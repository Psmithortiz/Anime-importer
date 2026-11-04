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
    texts: list[str] = []
    owners: list[int] = []
    for position, candidate in enumerate(candidates):
        for text in (candidate.title, *candidate.alternative_titles):
            if text:
                texts.append(text)
                owners.append(position)
    best: dict[int, float] = {}
    for _, score, text_index in process.extract(
        query, texts, processor=utils.default_process, limit=None
    ):
        best.setdefault(owners[text_index], score)
    ranked = list(best)
    above = [position for position in ranked if best[position] >= AUTO_ACCEPT_SCORE]
    if len(above) == 1:
        return MatchResult(accepted=candidates[above[0]])
    return MatchResult(
        accepted=None,
        options=tuple(candidates[position] for position in ranked[:MAX_OPTIONS]),
    )
