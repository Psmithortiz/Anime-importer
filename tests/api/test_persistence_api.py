import itertools
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from session_helpers import make_registry, make_services

from anime_importer.adapters.memory_repository import InMemorySessionRepository
from anime_importer.adapters.sqlite_repository import SqliteSessionRepository
from anime_importer.api.app import create_app
from anime_importer.api.registry import SessionNotFoundError, SessionRegistry
from anime_importer.domain.models import AnimeCandidate, NormalizedTitle
from anime_importer.ports import PersistenceError


class PlainNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


class TieSearcher:
    """Every query is a tie between two candidates, so every title asks the user."""

    def search(self, query):
        base = sum(ord(c) for c in query) * 10
        return [AnimeCandidate(base, query), AnimeCandidate(base + 1, query)]


class ForbiddenNormalizer:
    def normalize(self, titles, on_progress=None):
        raise AssertionError("the normalizer must not be called")


class ForbiddenSearcher:
    def search(self, query):
        raise AssertionError("the searcher must not be called")


def sync(fn):
    fn()


def _create(client: TestClient, text: str) -> str:
    response = client.post("/api/sessions", json={"text": text})
    assert response.status_code == 202
    return response.json()["id"]


def _get(client: TestClient, session_id: str) -> dict:
    response = client.get(f"/api/sessions/{session_id}")
    assert response.status_code == 200
    return response.json()


def _post(client: TestClient, session_id: str, action: str, **body):
    return client.post(f"/api/sessions/{session_id}/{action}", json=body or None)


# ------------------------------------------------------------------ restart


def test_session_survives_an_app_restart(tmp_path):
    database = tmp_path / "sessions.db"
    first = TestClient(
        create_app(
            make_registry(
                PlainNormalizer(), TieSearcher(), repository=SqliteSessionRepository(database)
            )
        )
    )
    session_id = _create(first, "alpha\nbeta\ngamma")
    assert _post(first, session_id, "choose", option=1).status_code == 200
    assert _post(first, session_id, "choose", option=2).status_code == 200
    before = _get(first, session_id)
    assert before["status"] == "question"
    assert before["progress"]["done"] == 2

    # A brand new app over the same file; every resolution is stored, so nothing may be looked up.
    second = TestClient(
        create_app(
            make_registry(
                ForbiddenNormalizer(),
                ForbiddenSearcher(),
                repository=SqliteSessionRepository(database),
            )
        )
    )
    after = _get(second, session_id)

    assert after == before
    assert after["can_undo"] is True


def test_unknown_session_is_404():
    client = TestClient(create_app(make_registry(PlainNormalizer(), TieSearcher())))

    assert client.get("/api/sessions/deadbeef").status_code == 404
    assert client.post("/api/sessions/deadbeef/undo").status_code == 404
    assert client.post("/api/sessions/deadbeef/retry").status_code == 404


class CountingServices:
    """Wraps real services and counts restore_session calls."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.restores = 0

    def new_session(self, session_id, titles):
        return self._inner.new_session(session_id, titles)

    def list_recent(self, limit):
        return self._inner.list_recent(limit)

    def restore_session(self, session_id):
        self.restores += 1
        return self._inner.restore_session(session_id)


def test_concurrent_gets_load_a_stored_session_once():
    repository = InMemorySessionRepository()
    creator = SessionRegistry(
        make_services(PlainNormalizer(), TieSearcher(), repository=repository),
        run_in_background=sync,
    )
    session_id = creator.create(["alpha"]).id
    counting = CountingServices(
        make_services(PlainNormalizer(), TieSearcher(), repository=repository)
    )
    registry = SessionRegistry(counting, run_in_background=sync)
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(registry.get(session_id))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert counting.restores == 1
    assert results[0] is results[1]


def test_get_of_an_unknown_id_raises_not_found():
    registry = SessionRegistry(
        make_services(PlainNormalizer(), TieSearcher()), run_in_background=sync
    )

    with pytest.raises(SessionNotFoundError):
        registry.get("missing")


# ------------------------------------------------------------------ undo


def test_undo_returns_to_the_previous_question():
    client = TestClient(create_app(make_registry(PlainNormalizer(), TieSearcher())))
    session_id = _create(client, "alpha\nbeta")
    first = _get(client, session_id)
    assert first["can_undo"] is False
    _post(client, session_id, "choose", option=1)
    assert _get(client, session_id)["question"]["original_title"] == "beta"
    assert _get(client, session_id)["can_undo"] is True

    response = _post(client, session_id, "undo")

    assert response.status_code == 200
    assert response.json() == first


def test_undo_without_decisions_is_409():
    client = TestClient(create_app(make_registry(PlainNormalizer(), TieSearcher())))
    session_id = _create(client, "alpha")

    response = _post(client, session_id, "undo")

    assert response.status_code == 409
    assert "Nothing to undo" in response.json()["detail"]


def test_undo_from_finished_goes_back_to_a_question():
    client = TestClient(create_app(make_registry(PlainNormalizer(), TieSearcher())))
    session_id = _create(client, "alpha")
    question = _get(client, session_id)["question"]
    _post(client, session_id, "choose", option=1)
    assert _get(client, session_id)["status"] == "finished"

    response = _post(client, session_id, "undo")

    assert response.status_code == 200
    assert response.json()["status"] == "question"
    assert response.json()["question"] == question


# ------------------------------------------------------------------ retry


class FlakySearcher:
    def __init__(self) -> None:
        self.healthy = False

    def search(self, query):
        if query == "b":
            if not self.healthy:
                raise RuntimeError("boom")
            return [AnimeCandidate(30, "b")]
        return TieSearcher().search(query)


def test_retry_rebuilds_a_failed_session_and_applies_the_logged_decision():
    searcher = FlakySearcher()
    client = TestClient(create_app(make_registry(PlainNormalizer(), searcher)))
    session_id = _create(client, "alpha\nb")
    candidates = _get(client, session_id)["question"]["options"]
    # Advancing past "alpha" needs the lookup of "b", which the worker could not do.
    assert _post(client, session_id, "choose", option=1).status_code == 200
    assert _get(client, session_id)["status"] == "failed"

    searcher.healthy = True
    response = _post(client, session_id, "retry")

    assert response.status_code == 202
    view = _get(client, session_id)
    assert view["status"] == "finished"
    assert view["summary"]["imported"] == 2  # "alpha" (the logged decision) and "b"
    xml = client.get(f"/api/sessions/{session_id}/export.xml").text
    assert f"<series_animedb_id>{candidates[0]['mal_id']}</series_animedb_id>" in xml
    assert "<series_animedb_id>30</series_animedb_id>" in xml


def test_retry_is_only_valid_for_failed_sessions():
    client = TestClient(create_app(make_registry(PlainNormalizer(), TieSearcher())))
    session_id = _create(client, "alpha")
    assert _get(client, session_id)["status"] == "question"

    assert _post(client, session_id, "retry").status_code == 409


# ------------------------------------------------------------------ listing


def _ticking_clock():
    counter = itertools.count()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return lambda: start + timedelta(seconds=next(counter))


def test_listing_orders_by_updated_at_and_respects_limit():
    repository = InMemorySessionRepository(clock=_ticking_clock())
    client = TestClient(
        create_app(make_registry(PlainNormalizer(), TieSearcher(), repository=repository))
    )
    first = _create(client, "a1\na2\na3\na4")
    second = _create(client, "b1")
    third = _create(client, "c1")
    _post(client, first, "choose", option=1)  # the first session is now the most recently updated

    listing = client.get("/api/sessions").json()

    assert [item["id"] for item in listing] == [first, third, second]
    assert listing[0]["title_count"] == 4
    assert listing[0]["preview"] == ["a1", "a2", "a3"]
    assert listing[0]["decision_count"] == 1
    assert {"created_at", "updated_at"} <= set(listing[0])
    assert [item["id"] for item in client.get("/api/sessions?limit=2").json()] == [first, third]


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_listing_rejects_limits_out_of_range(limit):
    client = TestClient(create_app(make_registry(PlainNormalizer(), TieSearcher())))

    assert client.get(f"/api/sessions?limit={limit}").status_code == 422


# ------------------------------------------------------------------ persistence errors


class FailingDecisions(InMemorySessionRepository):
    failing = False

    def add_decision(self, session_id, position, decision):
        if self.failing:
            raise PersistenceError("disk full")
        super().add_decision(session_id, position, decision)


def test_persistence_error_is_503_and_the_session_stays_the_same():
    repository = FailingDecisions()
    client = TestClient(
        create_app(make_registry(PlainNormalizer(), TieSearcher(), repository=repository))
    )
    session_id = _create(client, "alpha\nbeta")
    before = _get(client, session_id)
    repository.failing = True

    response = _post(client, session_id, "choose", option=1)

    assert response.status_code == 503
    assert response.json() == {"detail": "Could not save the session; try again"}
    assert _get(client, session_id) == before

    repository.failing = False
    assert _post(client, session_id, "choose", option=1).status_code == 200
