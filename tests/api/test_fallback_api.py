from fastapi.testclient import TestClient
from session_helpers import make_session

from anime_importer.api.app import create_app
from anime_importer.domain.models import AnimeCandidate, NormalizedTitle

TIE = [AnimeCandidate(10, "Hellsing"), AnimeCandidate(20, "Hellsing")]


class RomajiNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, "Hellsingu") for i, _ in enumerate(titles, start=1)]


class OriginalOnlySearcher:
    def search(self, query):
        return TIE if query == "hellsing" else []


def _question(normalizer, searcher):
    def factory(session_id, titles):
        return make_session(titles, normalizer, searcher, run_in_background=lambda fn: fn())

    client = TestClient(create_app(factory))
    session_id = client.post("/api/sessions", json={"text": "hellsing"}).json()["id"]
    return client.get(f"/api/sessions/{session_id}").json()["question"]


def test_question_reports_used_fallback_and_original_query():
    question = _question(RomajiNormalizer(), OriginalOnlySearcher())

    assert question["used_fallback"] is True
    assert question["query"] == "hellsing"


def test_question_without_fallback_reports_false():
    class DirectSearcher:
        def search(self, query):
            return TIE

    question = _question(RomajiNormalizer(), DirectSearcher())

    assert question["used_fallback"] is False
    assert question["query"] == "Hellsingu"
