"""Types of an import session: questions, resolutions, user decisions and stored snapshots."""

from dataclasses import dataclass, field
from datetime import datetime

from anime_importer.domain.models import (
    AnimeCandidate,
    Franchise,
    ImportedAnime,
    ListStatus,
    NormalizedTitle,
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


# ------------------------------------------------------------------ decisions
# They identify what the user chose by identity (query text, MAL id), never by option number.


@dataclass(frozen=True, slots=True)
class PickQuery:
    """Answer to a NormalizationChoice: the chosen query."""

    query: str


@dataclass(frozen=True, slots=True)
class PickCandidates:
    """Answer to a CandidateChoice: (mal_id, status) of every chosen anime."""

    selections: tuple[tuple[int, ListStatus], ...]


@dataclass(frozen=True, slots=True)
class Discard:
    """The user discarded the title."""


Decision = PickQuery | PickCandidates | Discard


# ------------------------------------------------------------------ stored session


@dataclass(frozen=True)
class StoredSession:
    """Snapshot of a persisted session.

    Not `slots=True`, and `answers` is a dict: the instance is not hashable. `answers` must not
    be mutated by callers.
    """

    id: str
    titles: tuple[str, ...]
    normalized: tuple[NormalizedTitle, ...] | None
    resolutions: tuple[Resolution, ...]  # in position order, no gaps
    answers: dict[tuple[int, str], Resolution]  # (position, query) -> resolution
    decisions: tuple[tuple[int, Decision], ...]  # (position, decision) in order


@dataclass(frozen=True, slots=True)
class SessionSummary:
    id: str
    created_at: datetime
    updated_at: datetime
    title_count: int
    preview: tuple[str, ...]  # first 3 titles
    decision_count: int
