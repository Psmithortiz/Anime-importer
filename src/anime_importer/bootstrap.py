import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai

from anime_importer.adapters.config_file import save_config
from anime_importer.adapters.demo import (
    DemoRecording,
    ReplayDetailsProvider,
    ReplayNormalizer,
    ReplaySearcher,
)
from anime_importer.adapters.details_cache import CachingDetailsProvider
from anime_importer.adapters.gemini import GeminiNormalizer, cache_version
from anime_importer.adapters.http import Throttle
from anime_importer.adapters.mal import MalDetailsProvider, MalSearcher
from anime_importer.adapters.normalization_cache import CachingNormalizer, JsonCacheStore
from anime_importer.api.registry import InvalidStateError, NotConfiguredError, SessionRegistry
from anime_importer.api.schemas import ConfigView, KeyStatusOut
from anime_importer.config import KeySource, Settings, key_status
from anime_importer.domain.models import Franchise
from anime_importer.domain.session import SessionSummary
from anime_importer.ports import (
    AnimeDetailsProvider,
    AnimeSearcher,
    SessionRepository,
    TitleNormalizer,
)
from anime_importer.services.franchise import discover_franchise
from anime_importer.services.import_session import (
    BackgroundRunner,
    FranchiseFinder,
    ImportSession,
)


def build_real_adapters(
    settings: Settings, with_details: bool = True
) -> tuple[TitleNormalizer, AnimeSearcher, AnimeDetailsProvider | None]:
    """Build the real Gemini and MAL adapters (with their caches and a shared MAL throttle).

    The details provider is only created when `with_details` is true; otherwise it is None.
    """
    if not settings.gemini_api_key or not settings.mal_client_id:
        raise ValueError("GEMINI_API_KEY and MAL_CLIENT_ID are required outside demo mode")
    client = genai.Client(api_key=settings.gemini_api_key)
    gemini = GeminiNormalizer(
        client=client, model=settings.gemini_model, chunk_size=settings.gemini_chunk_size
    )
    store = JsonCacheStore(
        settings.normalization_cache_dir / f"{cache_version(settings.gemini_model)}.json"
    )
    normalizer = CachingNormalizer(inner=gemini, store=store)
    # One throttle for every MAL adapter so they share the same request budget.
    mal_throttle = Throttle(1.0)
    searcher = MalSearcher(client_id=settings.mal_client_id, throttle=mal_throttle)
    details: AnimeDetailsProvider | None = None
    if with_details:
        details = CachingDetailsProvider(
            MalDetailsProvider(client_id=settings.mal_client_id, throttle=mal_throttle),
            path=settings.details_cache_path,
            ttl_seconds=settings.details_cache_ttl_days * 24 * 3600,
        )
    return normalizer, searcher, details


@dataclass(frozen=True, slots=True)
class SessionServices:
    """Adapters shared by every session of the app, built once by `build_services`."""

    repository: SessionRepository
    normalizer: TitleNormalizer
    searcher: AnimeSearcher
    franchise_finder: FranchiseFinder | None
    resolution_buffer: int
    run_in_background: BackgroundRunner | None = None  # None: ImportSession's default (a thread)

    def _deps(self) -> dict[str, Any]:
        deps: dict[str, Any] = {
            "normalizer": self.normalizer,
            "searcher": self.searcher,
            "franchise_finder": self.franchise_finder,
            "resolution_buffer": self.resolution_buffer,
        }
        if self.run_in_background is not None:
            deps["run_in_background"] = self.run_in_background
        return deps

    def new_session(self, session_id: str, titles: Sequence[str]) -> ImportSession:
        return ImportSession.create(session_id, titles, repository=self.repository, **self._deps())

    def list_recent(self, limit: int) -> list[SessionSummary]:
        return self.repository.list_recent(limit)

    def restore_session(self, session_id: str) -> ImportSession | None:
        """Rebuild a stored session, or None if it does not exist."""
        stored = self.repository.load(session_id)
        if stored is None:
            return None
        return ImportSession(stored, repository=self.repository, **self._deps())


def build_services(
    settings: Settings, repository: SessionRepository, with_franchise: bool = True
) -> SessionServices:
    """Composition root: the only place that decides which concrete adapters are used.

    Adapters (and their throttle and caches) are built ONCE and shared by every session.
    """
    normalizer: TitleNormalizer
    searcher: AnimeSearcher
    details: AnimeDetailsProvider | None
    if settings.demo:
        recording = DemoRecording.load(settings.demo_data_dir / "recording.json")
        delay = settings.demo_delay_seconds
        normalizer = ReplayNormalizer(recording, delay, chunk_size=settings.gemini_chunk_size)
        searcher = ReplaySearcher(recording, delay)
        details = ReplayDetailsProvider(recording) if with_franchise else None
    else:
        normalizer, searcher, details = build_real_adapters(settings, with_details=with_franchise)
    finder: FranchiseFinder | None = None
    if details is not None:
        provider = details

        def find_franchise(seed_ids: Sequence[int]) -> Franchise:
            return discover_franchise(seed_ids, provider, settings.franchise_max_nodes)

        finder = find_franchise
    return SessionServices(
        repository=repository,
        normalizer=normalizer,
        searcher=searcher,
        franchise_finder=finder,
        resolution_buffer=settings.resolution_buffer,
    )


class UnconfiguredServices:
    """Stands in for SessionServices while the API keys are missing.

    Past sessions can still be listed; creating or restoring one needs the keys.
    """

    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    def new_session(self, session_id: str, titles: Sequence[str]) -> ImportSession:
        raise NotConfiguredError

    def restore_session(self, session_id: str) -> ImportSession | None:
        raise NotConfiguredError

    def list_recent(self, limit: int) -> list[SessionSummary]:
        return self._repository.list_recent(limit)


def build_provider(
    settings: Settings, repository: SessionRepository
) -> SessionServices | UnconfiguredServices:
    """Real services if the app can run (demo or all keys set); otherwise a placeholder."""
    if settings.demo or not settings.missing_keys():
        return build_services(settings, repository)
    return UnconfiguredServices(repository)


class FileConfigurator:
    """Shows and saves the API keys. Writes only to the per-user config file.

    If the app started unconfigured, saving the missing keys builds the real services and swaps
    them into the registry. If it was already configured, the keys are saved but the running
    adapters are kept (a second set would break "adapters once per app"): a restart is required.
    """

    def __init__(
        self, registry: SessionRegistry, repository: SessionRepository, config_path: Path
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._config_path = config_path
        self._lock = threading.Lock()
        settings = Settings()
        self._demo = settings.demo
        self._configured = settings.demo or not settings.missing_keys()
        self._restart_required = False

    @property
    def configured(self) -> bool:
        return self._configured

    def status(self) -> ConfigView:
        settings = Settings()
        return ConfigView(
            demo=self._demo,
            configured=self._configured,
            restart_required=self._restart_required,
            keys=[
                KeyStatusOut(name=k.name, source=k.source, masked=k.masked)
                for k in key_status(settings, config_path=self._config_path)
            ],
        )

    def save(self, updates: Mapping[str, str]) -> ConfigView:
        if self._demo:
            raise InvalidStateError("Demo mode does not use API keys")
        with self._lock:
            locked = {
                k.name.lower()
                for k in key_status(Settings(), config_path=self._config_path)
                if k.source is KeySource.ENVIRONMENT
            }
            for field in updates:
                if field in locked:
                    raise InvalidStateError(
                        f"{field.upper()} is set by an environment variable; change it there"
                    )
            save_config(self._config_path, updates)
            new_settings = Settings()
            if not self._configured:
                if not new_settings.missing_keys():
                    self._registry.replace_services(build_services(new_settings, self._repository))
                    self._configured = True
            else:
                self._restart_required = True
            return self.status()
