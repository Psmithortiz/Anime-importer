"""Shared helper to build an ImportSession on an in-memory repository."""

from typing import Any

from anime_importer.adapters.memory_repository import InMemorySessionRepository
from anime_importer.services.import_session import ImportSession


def make_session(
    titles, normalizer, searcher, *, repository=None, session_id: str = "test", **deps: Any
) -> ImportSession:
    return ImportSession.create(
        session_id,
        titles,
        repository=repository if repository is not None else InMemorySessionRepository(),
        normalizer=normalizer,
        searcher=searcher,
        **deps,
    )


def make_services(
    normalizer, searcher, *, repository=None, franchise_finder=None, resolution_buffer: int = 20
):
    from anime_importer.bootstrap import SessionServices

    return SessionServices(
        repository=repository if repository is not None else InMemorySessionRepository(),
        normalizer=normalizer,
        searcher=searcher,
        franchise_finder=franchise_finder,
        resolution_buffer=resolution_buffer,
        run_in_background=lambda fn: fn(),
    )


def make_registry(normalizer, searcher, **kwargs):
    """A registry whose background work runs synchronously, for tests."""
    from anime_importer.api.registry import SessionRegistry

    return SessionRegistry(
        make_services(normalizer, searcher, **kwargs), run_in_background=lambda fn: fn()
    )
