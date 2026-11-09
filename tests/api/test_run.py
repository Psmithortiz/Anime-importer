from anime_importer.api import app as app_module


def test_run_passes_host_and_port_from_settings(monkeypatch):
    captured = {}
    runs = []

    class FakeConfig:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    class FakeServer:
        def __init__(self, config):
            captured["server_config"] = config

        def run(self):
            runs.append(True)

    monkeypatch.setenv("DEMO", "1")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9100")
    monkeypatch.setattr(app_module.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(app_module.uvicorn, "Server", FakeServer)

    app_module.run()

    assert captured["kwargs"]["host"] == "0.0.0.0"
    assert captured["kwargs"]["port"] == 9100
    assert captured["kwargs"]["factory"] is True
    assert isinstance(captured["server_config"], FakeConfig)
    assert runs == [True]


def test_build_server_returns_the_server_with_the_expected_config(monkeypatch):
    from anime_importer.config import Settings

    captured = {}

    class FakeConfig:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    class FakeServer:
        def __init__(self, config):
            self.config = config

    monkeypatch.setattr(app_module.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(app_module.uvicorn, "Server", FakeServer)

    server = app_module.build_server(Settings(host="127.0.0.1", port=9200, demo=True))

    assert isinstance(server, FakeServer)
    assert isinstance(server.config, FakeConfig)
    assert captured["args"] == ("anime_importer.api.app:create_app",)
    assert captured["kwargs"] == {"factory": True, "host": "127.0.0.1", "port": 9200}
