from fastapi.testclient import TestClient
from platformdirs import user_data_path

from anime_importer import config
from anime_importer.api.app import create_app
from anime_importer.config import Settings


def test_database_paths_default_to_the_user_data_dir():
    settings = Settings(_env_file=None, demo=True)

    folder = user_data_path("anime-importer", appauthor=False)
    assert settings.database_path == folder / "sessions.db"
    assert settings.demo_database_path == folder / "demo.db"


def test_computing_the_default_database_paths_creates_no_folders(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_data_dir", lambda: tmp_path / "data")

    settings = Settings(_env_file=None, demo=True)

    assert settings.database_path == tmp_path / "data" / "sessions.db"
    assert not (tmp_path / "data").exists()


def test_database_path_comes_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mine.db"))
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(tmp_path / "mine-demo.db"))

    settings = Settings(_env_file=None, demo=True)

    assert settings.database_path == tmp_path / "mine.db"
    assert settings.demo_database_path == tmp_path / "mine-demo.db"


def test_create_app_without_registry_uses_the_demo_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("DEMO_DELAY_SECONDS", "0")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "real.db"))
    monkeypatch.setenv("DEMO_DATABASE_PATH", str(tmp_path / "sub" / "demo.db"))
    monkeypatch.chdir(tmp_path)

    client = TestClient(create_app())

    assert client.get("/api/info").json()["demo"] is True
    assert (tmp_path / "sub" / "demo.db").exists()
    assert not (tmp_path / "real.db").exists()
