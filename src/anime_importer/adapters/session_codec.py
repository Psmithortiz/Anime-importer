"""JSON-compatible serialization of session types (resolutions, decisions, normalized titles).

Pure functions: dataclass -> dict and back. Every polymorphic payload carries a "kind"
discriminator. The format is independent from details_cache.py and from demo.py on purpose:
changing one must not invalidate the others.
"""

from typing import Any

from anime_importer.domain.models import (
    AiringStatus,
    AnimeCandidate,
    Franchise,
    FranchiseEntry,
    ImportedAnime,
    ListStatus,
    MediaType,
    NormalizedTitle,
    RelationType,
)
from anime_importer.domain.session import (
    Ask,
    CandidateChoice,
    Decision,
    Discard,
    Imported,
    NormalizationChoice,
    PickCandidates,
    PickQuery,
    Rejected,
    Resolution,
)

# ---------------------------------------------------------------- normalized titles


def normalized_to_dict(title: NormalizedTitle) -> dict[str, Any]:
    """Unlike the demo format, the index IS stored."""
    return {
        "index": title.index,
        "romaji": title.romaji,
        "is_anime": title.is_anime,
        "ambiguous": title.ambiguous,
        "options": list(title.options),
    }


def normalized_from_dict(data: dict[str, Any]) -> NormalizedTitle:
    return NormalizedTitle(
        index=data["index"],
        romaji=data["romaji"],
        is_anime=data["is_anime"],
        ambiguous=data["ambiguous"],
        options=tuple(data["options"]),
    )


# ---------------------------------------------------------------- building blocks


def _candidate_to_dict(candidate: AnimeCandidate) -> dict[str, Any]:
    return {
        "mal_id": candidate.mal_id,
        "title": candidate.title,
        "image_url": candidate.image_url,
        "alternative_titles": list(candidate.alternative_titles),
        "media_type": candidate.media_type.value if candidate.media_type else None,
        "year": candidate.year,
        "episodes": candidate.episodes,
        "airing_status": candidate.airing_status.value,
    }


def _candidate_from_dict(data: dict[str, Any]) -> AnimeCandidate:
    media_type = data["media_type"]
    return AnimeCandidate(
        mal_id=data["mal_id"],
        title=data["title"],
        image_url=data["image_url"],
        alternative_titles=tuple(data["alternative_titles"]),
        media_type=MediaType(media_type) if media_type is not None else None,
        year=data["year"],
        episodes=data["episodes"],
        airing_status=AiringStatus(data["airing_status"]),
    )


def _franchise_to_dict(franchise: Franchise) -> dict[str, Any]:
    return {
        "entries": [
            {"candidate": _candidate_to_dict(e.candidate), "relation": e.relation.value}
            for e in franchise.entries
        ],
        "truncated": franchise.truncated,
    }


def _franchise_from_dict(data: dict[str, Any]) -> Franchise:
    return Franchise(
        entries=tuple(
            FranchiseEntry(
                candidate=_candidate_from_dict(e["candidate"]),
                relation=RelationType(e["relation"]),
            )
            for e in data["entries"]
        ),
        truncated=data["truncated"],
    )


def _question_to_dict(question: NormalizationChoice | CandidateChoice) -> dict[str, Any]:
    if isinstance(question, NormalizationChoice):
        return {
            "kind": "normalization_choice",
            "original_title": question.original_title,
            "options": list(question.options),
            "original_option": question.original_option,
        }
    return {
        "kind": "candidate_choice",
        "original_title": question.original_title,
        "query": question.query,
        "options": [_candidate_to_dict(c) for c in question.options],
        "franchise": _franchise_to_dict(question.franchise),
        "preselected": sorted(question.preselected),
        "used_fallback": question.used_fallback,
    }


def _question_from_dict(data: dict[str, Any]) -> NormalizationChoice | CandidateChoice:
    kind = data["kind"]
    if kind == "normalization_choice":
        return NormalizationChoice(
            original_title=data["original_title"],
            options=tuple(data["options"]),
            original_option=data["original_option"],
        )
    if kind == "candidate_choice":
        return CandidateChoice(
            original_title=data["original_title"],
            query=data["query"],
            options=tuple(_candidate_from_dict(c) for c in data["options"]),
            franchise=_franchise_from_dict(data["franchise"]),
            preselected=frozenset(data["preselected"]),
            used_fallback=data["used_fallback"],
        )
    raise ValueError(f"Unknown question kind: {kind!r}")


# ---------------------------------------------------------------- resolutions


def resolution_to_dict(resolution: Resolution) -> dict[str, Any]:
    match resolution:
        case Imported(entry):
            return {
                "kind": "imported",
                "mal_id": entry.mal_id,
                "title": entry.title,
                "list_status": entry.list_status.value,
            }
        case Rejected(reason):
            return {"kind": "rejected", "reason": reason}
        case Ask(question):
            return {"kind": "ask", "question": _question_to_dict(question)}
    raise TypeError(f"Unsupported resolution: {resolution!r}")


def resolution_from_dict(data: dict[str, Any]) -> Resolution:
    kind = data["kind"]
    if kind == "imported":
        return Imported(
            ImportedAnime(
                mal_id=data["mal_id"],
                title=data["title"],
                list_status=ListStatus(data["list_status"]),
            )
        )
    if kind == "rejected":
        return Rejected(data["reason"])
    if kind == "ask":
        return Ask(_question_from_dict(data["question"]))
    raise ValueError(f"Unknown resolution kind: {kind!r}")


# ---------------------------------------------------------------- decisions


def decision_to_dict(decision: Decision) -> dict[str, Any]:
    match decision:
        case PickQuery(query):
            return {"kind": "pick_query", "query": query}
        case PickCandidates(selections):
            return {
                "kind": "pick_candidates",
                "selections": [[mal_id, status.value] for mal_id, status in selections],
            }
        case Discard():
            return {"kind": "discard"}
    raise TypeError(f"Unsupported decision: {decision!r}")


def decision_from_dict(data: dict[str, Any]) -> Decision:
    kind = data["kind"]
    if kind == "pick_query":
        return PickQuery(data["query"])
    if kind == "pick_candidates":
        return PickCandidates(
            tuple((mal_id, ListStatus(status)) for mal_id, status in data["selections"])
        )
    if kind == "discard":
        return Discard()
    raise ValueError(f"Unknown decision kind: {kind!r}")
