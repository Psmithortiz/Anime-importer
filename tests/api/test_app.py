from fastapi.testclient import TestClient

from anime_importer.api.app import create_app
from anime_importer.api.registry import ManagedSession
from anime_importer.domain.models import AiringStatus, AnimeCandidate, MediaType, NormalizedTitle
from anime_importer.ports import NormalizationError
from anime_importer.services.import_session import ImportSession

RESULTS = {
    "hellsing": [
        AnimeCandidate(10, "Hellsing", image_url="http://img/10.jpg"),
        AnimeCandidate(
            20,
            "Hellsing",
            image_url="http://img/20.jpg",
            media_type=MediaType.TV,
            year=2001,
            episodes=13,
            airing_status=AiringStatus.FINISHED,
        ),
    ],
}


class FakeNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


class FailingNormalizer:
    def normalize(self, titles, on_progress=None):
        raise NormalizationError("Gemini is not responding")


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
    assert done["summary"] == {
        "imported": 1,
        "by_status": {
            "completed": 1,
            "watching": 0,
            "plan_to_watch": 0,
            "on_hold": 0,
            "dropped": 0,
        },
        "rejected": [],
    }
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
        {"title": "hellsing", "reason": "Discarded in search menu (query: hellsing)"}
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
    assert view["error"] == "Gemini is not responding"


def test_root_serves_static_page():
    assert _client().get("/").status_code == 200


def test_static_assets_are_served():
    client = _client()

    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200


def test_candidate_option_exposes_mal_metadata():
    client = _client()
    session_id = _create(client)

    options = client.get(f"/api/sessions/{session_id}").json()["question"]["options"]

    assert options[1]["media_type"] == "tv"
    assert options[1]["year"] == 2001
    assert options[1]["episodes"] == 13
    assert options[1]["airing_status"] == "finished"


def test_choose_many_flow_and_by_status():
    client = _client()
    session_id = _create(client)

    view = client.post(
        f"/api/sessions/{session_id}/choose-many",
        json={
            "selections": [
                {"mal_id": 10, "status": "watching"},
                {"mal_id": 20, "status": "dropped"},
            ]
        },
    ).json()

    assert view["status"] == "finished"
    assert view["summary"]["imported"] == 2
    assert view["summary"]["by_status"]["watching"] == 1
    assert view["summary"]["by_status"]["dropped"] == 1
    assert view["summary"]["by_status"]["completed"] == 0


def test_candidate_option_has_suggested_status():
    client = _client()
    session_id = _create(client)

    options = client.get(f"/api/sessions/{session_id}").json()["question"]["options"]

    assert options[1]["suggested_status"] == "completed"


def test_choose_many_empty_is_422():
    client = _client()
    session_id = _create(client)

    response = client.post(f"/api/sessions/{session_id}/choose-many", json={"selections": []})

    assert response.status_code == 422


def test_choose_many_invalid_status_is_422():
    client = _client()
    session_id = _create(client)

    response = client.post(
        f"/api/sessions/{session_id}/choose-many",
        json={"selections": [{"mal_id": 10, "status": "nope"}]},
    )

    assert response.status_code == 422


def test_choose_many_out_of_range_is_422_and_keeps_question():
    client = _client()
    session_id = _create(client)

    response = client.post(
        f"/api/sessions/{session_id}/choose-many",
        json={"selections": [{"mal_id": 999, "status": "completed"}]},
    )

    assert response.status_code == 422
    assert client.get(f"/api/sessions/{session_id}").json()["status"] == "question"


def test_choose_many_after_finished_is_409():
    client = _client()
    session_id = _create(client)
    client.post(f"/api/sessions/{session_id}/discard")

    response = client.post(
        f"/api/sessions/{session_id}/choose-many",
        json={"selections": [{"mal_id": 10, "status": "completed"}]},
    )

    assert response.status_code == 409


def test_export_overwrite_flag():
    client = _client()
    session_id = _create(client)
    client.post(f"/api/sessions/{session_id}/choose", json={"option": 1})

    default = client.get(f"/api/sessions/{session_id}/export.xml")
    forced = client.get(f"/api/sessions/{session_id}/export.xml?overwrite=true")

    assert "<update_on_import>0</update_on_import>" in default.text
    assert "<update_on_import>1</update_on_import>" in forced.text


class ProgressNormalizer:
    def normalize(self, titles, on_progress=None):
        if on_progress is not None:
            on_progress(len(titles), len(titles))
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


def test_final_view_has_no_normalization_progress():
    client = _client(ProgressNormalizer())
    session_id = _create(client)

    view = client.get(f"/api/sessions/{session_id}").json()

    assert view["status"] == "question"
    assert view["normalization"] is None


def test_view_includes_normalization_progress_while_normalizing():
    session = ImportSession(["a", "b", "c"], ProgressNormalizer(), FakeSearcher())
    session.start()  # reports (3, 3)
    managed = ManagedSession(id="x", session=session, status="normalizing")

    view = managed.view()

    assert view.status == "normalizing"
    assert view.normalization is not None
    assert (view.normalization.done, view.normalization.total) == (3, 3)
