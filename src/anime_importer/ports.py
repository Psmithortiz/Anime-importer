from collections.abc import Callable, Sequence
from typing import Protocol

from anime_importer.domain.models import AnimeCandidate, AnimeDetails, NormalizedTitle
from anime_importer.domain.session import Decision, Resolution, SessionSummary, StoredSession


class SearchError(Exception):
    """The searcher could not complete the search."""


class NormalizationError(Exception):
    """The normalizer could not process the list."""


class DetailsError(Exception):
    """The details provider could not fetch an anime."""


class PersistenceError(Exception):
    """The session repository could not complete the operation."""


class AnimeSearcher(Protocol):
    def search(self, query: str) -> list[AnimeCandidate]: ...


class AnimeDetailsProvider(Protocol):
    def get_details(self, mal_id: int) -> AnimeDetails: ...


ProgressCallback = Callable[[int, int], None]  # (done_titles, total_titles)


class TitleNormalizer(Protocol):
    def normalize(
        self, titles: Sequence[str], on_progress: ProgressCallback | None = None
    ) -> list[NormalizedTitle]: ...


ChunkCallback = Callable[[Sequence[str], Sequence[NormalizedTitle]], None]


class ChunkedNormalizer(Protocol):
    def normalize(
        self,
        titles: Sequence[str],
        on_chunk: ChunkCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> list[NormalizedTitle]: ...


class SessionRepository(Protocol):
    """Persistence of import sessions.

    Contract:
    - `add_resolution` requires `position` to be exactly the next one (= the current number of
      resolutions); otherwise PersistenceError.
    - `save_answer` with the same (position, query) replaces the previous answer.
    - Every operation on a nonexistent session_id raises PersistenceError (except `load`, which
      returns None).
    - Every write updates the session's `updated_at`, taken from an injectable clock.
    - `list_recent` orders by `updated_at`, most recent first.
    """

    def create(self, session_id: str, titles: Sequence[str]) -> None: ...

    def save_normalization(
        self, session_id: str, normalized: Sequence[NormalizedTitle]
    ) -> None: ...

    def add_resolution(self, session_id: str, position: int, resolution: Resolution) -> None: ...

    def save_answer(
        self, session_id: str, position: int, query: str, resolution: Resolution
    ) -> None: ...

    def add_decision(self, session_id: str, position: int, decision: Decision) -> None: ...

    def remove_last_decision(self, session_id: str) -> bool:
        """Remove the most recent decision; False if there were none."""
        ...

    def load(self, session_id: str) -> StoredSession | None: ...

    def list_recent(self, limit: int) -> list[SessionSummary]: ...
