from fastapi.testclient import TestClient

from anime_importer.api.app import create_app
from anime_importer.domain.models import AnimeCandidate, NormalizedTitle
from anime_importer.ports import NormalizationError
from anime_importer.services.import_session import ImportSession

RESULTS = {
    "hellsing": [
        AnimeCandidate(10, "Hellsing", image_url="http://img/10.jpg"),
        AnimeCandidate(20, "Hellsing", image_url="http://img/20.jpg"),
    ],
}


class FakeNormalizer:
    def normalize(self, titles):
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


class FailingNormalizer:
    def normalize(self, titles):
        raise NormalizationError("Gemini no responde")


class FakeSearcher:
    def search(self, query):
        return RESULTS.get(query, [])


def _client(normalizer=None) -> TestClient:
    def factory(titles):
        return ImportSession(titles, normalizer or FakeNormalizer(), FakeSearcher())

    return TestClient(create_app(factory))


def _create(client: TestClient, text: str = "hellsing") -> str:
    response = client.post("/api/sessions", json={"text": text})
    assert response.status_code == 202
    assert response.json()["status"] == "normalizing"
    return response.json()["id"]


def test_full_flow_and_export():
    client = _client()
    session_id = _create(client)

    view = client.get(f"/api/sessions/{session_id}").json()
    assert view["status"] == "question"
    assert view["progress"] == {"done": 0, "total": 1}
    assert view["question"]["kind"] == "candidate"
    assert view["question"]["query"] == "hellsing"
    options = view["question"]["options"]
    assert [o["number"] for o in options] == [1, 2]
    assert [o["mal_id"] for o in options] == [10, 20]
    assert options[1]["image_url"] == "http://img/20.jpg"

    done = client.post(f"/api/sessions/{session_id}/choose", json={"option": 2}).json()
    assert done["status"] == "finished"
    assert done["summary"] == {"imported": 1, "rejected": []}
    assert done["question"] is None

    export = client.get(f"/api/sessions/{session_id}/export.xml")
    assert export.status_code == 200
    assert "xml" in export.headers["content-type"]
    assert "anime_import.xml" in export.headers["content-disposition"]
    assert "<series_animedb_id>20</series_animedb_id>" in export.text


def test_discard_records_rejection():
    client = _client()
    session_id = _create(client)

    view = client.post(f"/api/sessions/{session_id}/discard").json()

    assert view["status"] == "finished"
    assert view["summary"]["imported"] == 0
    assert view["summary"]["rejected"] == [
        {"title": "hellsing", "reason": "Descartado en menú de búsqueda (query: hellsing)"}
    ]


def test_choose_out_of_range_is_422_and_keeps_question():
    client = _client()
    session_id = _create(client)

    response = client.post(f"/api/sessions/{session_id}/choose", json={"option": 9})

    assert response.status_code == 422
    assert client.get(f"/api/sessions/{session_id}").json()["status"] == "question"


def test_choose_option_zero_is_422():
    client = _client()
    session_id = _create(client)

    response = client.post(f"/api/sessions/{session_id}/choose", json={"option": 0})

    assert response.status_code == 422


def test_export_before_finished_is_409():
    client = _client()
    session_id = _create(client)

    assert client.get(f"/api/sessions/{session_id}/export.xml").status_code == 409


def test_choose_and_discard_after_finished_are_409():
    client = _client()
    session_id = _create(client)
    client.post(f"/api/sessions/{session_id}/discard")

    assert client.post(f"/api/sessions/{session_id}/choose", json={"option": 1}).status_code == 409
    assert client.post(f"/api/sessions/{session_id}/discard").status_code == 409


def test_unknown_session_is_404():
    client = _client()

    assert client.get("/api/sessions/nope").status_code == 404
    assert client.post("/api/sessions/nope/discard").status_code == 404
    assert client.get("/api/sessions/nope/export.xml").status_code == 404


def test_blank_text_is_422():
    client = _client()

    response = client.post("/api/sessions", json={"text": "  \n \n\n"})

    assert response.status_code == 422


def test_normalization_failure_shows_failed_status():
    client = _client(FailingNormalizer())
    session_id = _create(client)

    view = client.get(f"/api/sessions/{session_id}").json()

    assert view["status"] == "failed"
    assert view["error"] == "Gemini no responde"


def test_root_serves_static_page():
    assert _client().get("/").status_code == 200


def test_static_assets_are_served():
    client = _client()

    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200
