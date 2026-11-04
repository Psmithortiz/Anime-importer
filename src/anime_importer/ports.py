from collections.abc import Callable, Sequence
from typing import Protocol

from anime_importer.domain.models import AnimeCandidate, AnimeDetails, NormalizedTitle


class SearchError(Exception):
    """The searcher could not complete the search."""


class NormalizationError(Exception):
    """The normalizer could not process the list."""


class DetailsError(Exception):
    """The details provider could not fetch an anime."""


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
