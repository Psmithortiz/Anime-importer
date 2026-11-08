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
