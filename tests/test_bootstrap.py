import pytest

from anime_importer import bootstrap
from anime_importer.adapters.memory_repository import InMemorySessionRepository
from anime_importer.config import Settings


class RecordingDetails:
    created = 0

    def __init__(self, *args, **kwargs) -> None:
        type(self).created += 1
        self.throttle = kwargs.get("throttle")


@pytest.fixture
def settings(tmp_path):
    RecordingDetails.created = 0
    return Settings(
        gemini_api_key="k",
        mal_client_id="m",
        normalization_cache_dir=tmp_path / "norm",
        details_cache_path=tmp_path / "details.json",
    )


def test_without_franchise_no_details_provider_is_created(monkeypatch, settings):
    monkeypatch.setattr(bootstrap, "MalDetailsProvider", RecordingDetails)

    services = bootstrap.build_services(settings, InMemorySessionRepository(), with_franchise=False)

    assert RecordingDetails.created == 0
    assert services.franchise_finder is None


def test_with_franchise_builds_a_finder(monkeypatch, settings):
    monkeypatch.setattr(bootstrap, "MalDetailsProvider", RecordingDetails)

    services = bootstrap.build_services(settings, InMemorySessionRepository())

    assert RecordingDetails.created == 1
    assert services.franchise_finder is not None


def test_cli_builds_session_without_franchise(monkeypatch, tmp_path):
    from anime_importer import cli

    calls = []

    def fake_build(settings, repository, with_franchise=True):
        calls.append(with_franchise)
        raise ValueError("stop here")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MAL_CLIENT_ID", "m")
    monkeypatch.setattr(cli, "build_services", fake_build)
    (tmp_path / "list.txt").write_text("naruto\n", encoding="utf-8")

    assert cli.main(["--input", str(tmp_path / "list.txt")]) == 1
    assert calls == [False]


EMPTY_RECORDING = '{"normalizations": {}, "searches": {}, "details": {}}'


def test_demo_session_needs_no_keys_nor_real_adapters(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("real adapter instantiated in demo mode")

    monkeypatch.setattr(bootstrap.genai, "Client", forbidden)
    monkeypatch.setattr(bootstrap, "MalSearcher", forbidden)
    monkeypatch.setattr(bootstrap, "MalDetailsProvider", forbidden)
    monkeypatch.setattr(bootstrap, "CachingNormalizer", forbidden)
    monkeypatch.setattr(bootstrap, "CachingDetailsProvider", forbidden)
    (tmp_path / "recording.json").write_text(EMPTY_RECORDING, encoding="utf-8")
    settings = Settings(demo=True, demo_data_dir=tmp_path, demo_delay_seconds=0)

    services = bootstrap.build_services(settings, InMemorySessionRepository())

    assert services.franchise_finder is not None


def test_demo_session_without_franchise_has_no_finder(tmp_path):
    (tmp_path / "recording.json").write_text(EMPTY_RECORDING, encoding="utf-8")
    settings = Settings(demo=True, demo_data_dir=tmp_path)

    services = bootstrap.build_services(settings, InMemorySessionRepository(), with_franchise=False)

    assert services.franchise_finder is None


def test_two_sessions_of_the_same_services_share_the_adapters(tmp_path):
    (tmp_path / "recording.json").write_text(EMPTY_RECORDING, encoding="utf-8")
    settings = Settings(demo=True, demo_data_dir=tmp_path, demo_delay_seconds=0)
    services = bootstrap.build_services(settings, InMemorySessionRepository())

    first = services.new_session("one", ["a"])
    second = services.new_session("two", ["b"])

    assert first._searcher is second._searcher
    assert first._normalizer is second._normalizer
    assert first._franchise_finder is second._franchise_finder
    assert first._franchise_finder is services.franchise_finder


def test_restore_session_returns_none_for_unknown_ids(tmp_path):
    (tmp_path / "recording.json").write_text(EMPTY_RECORDING, encoding="utf-8")
    settings = Settings(demo=True, demo_data_dir=tmp_path)
    services = bootstrap.build_services(settings, InMemorySessionRepository())
    services.new_session("known", ["a"])

    assert services.restore_session("missing") is None
    restored = services.restore_session("known")
    assert restored is not None
    assert restored.id == "known"


def test_session_services_can_back_a_registry(tmp_path):
    from anime_importer.api.registry import SessionRegistry

    (tmp_path / "recording.json").write_text(EMPTY_RECORDING, encoding="utf-8")
    settings = Settings(demo=True, demo_data_dir=tmp_path)
    services = bootstrap.build_services(settings, InMemorySessionRepository())
    registry = SessionRegistry(services, run_in_background=lambda fn: None)

    managed = registry.create(["a", "b"])

    assert [item.id for item in registry.list_recent(5)] == [managed.id]
