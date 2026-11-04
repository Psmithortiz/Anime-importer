from collections.abc import Sequence
from typing import Protocol

from anime_importer.domain.models import AnimeCandidate, NormalizedTitle


class SearchError(Exception):
    """El buscador no pudo completar la búsqueda."""


class NormalizationError(Exception):
    """El normalizador no pudo procesar la lista."""


class AnimeSearcher(Protocol):
    def search(self, query: str) -> list[AnimeCandidate]: ...


class TitleNormalizer(Protocol):
    def normalize(self, titles: Sequence[str]) -> list[NormalizedTitle]: ...
