from dataclasses import dataclass
from enum import StrEnum


class MediaType(StrEnum):
    TV = "tv"
    MOVIE = "movie"
    OVA = "ova"
    ONA = "ona"
    SPECIAL = "special"
    MUSIC = "music"
    OTHER = "other"


class AiringStatus(StrEnum):
    FINISHED = "finished"
    AIRING = "airing"
    NOT_YET_AIRED = "not_yet_aired"
    UNKNOWN = "unknown"


class ListStatus(StrEnum):
    COMPLETED = "completed"
    WATCHING = "watching"
    PLAN_TO_WATCH = "plan_to_watch"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"


@dataclass(frozen=True, slots=True)
class AnimeCandidate:
    """Search result."""

    mal_id: int
    title: str
    image_url: str | None = None
    alternative_titles: tuple[str, ...] = ()
    media_type: MediaType | None = None
    year: int | None = None
    episodes: int | None = None
    airing_status: AiringStatus = AiringStatus.UNKNOWN


_SUGGESTED_STATUS = {
    AiringStatus.FINISHED: ListStatus.COMPLETED,
    AiringStatus.AIRING: ListStatus.WATCHING,
    AiringStatus.NOT_YET_AIRED: ListStatus.PLAN_TO_WATCH,
    AiringStatus.UNKNOWN: ListStatus.COMPLETED,
}


def suggest_list_status(airing: AiringStatus) -> ListStatus:
    return _SUGGESTED_STATUS[airing]


@dataclass(frozen=True, slots=True)
class NormalizedTitle:
    """Gemini output for one title of the list."""

    index: int
    romaji: str
    is_anime: bool = True
    ambiguous: bool = False
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportedAnime:
    """Resolved anime, ready for the XML."""

    mal_id: int
    title: str
    list_status: ListStatus = ListStatus.COMPLETED


@dataclass(frozen=True, slots=True)
class RejectedTitle:
    """Title that was not imported."""

    original_title: str
    reason: str


class RelationType(StrEnum):
    SEQUEL = "sequel"
    PREQUEL = "prequel"
    SIDE_STORY = "side_story"
    PARENT_STORY = "parent_story"
    SUMMARY = "summary"
    FULL_STORY = "full_story"
    ALTERNATIVE_VERSION = "alternative_version"
    ALTERNATIVE_SETTING = "alternative_setting"
    SPIN_OFF = "spin_off"
    CHARACTER = "character"
    OTHER = "other"


# Relations whose target is also expanded when exploring a franchise.
FOLLOWED_RELATIONS = frozenset(
    {
        RelationType.SEQUEL,
        RelationType.PREQUEL,
        RelationType.SIDE_STORY,
        RelationType.PARENT_STORY,
        RelationType.SUMMARY,
        RelationType.FULL_STORY,
    }
)
# Relations whose target is offered to the user but not expanded.
SHOWN_RELATIONS = frozenset(
    {
        RelationType.ALTERNATIVE_VERSION,
        RelationType.ALTERNATIVE_SETTING,
        RelationType.SPIN_OFF,
    }
)


@dataclass(frozen=True, slots=True)
class Relation:
    """Link from one anime to another."""

    mal_id: int
    relation_type: RelationType


@dataclass(frozen=True, slots=True)
class AnimeDetails:
    """An anime with its relations to other anime."""

    candidate: AnimeCandidate
    relations: tuple[Relation, ...]


@dataclass(frozen=True, slots=True)
class FranchiseEntry:
    """Anime found while exploring a franchise, and how it was reached."""

    candidate: AnimeCandidate
    relation: RelationType


@dataclass(frozen=True, slots=True)
class Franchise:
    entries: tuple[FranchiseEntry, ...] = ()
    truncated: bool = False
