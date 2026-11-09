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


def test_config_file_path_uses_the_override(monkeypatch, tmp_path):
    from anime_importer.config import config_file_path

    monkeypatch.setenv("ANIME_IMPORTER_CONFIG_FILE", str(tmp_path / "x.json"))

    assert config_file_path() == tmp_path / "x.json"


def test_config_file_path_defaults_to_the_user_config_dir(monkeypatch):
    from platformdirs import user_config_path

    from anime_importer.config import config_file_path

    monkeypatch.delenv("ANIME_IMPORTER_CONFIG_FILE")

    assert config_file_path() == user_config_path("anime-importer", appauthor=False) / "config.json"


def test_missing_config_file_is_ignored():
    settings = Settings(_env_file=None, demo=True)

    assert settings.gemini_model == "gemini-2.5-flash"


def test_config_file_with_keys_allows_creating_settings(tmp_path):
    (tmp_path / "config.json").write_text('{"gemini_api_key": "g", "mal_client_id": "m"}')

    settings = Settings(_env_file=None)

    assert settings.gemini_api_key == "g"
    assert settings.mal_client_id == "m"


def test_config_file_value_is_used_when_nothing_overrides_it(tmp_path):
    (tmp_path / "config.json").write_text('{"gemini_model": "from-file"}')

    assert Settings(_env_file=None, demo=True).gemini_model == "from-file"


def test_dotenv_overrides_the_config_file(tmp_path):
    (tmp_path / "config.json").write_text('{"gemini_model": "from-file"}')
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_MODEL=from-dotenv\n")

    assert Settings(_env_file=env_file, demo=True).gemini_model == "from-dotenv"


def test_environment_overrides_dotenv_and_the_config_file(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text('{"gemini_model": "from-file"}')
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_MODEL=from-dotenv\n")
    monkeypatch.setenv("GEMINI_MODEL", "from-env")

    assert Settings(_env_file=env_file, demo=True).gemini_model == "from-env"


def test_invalid_json_names_the_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")

    with pytest.raises(ValueError, match="config.json"):
        Settings(_env_file=None, demo=True)


def test_non_object_json_names_the_file(tmp_path):
    (tmp_path / "config.json").write_text("[1, 2]")

    with pytest.raises(ValueError, match="config.json"):
        Settings(_env_file=None, demo=True)


def test_missing_keys_message_mentions_the_config_file():
    with pytest.raises(ValidationError, match="config file"):
        Settings(_env_file=None)
