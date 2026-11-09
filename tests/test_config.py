import pytest
from pydantic import ValidationError

from anime_importer.config import Settings


def test_demo_without_keys_is_valid():
    settings = Settings(_env_file=None, demo=True)

    assert settings.gemini_api_key is None
    assert settings.mal_client_id is None


def test_without_keys_and_without_demo_names_the_missing_ones():
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, demo=False)

    message = str(excinfo.value)
    assert "GEMINI_API_KEY" in message
    assert "MAL_CLIENT_ID" in message
    assert "DEMO=1" in message


def test_only_the_missing_key_is_named():
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, gemini_api_key="k")

    message = str(excinfo.value)
    assert "MAL_CLIENT_ID" in message
    assert "GEMINI_API_KEY" not in message


def test_with_keys_is_valid():
    settings = Settings(_env_file=None, gemini_api_key="k", mal_client_id="m")

    assert settings.demo is False


def test_host_and_port_defaults():
    settings = Settings(_env_file=None, demo=True)

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_host_and_port_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")

    settings = Settings(_env_file=None, demo=True)

    assert settings.host == "0.0.0.0"
    assert settings.port == 9000


def test_cache_paths_default_to_the_user_cache_dir():
    from platformdirs import user_cache_path

    settings = Settings(_env_file=None, demo=True)

    folder = user_cache_path("anime-importer", appauthor=False)
    assert settings.normalization_cache_dir == folder / "normalization"
    assert settings.details_cache_path == folder / "mal_details.json"


def test_computing_the_default_cache_paths_creates_no_folders(monkeypatch, tmp_path):
    from anime_importer import config

    monkeypatch.setattr(config, "_cache_dir", lambda: tmp_path / "cache")

    settings = Settings(_env_file=None, demo=True)

    assert settings.normalization_cache_dir == tmp_path / "cache" / "normalization"
    assert not (tmp_path / "cache").exists()


def test_cache_paths_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMALIZATION_CACHE_DIR", str(tmp_path / "norm"))
    monkeypatch.setenv("DETAILS_CACHE_PATH", str(tmp_path / "details.json"))

    settings = Settings(_env_file=None, demo=True)

    assert settings.normalization_cache_dir == tmp_path / "norm"
    assert settings.details_cache_path == tmp_path / "details.json"
