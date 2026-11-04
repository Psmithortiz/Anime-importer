from typing import Protocol

from anime_importer.domain.models import AnimeCandidate


class AnimeSearcher(Protocol):
    def search(self, query: str) -> list[AnimeCandidate]: ...
