import sys

import pytest

from anime_importer import launcher
from anime_importer.config import Settings
from anime_importer.launcher import bind_socket, running_mode


@pytest.fixture
def sockets():
    opened = []
    yield opened
    for sock in opened:
        sock.close()


def _occupy(sockets):
    sock = bind_socket("127.0.0.1", 0)
    sockets.append(sock)
    return sock, sock.getsockname()[1]


def _settings(port, demo=True):
    return Settings(demo=demo, port=port)


class _Run:
    """Collects what main() hands to serve() and open_browser()."""

    def __init__(self):
        self.urls = []
        self.served = []
        self.ports = []

    def open_browser(self, url):
        self.urls.append(url)

    def serve(self, settings, sock):
        self.served.append(settings)
        self.ports.append(sock.getsockname()[1])
        assert sock.fileno() != -1  # still open and listening while serving


def _free_port():
    sock = bind_socket("127.0.0.1", 0)
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_free_port_serves_on_it_and_opens_the_browser():
    port = _free_port()
    run = _Run()

    code = launcher.main(settings=_settings(port), open_browser=run.open_browser, serve=run.serve)

    assert code == 0
    assert run.ports == [port]
    assert run.served[0].port == port
    assert run.served[0].host == "127.0.0.1"
    assert run.urls == [f"http://127.0.0.1:{port}/"]


@pytest.mark.parametrize("demo", [True, False])
def test_busy_port_with_our_app_in_the_same_mode_only_opens_the_browser(sockets, demo):
    _, port = _occupy(sockets)
    run = _Run()

    code = launcher.main(
        settings=_settings(port, demo=demo),
        open_browser=run.open_browser,
        get_json=lambda url: {"app": "anime-importer", "demo": demo},
        serve=run.serve,
    )

    assert code == 0
    assert run.urls == [f"http://127.0.0.1:{port}/"]
    assert run.served == []


@pytest.mark.parametrize("demo", [True, False])
def test_busy_port_with_our_app_in_the_other_mode_uses_a_free_port(sockets, capsys, demo):
    _, busy = _occupy(sockets)
    run = _Run()

    code = launcher.main(
        settings=_settings(busy, demo=demo),
        open_browser=run.open_browser,
        get_json=lambda url: {"app": "anime-importer", "demo": not demo},
        serve=run.serve,
    )

    assert code == 0
    assert run.ports[0] != busy
    assert run.served[0].port == run.ports[0]
    assert run.served[0].demo is demo
    assert run.urls == [f"http://127.0.0.1:{run.ports[0]}/"]
    running, starting = ("normal", "demo") if demo else ("demo", "normal")
    assert (
        f"Anime Importer is already running in {running} mode at http://127.0.0.1:{busy}/; "
        f"starting {starting} mode on a free port."
    ) in capsys.readouterr().out


@pytest.mark.parametrize("answer", [OSError("refused"), {"app": "other"}, ["x"]])
def test_busy_port_with_another_program_uses_a_free_port(sockets, answer):
    _, busy = _occupy(sockets)
    run = _Run()

    def get_json(url):
        if isinstance(answer, Exception):
            raise answer
        return answer

    code = launcher.main(
        settings=_settings(busy),
        open_browser=run.open_browser,
        get_json=get_json,
        serve=run.serve,
    )

    assert code == 0
    assert run.ports[0] != busy
    assert run.served[0].port == run.ports[0]
    assert run.urls == [f"http://127.0.0.1:{run.ports[0]}/"]


def test_bind_socket_fails_on_a_used_port_and_leaves_nothing_open(sockets):
    _, port = _occupy(sockets)

    with pytest.raises(OSError):
        bind_socket("127.0.0.1", port)


def test_running_mode_checks_the_marker():
    assert running_mode("http://x/", lambda url: {"app": "anime-importer", "demo": True}) is True
    assert running_mode("http://x/", lambda url: {"app": "anime-importer", "demo": False}) is False
    assert running_mode("http://x/", lambda url: {"demo": False}) is None
    assert running_mode("http://x/", lambda url: {"app": "other", "demo": True}) is None
    assert running_mode("http://x/", lambda url: [1]) is None


@pytest.mark.parametrize("demo", [{}, {"demo": None}, {"demo": "yes"}, {"demo": 1}])
def test_running_mode_is_none_when_demo_is_missing_or_not_a_bool(demo):
    assert running_mode("http://x/", lambda url: {"app": "anime-importer", **demo}) is None


def test_running_mode_is_none_on_any_error():
    def boom(url):
        raise TimeoutError

    assert running_mode("http://x/", boom) is None


def test_running_mode_asks_the_info_endpoint():
    asked = []

    def get_json(url):
        asked.append(url)
        return {}

    running_mode("http://127.0.0.1:8000/", get_json)

    assert asked == ["http://127.0.0.1:8000/api/info"]


def test_frozen_crash_waits_for_enter_and_exits_with_1(monkeypatch, capsys):
    prompts = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher, "main", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt))

    with pytest.raises(SystemExit) as excinfo:
        launcher.run_frozen_safe()

    assert excinfo.value.code == 1
    assert prompts == ["Press Enter to exit..."]
    assert "boom" in capsys.readouterr().err


def test_crash_when_not_frozen_is_reraised(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(launcher, "main", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        launcher.run_frozen_safe()


def test_keyboard_interrupt_exits_with_0(monkeypatch):
    monkeypatch.setattr(launcher, "main", lambda: (_ for _ in ()).throw(KeyboardInterrupt))

    with pytest.raises(SystemExit) as excinfo:
        launcher.run_frozen_safe()

    assert excinfo.value.code == 0


def test_normal_exit_uses_the_return_code(monkeypatch):
    monkeypatch.setattr(launcher, "main", lambda: 0)

    with pytest.raises(SystemExit) as excinfo:
        launcher.run_frozen_safe()

    assert excinfo.value.code == 0
