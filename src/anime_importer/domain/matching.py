from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import process, utils

from anime_importer.domain.models import AnimeCandidate

AUTO_ACCEPT_SCORE = 95
MAX_OPTIONS = 5


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Si `accepted` no es None, el match es automático. Si no, `options` va al menú."""

    accepted: AnimeCandidate | None
    options: tuple[AnimeCandidate, ...] = ()


def match_candidates(query: str, candidates: Sequence[AnimeCandidate]) -> MatchResult:
    if not candidates:
        return MatchResult(accepted=None)
    titles = [c.title for c in candidates]
    scored = process.extract(query, titles, processor=utils.default_process, limit=None)
    above = [i for _, score, i in scored if score >= AUTO_ACCEPT_SCORE]
    if len(above) == 1:
        return MatchResult(accepted=candidates[above[0]])
    return MatchResult(
        accepted=None,
        options=tuple(candidates[i] for _, _, i in scored[:MAX_OPTIONS]),
    )
