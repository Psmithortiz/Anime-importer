from collections.abc import Sequence
from typing import Protocol

from anime_importer.domain.models import AnimeCandidate, NormalizedTitle


class AnimeSearcher(Protocol):
    def search(self, query: str) -> list[AnimeCandidate]: ...


class TitleNormalizer(Protocol):
    def normalize(self, titles: Sequence[str]) -> list[NormalizedTitle]: ...
