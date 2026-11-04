from collections.abc import Callable, Sequence
from typing import Protocol

from anime_importer.domain.models import AnimeCandidate, NormalizedTitle


class SearchError(Exception):
    """The searcher could not complete the search."""


class NormalizationError(Exception):
    """The normalizer could not process the list."""


class AnimeSearcher(Protocol):
    def search(self, query: str) -> list[AnimeCandidate]: ...


class TitleNormalizer(Protocol):
    def normalize(self, titles: Sequence[str]) -> list[NormalizedTitle]: ...


ChunkCallback = Callable[[Sequence[str], Sequence[NormalizedTitle]], None]


class ChunkedNormalizer(Protocol):
    def normalize(
        self, titles: Sequence[str], on_chunk: ChunkCallback | None = None
    ) -> list[NormalizedTitle]: ...
