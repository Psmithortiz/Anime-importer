"""Desktop launcher: starts the web app on a free local port and opens the browser.

If the preferred port already runs our app in the same mode (normal or demo), it only opens that
instance; in the other mode, it starts its own on a free port (each mode has its own database).
"""

import json
import socket
import sys
import traceback
import urllib.request
import webbrowser
from collections.abc import Callable
from typing import Any

from anime_importer.api.app import build_server
from anime_importer.config import Settings

HOST = "127.0.0.1"

OpenBrowser = Callable[[str], Any]
GetJson = Callable[[str], Any]
Serve = Callable[[Settings, socket.socket], None]


def bind_socket(host: str, port: int) -> socket.socket:
    """Bind and listen. Port 0 lets the OS pick a free port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # On Windows SO_REUSEADDR lets a second process take a port that is already in use;
        # SO_EXCLUSIVEADDRUSE makes the bind fail instead, which is what we want to detect.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen()
    except OSError:
        sock.close()
        raise
    return sock


def _get_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


def running_mode(url: str, get_json: GetJson = _get_json) -> bool | None:
    """The `demo` flag of the Anime Importer at `url`, or None if it is not one (or does not say)."""
    try:
        data = get_json(f"{url}api/info")
    except Exception:  # noqa: BLE001 (any failure means "not our app")
        return None
    if not isinstance(data, dict) or data.get("app") != "anime-importer":
        return None
    demo = data.get("demo")
    return demo if isinstance(demo, bool) else None


def _mode_name(demo: bool) -> str:
    return "demo" if demo else "normal"


def _serve(settings: Settings, sock: socket.socket) -> None:
    build_server(settings).run(sockets=[sock])


def main(
    *,
    settings: Settings | None = None,
    open_browser: OpenBrowser = webbrowser.open,
    get_json: GetJson = _get_json,
    serve: Serve | None = None,
) -> int:
    settings = settings or Settings()
    serve = serve or _serve
    preferred_url = f"http://{HOST}:{settings.port}/"
    try:
        sock = bind_socket(HOST, settings.port)
    except OSError:
        running = running_mode(preferred_url, get_json)
        if running is None:
            print(f"Port {settings.port} is in use by another program; using a free port instead.")
        elif running == settings.demo:
            print(f"Anime Importer is already running at {preferred_url}")
            open_browser(preferred_url)
            return 0
        else:
            print(
                f"Anime Importer is already running in {_mode_name(running)} mode at "
                f"{preferred_url}; starting {_mode_name(settings.demo)} mode on a free port."
            )
        sock = bind_socket(HOST, 0)
    with sock:
        port = sock.getsockname()[1]
        url = f"http://{HOST}:{port}/"
        effective = settings.model_copy(update={"host": HOST, "port": port})
        print(f"Anime Importer is running at {url}")
        print("Close this window to stop.")
        # The socket is already listening, so the OS queues the browser's connection until
        # uvicorn starts accepting: no need to wait for the server before opening the page.
        open_browser(url)
        serve(effective, sock)
    return 0


def run_frozen_safe() -> None:
    """Entry point. In a frozen build, keeps the console open after a crash so it can be read."""
    try:
        code = main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        if not getattr(sys, "frozen", False):
            raise
        traceback.print_exc()
        input("Press Enter to exit...")
        sys.exit(1)
    sys.exit(code)
