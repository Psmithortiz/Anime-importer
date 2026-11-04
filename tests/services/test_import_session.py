import pytest

from anime_importer.domain.models import (
    AiringStatus,
    AnimeCandidate,
    ImportedAnime,
    ListStatus,
    NormalizedTitle,
)
from anime_importer.ports import SearchError
from anime_importer.services.import_session import (
    CandidateChoice,
    Finished,
    ImportSession,
    NormalizationChoice,
)


class FakeNormalizer:
    def __init__(self, normalized: list[NormalizedTitle]) -> None:
        self._normalized = normalized

    def normalize(self, titles, on_progress=None):
        return self._normalized


class FakeSearcher:
    def __init__(self, results: dict[str, list[AnimeCandidate] | Exception]) -> None:
        self._results = results
        self.queries: list[str] = []

    def search(self, query):
        self.queries.append(query)
        result = self._results.get(query, [])
        if isinstance(result, Exception):
            raise result
        return result


class ProgressNormalizer:
    def normalize(self, titles, on_progress=None):
        if on_progress is not None:
            on_progress(1, len(titles))
            on_progress(len(titles), len(titles))
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


def test_exposes_normalization_progress_after_start():
    session = ImportSession(["a", "b"], ProgressNormalizer(), FakeSearcher({}))
    assert session.normalization_progress is None

    session.start()

    assert session.normalization_progress == (2, 2)


def _session(titles, normalized, results):
    searcher = FakeSearcher(results)
    return ImportSession(titles, FakeNormalizer(normalized), searcher), searcher


def _hellsing_tie():
    return [AnimeCandidate(10, "Hellsing"), AnimeCandidate(20, "Hellsing")]


def test_auto_match_finishes_with_one_imported():
    session, _ = _session(
        ["naruto"],
        [NormalizedTitle(1, "Naruto")],
        {"Naruto": [AnimeCandidate(20, "Naruto")]},
    )

    step = session.start()

    assert isinstance(step, Finished)
    assert step.imported == (ImportedAnime(20, "Naruto"),)
    assert step.rejected == ()


def test_no_results_is_rejected():
    session, _ = _session(["x"], [NormalizedTitle(1, "Foo")], {})

    step = session.start()

    assert isinstance(step, Finished)
    assert step.imported == ()
    assert [r.reason for r in step.rejected] == ["No results (query: Foo)"]
    assert step.rejected[0].original_title == "x"


def test_search_error_is_rejected():
    session, _ = _session(["x"], [NormalizedTitle(1, "Foo")], {"Foo": SearchError("boom")})

    step = session.start()

    assert isinstance(step, Finished)
    assert [r.reason for r in step.rejected] == ["Search error: boom"]


def test_not_anime_is_rejected():
    session, _ = _session(["x"], [NormalizedTitle(1, "Foo", is_anime=False)], {})

    step = session.start()

    assert isinstance(step, Finished)
    assert [r.reason for r in step.rejected] == ["Not an anime (according to the normalizer)"]


def test_missing_normalization_is_rejected():
    session, _ = _session(["x"], [], {})

    step = session.start()

    assert isinstance(step, Finished)
    assert [r.reason for r in step.rejected] == ["No normalization data"]


def test_tie_asks_user_and_choose_imports_selected_candidate():
    session, _ = _session(
        ["hellsing"], [NormalizedTitle(1, "Hellsing")], {"Hellsing": _hellsing_tie()}
    )

    step = session.start()

    assert isinstance(step, CandidateChoice)
    assert step.original_title == "hellsing"
    assert step.query == "Hellsing"

    finished = session.choose(2)

    assert isinstance(finished, Finished)
    assert finished.imported == (ImportedAnime(20, "Hellsing"),)


def test_ambiguous_normalization_searches_chosen_option_and_continues():
    session, searcher = _session(
        ["naruto", "bleach"],
        [
            NormalizedTitle(1, "Naruto", ambiguous=True, options=("Naruto", "Naruto Shippuden")),
            NormalizedTitle(2, "Bleach"),
        ],
        {
            "Naruto Shippuden": [AnimeCandidate(1735, "Naruto Shippuden")],
            "Bleach": [AnimeCandidate(269, "Bleach")],
        },
    )

    step = session.start()
    assert isinstance(step, NormalizationChoice)
    assert step.options == ("Naruto", "Naruto Shippuden")

    finished = session.choose(2)

    assert isinstance(finished, Finished)
    assert finished.imported == (
        ImportedAnime(1735, "Naruto Shippuden"),
        ImportedAnime(269, "Bleach"),
    )
    assert searcher.queries == ["Naruto Shippuden", "Bleach"]


def test_ambiguous_choice_can_lead_to_candidate_choice():
    session, _ = _session(
        ["hellsing"],
        [NormalizedTitle(1, "Hellsing", ambiguous=True, options=("Hellsing",))],
        {"Hellsing": _hellsing_tie()},
    )
    assert isinstance(session.start(), NormalizationChoice)

    step = session.choose(1)

    assert isinstance(step, CandidateChoice)
    assert session.current is step


def test_discard_normalization_choice():
    session, _ = _session(
        ["naruto"],
        [NormalizedTitle(1, "Naruto", ambiguous=True, options=("A", "B"))],
        {},
    )
    session.start()

    step = session.discard()

    assert isinstance(step, Finished)
    assert [r.reason for r in step.rejected] == ["Discarded in normalization menu"]


def test_discard_candidate_choice():
    session, _ = _session(
        ["hellsing"], [NormalizedTitle(1, "Hellsing")], {"Hellsing": _hellsing_tie()}
    )
    session.start()

    step = session.discard()

    assert isinstance(step, Finished)
    assert [r.reason for r in step.rejected] == ["Discarded in search menu (query: Hellsing)"]


def test_finished_rejected_sorted_by_reason():
    session, _ = _session(
        ["a", "b", "c"],
        [
            NormalizedTitle(1, "Foo"),
            NormalizedTitle(2, "Bar", is_anime=False),
            NormalizedTitle(3, "Baz"),
        ],
        {},
    )

    step = session.start()

    assert isinstance(step, Finished)
    reasons = [r.reason for r in step.rejected]
    assert reasons == sorted(reasons)
    assert len(reasons) == 3


@pytest.mark.parametrize("number", [0, 3])
def test_choose_out_of_range_raises_and_keeps_question(number):
    session, _ = _session(
        ["hellsing"], [NormalizedTitle(1, "Hellsing")], {"Hellsing": _hellsing_tie()}
    )
    step = session.start()

    with pytest.raises(ValueError):
        session.choose(number)

    assert session.current is step


def test_current_before_start_raises():
    session, _ = _session(["x"], [], {})

    with pytest.raises(RuntimeError):
        _ = session.current


def test_choose_and_discard_after_finished_raise():
    session, _ = _session(["x"], [NormalizedTitle(1, "Foo", is_anime=False)], {})
    assert isinstance(session.start(), Finished)

    with pytest.raises(RuntimeError):
        session.choose(1)
    with pytest.raises(RuntimeError):
        session.discard()


def test_start_twice_raises():
    session, _ = _session(["x"], [NormalizedTitle(1, "Foo", is_anime=False)], {})
    session.start()

    with pytest.raises(RuntimeError):
        session.start()


def test_empty_title_list_raises():
    with pytest.raises(ValueError):
        ImportSession([], FakeNormalizer([]), FakeSearcher({}))


def test_progress_advances_with_resolved_titles():
    session, _ = _session(
        ["a", "b", "c"],
        [NormalizedTitle(1, "A"), NormalizedTitle(2, "Hellsing"), NormalizedTitle(3, "C")],
        {
            "A": [AnimeCandidate(1, "A")],
            "Hellsing": _hellsing_tie(),
            "C": [AnimeCandidate(3, "C")],
        },
    )
    assert session.progress == (0, 3)

    assert isinstance(session.start(), CandidateChoice)
    assert session.progress == (1, 3)

    assert isinstance(session.choose(1), Finished)
    assert session.progress == (3, 3)


def _tie_session():
    return _session(["hellsing"], [NormalizedTitle(1, "Hellsing")], {"Hellsing": _hellsing_tie()})


def test_choose_many_imports_each_option_with_its_status():
    session, _ = _tie_session()
    session.start()

    step = session.choose_many([(1, ListStatus.DROPPED), (2, ListStatus.WATCHING)])

    assert isinstance(step, Finished)
    assert step.imported == (
        ImportedAnime(10, "Hellsing", ListStatus.DROPPED),
        ImportedAnime(20, "Hellsing", ListStatus.WATCHING),
    )


@pytest.mark.parametrize(
    "selections",
    [
        [],
        [(3, ListStatus.COMPLETED)],
        [(0, ListStatus.COMPLETED)],
        [(1, ListStatus.COMPLETED), (1, ListStatus.DROPPED)],
    ],
)
def test_choose_many_invalid_raises_and_keeps_question(selections):
    session, _ = _tie_session()
    step = session.start()

    with pytest.raises(ValueError):
        session.choose_many(selections)

    assert session.current is step
    assert session.progress == (0, 1)


def test_choose_many_on_normalization_choice_raises():
    session, _ = _session(
        ["naruto"],
        [NormalizedTitle(1, "Naruto", ambiguous=True, options=("A", "B"))],
        {},
    )
    step = session.start()

    with pytest.raises(ValueError):
        session.choose_many([(1, ListStatus.COMPLETED)])

    assert session.current is step


def test_auto_match_uses_suggested_status_from_airing():
    airing = AnimeCandidate(5, "Frieren", airing_status=AiringStatus.AIRING)
    session, _ = _session(["f"], [NormalizedTitle(1, "Frieren")], {"Frieren": [airing]})

    step = session.start()

    assert isinstance(step, Finished)
    assert step.imported == (ImportedAnime(5, "Frieren", ListStatus.WATCHING),)


def test_choose_uses_suggested_status_of_candidate():
    options = [
        AnimeCandidate(10, "Hellsing", airing_status=AiringStatus.NOT_YET_AIRED),
        AnimeCandidate(20, "Hellsing"),
    ]
    session, _ = _session(["h"], [NormalizedTitle(1, "Hellsing")], {"Hellsing": options})
    session.start()

    step = session.choose(1)

    assert step.imported == (ImportedAnime(10, "Hellsing", ListStatus.PLAN_TO_WATCH),)


def test_duplicate_mal_id_last_import_wins():
    naruto = [AnimeCandidate(20, "Naruto", airing_status=AiringStatus.AIRING)]
    session, _ = _session(
        ["a", "b"],
        [NormalizedTitle(1, "Naruto"), NormalizedTitle(2, "Hellsing")],
        {"Naruto": naruto, "Hellsing": _hellsing_tie()},
    )
    session.start()

    step = session.choose_many([(2, ListStatus.DROPPED)])

    assert isinstance(step, Finished)
    assert step.imported == (ImportedAnime(20, "Hellsing", ListStatus.DROPPED),)
