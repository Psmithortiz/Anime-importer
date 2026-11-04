from fastapi.testclient import TestClient

from anime_importer.api.app import create_app
from anime_importer.domain.models import (
    AiringStatus,
    AnimeCandidate,
    Franchise,
    FranchiseEntry,
    MediaType,
    NormalizedTitle,
    RelationType,
)
from anime_importer.services.import_session import ImportSession

SEQUEL = AnimeCandidate(
    30,
    "Hellsing Ultimate",
    image_url="http://img/30.jpg",
    media_type=MediaType.OVA,
    year=2006,
    episodes=10,
    airing_status=AiringStatus.AIRING,
)
FRANCHISE = Franchise(entries=(FranchiseEntry(SEQUEL, RelationType.SEQUEL),), truncated=True)


class FakeNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


class FakeSearcher:
    def search(self, query):
        return [AnimeCandidate(10, "Hellsing")]


def _client() -> TestClient:
    def factory(titles):
        return ImportSession(
            titles,
            FakeNormalizer(),
            FakeSearcher(),
            franchise_finder=lambda seeds: FRANCHISE,
            run_in_background=lambda fn: fn(),
        )

    return TestClient(create_app(factory))


def _create(client: TestClient) -> str:
    return client.post("/api/sessions", json={"text": "hellsing"}).json()["id"]


def test_question_exposes_franchise_truncated_and_preselected():
    client = _client()
    session_id = _create(client)

    question = client.get(f"/api/sessions/{session_id}").json()["question"]

    assert question["preselected"] == [10]
    assert question["franchise_truncated"] is True
    assert question["options"][0]["mal_id"] == 10
    assert question["franchise"] == [
        {
            "mal_id": 30,
            "label": "Hellsing Ultimate",
            "image_url": "http://img/30.jpg",
            "media_type": "ova",
            "year": 2006,
            "episodes": 10,
            "airing_status": "airing",
            "suggested_status": "watching",
            "relation": "sequel",
        }
    ]


def test_choose_many_by_mal_id_including_franchise_entry():
    client = _client()
    session_id = _create(client)

    view = client.post(
        f"/api/sessions/{session_id}/choose-many",
        json={
            "selections": [
                {"mal_id": 10, "status": "completed"},
                {"mal_id": 30, "status": "plan_to_watch"},
            ]
        },
    ).json()

    assert view["status"] == "finished"
    assert view["summary"]["imported"] == 2
    assert view["summary"]["by_status"]["plan_to_watch"] == 1


def test_choose_many_unknown_mal_id_is_422_and_keeps_question():
    client = _client()
    session_id = _create(client)

    response = client.post(
        f"/api/sessions/{session_id}/choose-many",
        json={"selections": [{"mal_id": 999, "status": "completed"}]},
    )

    assert response.status_code == 422
    assert client.get(f"/api/sessions/{session_id}").json()["status"] == "question"
