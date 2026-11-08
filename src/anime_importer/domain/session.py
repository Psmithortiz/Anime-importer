"""Types of an import session: questions and resolutions."""

from dataclasses import dataclass, field

from anime_importer.domain.models import (
    AnimeCandidate,
    Franchise,
    ImportedAnime,
    RejectedTitle,
)


@dataclass(frozen=True, slots=True)
class NormalizationChoice:
    """The normalizer is unsure: the user picks among possible titles."""

    original_title: str
    options: tuple[str, ...]
    original_option: int | None = None  # 1-based number of the option that is the user's line


@dataclass(frozen=True, slots=True)
class CandidateChoice:
    """The search gave no confident match: the user picks among candidates."""

    original_title: str
    query: str
    options: tuple[AnimeCandidate, ...]
    franchise: Franchise = field(default_factory=Franchise)
    preselected: frozenset[int] = frozenset()  # mal_ids marked in advance
    used_fallback: bool = False  # the query is the user's original line, not the normalized one


@dataclass(frozen=True, slots=True)
class Finished:
    imported: tuple[ImportedAnime, ...]
    rejected: tuple[RejectedTitle, ...]


Step = NormalizationChoice | CandidateChoice | Finished


@dataclass(frozen=True, slots=True)
class Imported:
    """The title resolved to an anime on its own."""

    entry: ImportedAnime


@dataclass(frozen=True, slots=True)
class Rejected:
    """The title cannot be imported."""

    reason: str


@dataclass(frozen=True, slots=True)
class Ask:
    """The title needs the user to decide."""

    question: NormalizationChoice | CandidateChoice


Resolution = Imported | Rejected | Ask
