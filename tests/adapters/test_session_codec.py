import json

import pytest

from anime_importer.adapters.session_codec import (
    decision_from_dict,
    decision_to_dict,
    normalized_from_dict,
    normalized_to_dict,
    resolution_from_dict,
    resolution_to_dict,
)
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
    Discard,
    Imported,
    NormalizationChoice,
    PickCandidates,
    PickQuery,
    Rejected,
)


def _full_candidate(mal_id: int = 1) -> AnimeCandidate:
    return AnimeCandidate(
        mal_id=mal_id,
        title=f"Title {mal_id}",
        image_url="https://example.com/a.jpg",
        alternative_titles=("Alt A", "Alt B"),
        media_type=MediaType.TV,
        year=2004,
        episodes=26,
        airing_status=AiringStatus.FINISHED,
    )


def _bare_candidate(mal_id: int = 2) -> AnimeCandidate:
    return AnimeCandidate(mal_id=mal_id, title=f"Bare {mal_id}")


def _roundtrip_resolution(resolution):
    # Through real JSON text: proves the dict is JSON-compatible.
    return resolution_from_dict(json.loads(json.dumps(resolution_to_dict(resolution))))


def _roundtrip_decision(decision):
    return decision_from_dict(json.loads(json.dumps(decision_to_dict(decision))))


def test_normalized_title_roundtrip_keeps_index() -> None:
    title = NormalizedTitle(
        index=7, romaji="Naruto", is_anime=False, ambiguous=True, options=("A", "B")
    )

    assert normalized_from_dict(json.loads(json.dumps(normalized_to_dict(title)))) == title


def test_imported_roundtrip() -> None:
    resolution = Imported(ImportedAnime(mal_id=5, title="Bebop", list_status=ListStatus.DROPPED))

    assert _roundtrip_resolution(resolution) == resolution


def test_rejected_roundtrip() -> None:
    assert _roundtrip_resolution(Rejected("No results")) == Rejected("No results")


@pytest.mark.parametrize("original_option", [None, 3])
def test_ask_normalization_choice_roundtrip(original_option: int | None) -> None:
    resolution = Ask(
        NormalizationChoice(
            original_title="my line", options=("a", "b", "my line"), original_option=original_option
        )
    )

    assert _roundtrip_resolution(resolution) == resolution


def test_ask_candidate_choice_with_truncated_franchise_roundtrip() -> None:
    franchise = Franchise(
        entries=(
            FranchiseEntry(_full_candidate(10), RelationType.SEQUEL),
            FranchiseEntry(_bare_candidate(11), RelationType.SPIN_OFF),
        ),
        truncated=True,
    )
    resolution = Ask(
        CandidateChoice(
            original_title="line",
            query="query",
            options=(_full_candidate(1), _bare_candidate(2)),
            franchise=franchise,
            preselected=frozenset({1, 2}),
            used_fallback=True,
        )
    )

    assert _roundtrip_resolution(resolution) == resolution


def test_ask_candidate_choice_with_empty_preselected_and_default_franchise_roundtrip() -> None:
    resolution = Ask(
        CandidateChoice(original_title="line", query="query", options=(_bare_candidate(),))
    )

    restored = _roundtrip_resolution(resolution)

    assert restored == resolution
    assert restored.question.preselected == frozenset()


def test_preselected_is_stored_sorted() -> None:
    resolution = Ask(
        CandidateChoice(
            original_title="l",
            query="q",
            options=(_bare_candidate(),),
            preselected=frozenset({9, 3, 5}),
        )
    )

    assert resolution_to_dict(resolution)["question"]["preselected"] == [3, 5, 9]


@pytest.mark.parametrize(
    "decision",
    [
        PickQuery("Cowboy Bebop"),
        PickCandidates(((1, ListStatus.COMPLETED), (2, ListStatus.PLAN_TO_WATCH))),
        PickCandidates(()),
        Discard(),
    ],
)
def test_decision_roundtrip(decision) -> None:
    assert _roundtrip_decision(decision) == decision


def test_unknown_kinds_are_rejected() -> None:
    with pytest.raises(ValueError, match="resolution"):
        resolution_from_dict({"kind": "nope"})
    with pytest.raises(ValueError, match="decision"):
        decision_from_dict({"kind": "nope"})
