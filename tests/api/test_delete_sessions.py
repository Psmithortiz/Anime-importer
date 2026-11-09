import threading

import pytest
from fastapi.testclient import TestClient
from session_helpers import make_registry

from anime_importer.adapters.memory_repository import InMemorySessionRepository
from anime_importer.api.app import create_app
from anime_importer.api.registry import (
    InvalidStateError,
    SessionNotFoundError,
    SessionRegistry,
)
from anime_importer.bootstrap import SessionServices
from anime_importer.domain.models import AnimeCandidate, NormalizedTitle

TIMEOUT = 2.0


def sync(fn):
    fn()


class PlainNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


class TieSearcher:
    def search(self, query):
        base = sum(ord(c) for c in query) * 10
        return [AnimeCandidate(base, query), AnimeCandidate(base + 1, query)]


class FailingSearcher:
    def search(self, query):
        raise RuntimeError("boom")


class GatedSearcher:
    """The first title is answered at once; the rest wait until the test releases them."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def search(self, query):
        if query != "alpha":
            assert self.release.wait(TIMEOUT), "test never released the searcher"
        return TieSearcher().search(query)


def _resolving_registry(searcher, repository=None):
    """A registry whose worker runs on a real thread, one resolution ahead of the user."""
    services = SessionServices(
        repository=repository if repository is not None else InMemorySessionRepository(),
        normalizer=PlainNormalizer(),
        searcher=searcher,
        franchise_finder=None,
        resolution_buffer=1,
    )
    return SessionRegistry(services, run_in_background=sync)


# ------------------------------------------------------------------ registry


def test_deleting_a_session_not_in_memory_removes_it_from_the_repository():
    repository = InMemorySessionRepository()
    creator = make_registry(PlainNormalizer(), TieSearcher(), repository=repository)
    session_id = creator.create(["alpha"]).id
    fresh = make_registry(PlainNormalizer(), TieSearcher(), repository=repository)

    fresh.delete(session_id)

    assert repository.load(session_id) is None


def test_deleting_an_unknown_session_raises_not_found():
    registry = make_registry(PlainNormalizer(), TieSearcher())

    with pytest.raises(SessionNotFoundError):
        registry.delete("nope")


def test_deleting_an_idle_session_removes_it_and_blocks_the_old_reference():
    repository = InMemorySessionRepository()
    registry = make_registry(PlainNormalizer(), TieSearcher(), repository=repository)
    managed = registry.create(["alpha", "beta"])
    managed.run_start()
    assert managed.status == "question"

    registry.delete(managed.id)

    assert repository.load(managed.id) is None
    with pytest.raises(SessionNotFoundError):
        registry.get(managed.id)
    with pytest.raises(SessionNotFoundError):
        managed.choose(1)
    with pytest.raises(SessionNotFoundError):
        managed.discard()
    with pytest.raises(SessionNotFoundError):
        managed.undo()


def test_a_session_that_is_still_resolving_cannot_be_deleted():
    searcher = GatedSearcher()
    repository = InMemorySessionRepository()
    registry = _resolving_registry(searcher, repository)
    managed = registry.create(["alpha", "beta"])
    managed.run_start()
    try:
        assert managed.session.is_resolving is True

        with pytest.raises(InvalidStateError):
            registry.delete(managed.id)

        assert repository.load(managed.id) is not None
    finally:
        searcher.release.set()


def test_a_busy_session_is_a_409_without_waiting():
    registry = make_registry(PlainNormalizer(), TieSearcher())
    managed = registry.create(["alpha"])
    managed.run_start()

    assert managed.lock.acquire(blocking=False)
    try:
        with pytest.raises(InvalidStateError):
            registry.delete(managed.id)
    finally:
        managed.lock.release()


def test_a_failed_session_can_be_deleted():
    repository = InMemorySessionRepository()
    registry = make_registry(PlainNormalizer(), FailingSearcher(), repository=repository)
    managed = registry.create(["alpha"])
    managed.run_start()
    assert managed.status == "failed"

    registry.delete(managed.id)

    assert repository.load(managed.id) is None


# ------------------------------------------------------------------ API


def _client(searcher=None, registry=None) -> TestClient:
    return TestClient(
        create_app(registry or make_registry(PlainNormalizer(), searcher or TieSearcher()))
    )


def test_delete_returns_204_and_the_session_is_gone():
    client = _client()
    session_id = client.post("/api/sessions", json={"text": "alpha\nbeta"}).json()["id"]

    response = client.delete(f"/api/sessions/{session_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert session_id not in [item["id"] for item in client.get("/api/sessions").json()]


def test_delete_unknown_session_is_404():
    assert _client().delete("/api/sessions/deadbeef").status_code == 404


def test_delete_while_resolving_is_409():
    searcher = GatedSearcher()
    client = TestClient(create_app(_resolving_registry(searcher)))
    try:
        session_id = client.post("/api/sessions", json={"text": "alpha\nbeta"}).json()["id"]

        response = client.delete(f"/api/sessions/{session_id}")

        assert response.status_code == 409
        assert client.get(f"/api/sessions/{session_id}").status_code == 200
    finally:
        searcher.release.set()


def test_an_action_on_a_deleted_session_object_is_404_not_500():
    registry = make_registry(PlainNormalizer(), TieSearcher())
    client = TestClient(create_app(registry))
    session_id = client.post("/api/sessions", json={"text": "alpha\nbeta"}).json()["id"]
    stale = registry.get(session_id)
    registry.delete(session_id)
    # A request that already held the old object (other tab) reaches it through the handler.
    from anime_importer.api.app import get_managed

    client.app.dependency_overrides[get_managed] = lambda: stale

    response = client.post(f"/api/sessions/{session_id}/choose", json={"option": 1})

    assert response.status_code == 404
