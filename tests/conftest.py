import pytest


@pytest.fixture(autouse=True)
def _isolated_config_file(monkeypatch, tmp_path):
    """Point the config file at a path that does not exist, so no test reads the real one."""
    monkeypatch.setenv("ANIME_IMPORTER_CONFIG_FILE", str(tmp_path / "config.json"))
