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
