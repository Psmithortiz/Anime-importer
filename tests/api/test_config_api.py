import json
import logging

import pytest
from fastapi.testclient import TestClient
from session_helpers import make_services

from anime_importer import bootstrap
from anime_importer.adapters.memory_repository import InMemorySessionRepository
from anime_importer.api.app import create_app
from anime_importer.api.registry import SessionRegistry
from anime_importer.bootstrap import FileConfigurator, build_provider
from anime_importer.config import Settings
from anime_importer.domain.models import AnimeCandidate, NormalizedTitle

GEMINI = "gemini-secret-key-1234"
MAL = "mal-secret-id-5678"


class _Normalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, t) for i, t in enumerate(titles, start=1)]


class _Searcher:
    def search(self, query):
        return [AnimeCandidate(1, "A"), AnimeCandidate(2, "B")]


@pytest.fixture
def env(monkeypatch, tmp_path):
    """No keys anywhere, no .env in the current folder, fake services instead of real adapters."""
    monkeypatch.chdir(tmp_path)
    for name in ("GEMINI_API_KEY", "MAL_CLIENT_ID", "DEMO"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        bootstrap,
        "build_services",
        lambda settings, repository, **kw: make_services(
            _Normalizer(), _Searcher(), repository=repository
        ),
    )
    return tmp_path


def _app(tmp_path):
    repository = InMemorySessionRepository()
    registry = SessionRegistry(
        build_provider(Settings(), repository), run_in_background=lambda fn: fn()
    )
    configurator = FileConfigurator(registry, repository, tmp_path / "config.json")
    app = create_app(registry, configurator=configurator, allowed_hosts=["testserver"])
    return TestClient(app), tmp_path / "config.json"


def test_starts_without_keys(env):
    client, _ = _app(env)

    assert client.get("/api/info").json()["configured"] is False
    assert client.get("/api/sessions").status_code == 200
    response = client.post("/api/sessions", json={"text": "naruto"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Configure your API keys first"


def test_saving_both_keys_configures_the_running_app(env):
    client, path = _app(env)

    response = client.put("/api/config", json={"gemini_api_key": GEMINI, "mal_client_id": MAL})

    body = response.json()
    assert response.status_code == 200
    assert body["configured"] is True
    assert body["restart_required"] is False
    assert {k["source"] for k in body["keys"]} == {"config_file"}
    assert json.loads(path.read_text()) == {"gemini_api_key": GEMINI, "mal_client_id": MAL}
    assert client.get("/api/info").json()["configured"] is True
    assert client.post("/api/sessions", json={"text": "naruto"}).status_code == 202


def test_saving_only_one_key_keeps_the_app_unconfigured(env):
    client, _ = _app(env)

    body = client.put("/api/config", json={"gemini_api_key": GEMINI}).json()

    assert body["configured"] is False
    assert client.post("/api/sessions", json={"text": "x"}).status_code == 409


def test_saving_when_configured_requires_restart_and_keeps_services(env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-aaaa")
    monkeypatch.setenv("MAL_CLIENT_ID", "env-mal-bbbb")
    client, _ = _app(env)
    monkeypatch.delenv("MAL_CLIENT_ID")  # editable now: the file is the only source

    before = client.app.state.registry._services
    # Settings are rebuilt on save: with MAL_CLIENT_ID unset it comes from the file.
    body = client.put("/api/config", json={"mal_client_id": MAL}).json()

    assert body["restart_required"] is True
    assert client.app.state.registry._services is before


def test_key_from_the_environment_cannot_be_changed(env, monkeypatch):
    client, path = _app(env)
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-aaaa")

    response = client.put("/api/config", json={"gemini_api_key": GEMINI})

    assert response.status_code == 409
    assert "environment variable" in response.json()["detail"]
    assert not path.exists()


def test_key_from_dotenv_cannot_be_changed(env):
    (env / ".env").write_text("MAL_CLIENT_ID=dotenv-mal-1111\n")
    client, _ = _app(env)

    response = client.put("/api/config", json={"mal_client_id": MAL})

    assert response.status_code == 409
    assert ".env" in response.json()["detail"]


def test_saving_in_demo_mode_is_rejected(env, monkeypatch):
    monkeypatch.setenv("DEMO", "1")
    client, path = _app(env)

    response = client.put("/api/config", json={"gemini_api_key": GEMINI})

    assert response.status_code == 409
    assert not path.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"gemini_api_key": GEMINI, "extra": "x"},
        {},
        {"gemini_api_key": "has space"},
        {"gemini_api_key": ""},
        {"gemini_api_key": "x" * 201},
    ],
)
def test_invalid_bodies_are_rejected(env, body):
    client, path = _app(env)

    assert client.put("/api/config", json=body).status_code == 422
    assert not path.exists()


def test_keys_are_stripped(env):
    client, path = _app(env)

    client.put("/api/config", json={"gemini_api_key": f"  {GEMINI}\n"})

    assert json.loads(path.read_text())["gemini_api_key"] == GEMINI


def test_non_json_content_type_is_rejected_even_with_a_valid_body(env):
    client, path = _app(env)

    response = client.put(
        "/api/config",
        content=json.dumps({"gemini_api_key": GEMINI}),
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 422
    assert not path.exists()


def test_unknown_host_is_rejected(env):
    client, _ = _app(env)

    response = client.get("/api/info", headers={"Host": "evil.example"})

    assert response.status_code == 400


def test_responses_and_logs_never_contain_the_key(env, caplog):
    client, _ = _app(env)
    caplog.set_level(logging.DEBUG)

    response = client.put("/api/config", json={"gemini_api_key": GEMINI, "mal_client_id": MAL})
    status = client.get("/api/config")

    for text in (response.text, status.text, caplog.text):
        assert GEMINI not in text
        assert MAL not in text


def test_config_endpoints_are_404_without_a_configurator():
    from session_helpers import make_registry

    client = TestClient(create_app(make_registry(_Normalizer(), _Searcher())))

    assert client.get("/api/config").status_code == 404
    assert client.put("/api/config", json={"gemini_api_key": "k"}).status_code == 404
