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


@dataclass(frozen=True, slots=True)
class AnimeCandidate:
    """Resultado de búsqueda (reemplaza el dict {"id", "title", "imagen"})."""

    mal_id: int
    title: str
    image_url: str | None = None
    alternative_titles: tuple[str, ...] = ()
    media_type: MediaType | None = None
    year: int | None = None
    episodes: int | None = None
    airing_status: AiringStatus = AiringStatus.UNKNOWN


@dataclass(frozen=True, slots=True)
class NormalizedTitle:
    """Salida de Gemini para un título de la lista."""

    index: int
    romaji: str
    is_anime: bool = True
    ambiguous: bool = False
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportedAnime:
    """Anime resuelto, listo para el XML (reemplaza la tupla (id, title))."""

    mal_id: int
    title: str


@dataclass(frozen=True, slots=True)
class RejectedTitle:
    """Título que no se importó (reemplaza la tupla (title, reason))."""

    original_title: str
    reason: str
