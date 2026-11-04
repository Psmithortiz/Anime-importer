from collections.abc import Callable, Sequence
from typing import Protocol

from anime_importer.domain.models import AnimeCandidate, NormalizedTitle


class SearchError(Exception):
    """The searcher could not complete the search."""


class NormalizationError(Exception):
    """The normalizer could not process the list."""


class AnimeSearcher(Protocol):
    def search(self, query: str) -> list[AnimeCandidate]: ...


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
