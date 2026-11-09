import pytest

from anime_importer.config import Settings


def test_demo_without_keys_is_valid():
    settings = Settings(demo=True)

    assert settings.gemini_api_key is None
    assert settings.mal_client_id is None


def test_missing_keys_names_the_missing_ones():
    settings = Settings(demo=False)

    assert settings.missing_keys() == ["GEMINI_API_KEY", "MAL_CLIENT_ID"]


def test_only_the_missing_key_is_named():
    settings = Settings(gemini_api_key="k")

    assert settings.missing_keys() == ["MAL_CLIENT_ID"]


def test_missing_keys_is_empty_in_demo_mode():
    assert Settings(demo=True).missing_keys() == []


def test_with_keys_is_valid():
    settings = Settings(gemini_api_key="k", mal_client_id="m")

    assert settings.demo is False


def test_host_and_port_defaults():
    settings = Settings(demo=True)

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_host_and_port_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")

    settings = Settings(demo=True)

    assert settings.host == "0.0.0.0"
    assert settings.port == 9000


def test_cache_paths_default_to_the_user_cache_dir():
    from platformdirs import user_cache_path

    settings = Settings(demo=True)

    folder = user_cache_path("anime-importer", appauthor=False)
    assert settings.normalization_cache_dir == folder / "normalization"
    assert settings.details_cache_path == folder / "mal_details.json"


def test_computing_the_default_cache_paths_creates_no_folders(monkeypatch, tmp_path):
    from anime_importer import config

    monkeypatch.setattr(config, "_cache_dir", lambda: tmp_path / "cache")

    settings = Settings(demo=True)

    assert settings.normalization_cache_dir == tmp_path / "cache" / "normalization"
    assert not (tmp_path / "cache").exists()


def test_cache_paths_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("NORMALIZATION_CACHE_DIR", str(tmp_path / "norm"))
    monkeypatch.setenv("DETAILS_CACHE_PATH", str(tmp_path / "details.json"))

    settings = Settings(demo=True)

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
    settings = Settings(demo=True)

    assert settings.gemini_model == "gemini-2.5-flash"


def test_config_file_with_keys_allows_creating_settings(tmp_path):
    (tmp_path / "config.json").write_text('{"gemini_api_key": "g", "mal_client_id": "m"}')

    settings = Settings()

    assert settings.gemini_api_key == "g"
    assert settings.mal_client_id == "m"


def test_config_file_value_is_used_when_nothing_overrides_it(tmp_path):
    (tmp_path / "config.json").write_text('{"gemini_model": "from-file"}')

    assert Settings(demo=True).gemini_model == "from-file"


def test_environment_overrides_the_config_file(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text('{"gemini_model": "from-file"}')
    monkeypatch.setenv("GEMINI_MODEL", "from-env")

    assert Settings(demo=True).gemini_model == "from-env"


def test_a_dotenv_file_in_the_current_folder_is_no_longer_read(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MAL_CLIENT_ID", raising=False)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=k\nMAL_CLIENT_ID=m\n")

    assert Settings().missing_keys() == ["GEMINI_API_KEY", "MAL_CLIENT_ID"]


def test_invalid_json_names_the_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")

    with pytest.raises(ValueError, match="config.json"):
        Settings(demo=True)


def test_non_object_json_names_the_file(tmp_path):
    (tmp_path / "config.json").write_text("[1, 2]")

    with pytest.raises(ValueError, match="config.json"):
        Settings(demo=True)


def _status(settings, tmp_path):
    from anime_importer.config import key_status

    return {s.name: s for s in key_status(settings, tmp_path / "config.json")}


def test_key_status_missing(tmp_path):
    from anime_importer.config import KeySource

    statuses = _status(Settings(), tmp_path)

    assert statuses["GEMINI_API_KEY"].source is KeySource.MISSING
    assert statuses["GEMINI_API_KEY"].masked is None


def test_key_status_sources_and_priority(monkeypatch, tmp_path):
    from anime_importer.config import KeySource

    (tmp_path / "config.json").write_text(
        '{"gemini_api_key": "file-key-1234", "mal_client_id": "file-mal-5678"}'
    )
    statuses = _status(Settings(), tmp_path)
    assert statuses["GEMINI_API_KEY"].source is KeySource.CONFIG_FILE
    assert statuses["MAL_CLIENT_ID"].source is KeySource.CONFIG_FILE

    monkeypatch.setenv("GEMINI_API_KEY", "env-key-0000")
    statuses = _status(Settings(), tmp_path)
    assert statuses["GEMINI_API_KEY"].source is KeySource.ENVIRONMENT
    assert statuses["GEMINI_API_KEY"].masked == "••••0000"


def test_masked_never_shows_more_than_the_last_four(tmp_path):
    from anime_importer.config import mask_key

    assert mask_key("abcdefghijkl") == "••••ijkl"
    assert mask_key("abcdefgh") == "••••"
    assert mask_key("abc") == "••••"
    settings = Settings(gemini_api_key="supersecretkey", mal_client_id="m")
    for status in _status(settings, tmp_path).values():
        assert "supersecret" not in (status.masked or "")
