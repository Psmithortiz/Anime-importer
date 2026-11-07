from collections.abc import Sequence

from google import genai

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
from anime_importer.config import Settings
from anime_importer.domain.models import Franchise
from anime_importer.ports import AnimeDetailsProvider, AnimeSearcher, TitleNormalizer
from anime_importer.services.franchise import discover_franchise
from anime_importer.services.import_session import FranchiseFinder, ImportSession


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


def build_session(
    settings: Settings, titles: Sequence[str], with_franchise: bool = True
) -> ImportSession:
    """Composition root: the only place that decides which concrete adapters are used."""
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
    return ImportSession(
        titles,
        normalizer=normalizer,
        searcher=searcher,
        franchise_finder=finder,
        resolution_buffer=settings.resolution_buffer,
    )
