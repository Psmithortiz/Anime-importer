import pytest

from anime_importer.domain.models import (
    AnimeCandidate,
    Franchise,
    FranchiseEntry,
    ImportedAnime,
    ListStatus,
    NormalizedTitle,
    RelationType,
)
from anime_importer.services.import_session import (
    CandidateChoice,
    Finished,
    ImportSession,
)


class FakeNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


class FakeSearcher:
    def __init__(self, results):
        self._results = results

    def search(self, query):
        return self._results.get(query, [])


class FakeFinder:
    def __init__(self, franchise: Franchise) -> None:
        self._franchise = franchise
        self.calls: list[list[int]] = []

    def __call__(self, seed_ids):
        self.calls.append(list(seed_ids))
        return self._franchise


SEQUEL = AnimeCandidate(30, "Hellsing Ultimate")
FRANCHISE = Franchise(entries=(FranchiseEntry(SEQUEL, RelationType.SEQUEL),))
TIE = [AnimeCandidate(10, "Hellsing"), AnimeCandidate(20, "Hellsing")]


def _session(results, finder):
    return ImportSession(
        ["Hellsing"],
        FakeNormalizer(),
        FakeSearcher(results),
        franchise_finder=finder,
        run_in_background=lambda fn: fn(),
    )


def test_auto_match_with_empty_franchise_imports_directly():
    finder = FakeFinder(Franchise())
    session = _session({"Hellsing": [AnimeCandidate(10, "Hellsing")]}, finder)

    step = session.start()

    assert isinstance(step, Finished)
    assert step.imported == (ImportedAnime(10, "Hellsing", ListStatus.COMPLETED),)
    assert finder.calls == [[10]]


def test_auto_match_with_franchise_asks_with_accepted_preselected():
    session = _session({"Hellsing": [AnimeCandidate(10, "Hellsing")]}, FakeFinder(FRANCHISE))

    step = session.start()

    assert isinstance(step, CandidateChoice)
    assert step.options == (AnimeCandidate(10, "Hellsing"),)
    assert step.preselected == frozenset({10})
    assert step.franchise == FRANCHISE


def test_truncated_empty_franchise_still_asks():
    session = _session(
        {"Hellsing": [AnimeCandidate(10, "Hellsing")]}, FakeFinder(Franchise(truncated=True))
    )

    assert isinstance(session.start(), CandidateChoice)


def test_tie_passes_every_option_id_to_the_finder():
    finder = FakeFinder(FRANCHISE)
    session = _session({"Hellsing": TIE}, finder)

    step = session.start()

    assert finder.calls == [[10, 20]]
    assert isinstance(step, CandidateChoice)
    assert step.options == tuple(TIE)
    assert step.preselected == frozenset()
    assert step.franchise == FRANCHISE


def test_choose_many_accepts_franchise_and_option_ids():
    session = _session({"Hellsing": TIE}, FakeFinder(FRANCHISE))
    session.start()

    step = session.choose_many([(30, ListStatus.PLAN_TO_WATCH), (20, ListStatus.DROPPED)])

    assert isinstance(step, Finished)
    assert step.imported == (
        ImportedAnime(30, "Hellsing Ultimate", ListStatus.PLAN_TO_WATCH),
        ImportedAnime(20, "Hellsing", ListStatus.DROPPED),
    )


@pytest.mark.parametrize(
    "selections",
    [
        [],
        [(999, ListStatus.COMPLETED)],
        [(10, ListStatus.COMPLETED), (999, ListStatus.COMPLETED)],
        [(30, ListStatus.COMPLETED), (30, ListStatus.DROPPED)],
    ],
)
def test_choose_many_invalid_raises_and_changes_nothing(selections):
    session = _session({"Hellsing": TIE}, FakeFinder(FRANCHISE))
    step = session.start()

    with pytest.raises(ValueError):
        session.choose_many(selections)

    assert session.current is step
    assert session.progress == (0, 1)
    # Nothing was imported by the failed call: a valid retry yields only its own entry.
    done = session.choose_many([(10, ListStatus.COMPLETED)])
    assert [entry.mal_id for entry in done.imported] == [10]


def test_without_finder_behaves_as_before():
    session = _session({"Hellsing": TIE}, None)

    step = session.start()

    assert isinstance(step, CandidateChoice)
    assert step.franchise == Franchise()
    assert step.preselected == frozenset()
    auto = _session({"Hellsing": [AnimeCandidate(10, "Hellsing")]}, None)
    assert isinstance(auto.start(), Finished)
