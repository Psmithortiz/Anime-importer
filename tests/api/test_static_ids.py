import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "anime_importer" / "api" / "static"


def test_every_element_id_used_by_the_script_exists_in_the_page():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    page = (STATIC / "index.html").read_text(encoding="utf-8")

    used = set(re.findall(r'\$\("([a-z][a-z0-9-]*)"\)', script))
    defined = set(re.findall(r'\bid="([^"]+)"', page))

    assert used - defined == set()


def test_the_script_never_inserts_markup_with_innerhtml():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))

    assert "innerHTML" not in code


def test_static_files_are_revalidated_but_the_api_is_untouched():
    from fastapi.testclient import TestClient
    from session_helpers import make_registry

    from anime_importer.api.app import create_app

    client = TestClient(create_app(make_registry(None, None)))

    for path in ("/", "/app.js"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-cache"

    etag = client.get("/app.js").headers["ETag"]
    again = client.get("/app.js", headers={"If-None-Match": etag})
    assert again.status_code == 304

    assert "Cache-Control" not in client.get("/api/info").headers


def test_icon_files_are_served():
    from fastapi.testclient import TestClient
    from session_helpers import make_registry

    from anime_importer.api.app import create_app

    client = TestClient(create_app(make_registry(None, None)))

    assert client.get("/favicon.ico").status_code == 200
    svg = client.get("/icon.svg")
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
