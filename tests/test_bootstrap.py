import pytest

from anime_importer import bootstrap
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
        _env_file=None,
        gemini_api_key="k",
        mal_client_id="m",
        normalization_cache_dir=tmp_path / "norm",
        details_cache_path=tmp_path / "details.json",
    )


def test_without_franchise_no_details_provider_is_created(monkeypatch, settings):
    monkeypatch.setattr(bootstrap, "MalDetailsProvider", RecordingDetails)

    session = bootstrap.build_session(settings, ["a"], with_franchise=False)

    assert RecordingDetails.created == 0
    assert session._franchise_finder is None


def test_with_franchise_builds_a_finder(monkeypatch, settings):
    monkeypatch.setattr(bootstrap, "MalDetailsProvider", RecordingDetails)

    session = bootstrap.build_session(settings, ["a"])

    assert RecordingDetails.created == 1
    assert session._franchise_finder is not None


def test_cli_builds_session_without_franchise(monkeypatch, tmp_path):
    from anime_importer import cli

    calls = []

    def fake_build(settings, titles, with_franchise=True):
        calls.append(with_franchise)
        raise ValueError("stop here")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MAL_CLIENT_ID", "m")
    monkeypatch.setattr(cli, "build_session", fake_build)
    (tmp_path / "list.txt").write_text("naruto\n", encoding="utf-8")

    assert cli.main(["--input", str(tmp_path / "list.txt")]) == 1
    assert calls == [False]
