import threading

import pytest
from session_helpers import make_session

from anime_importer.domain.models import (
    AnimeCandidate,
    Franchise,
    ImportedAnime,
    ListStatus,
    NormalizedTitle,
)
from anime_importer.domain.session import CandidateChoice, Finished
from anime_importer.services.import_session import ResolutionError

TIMEOUT = 2.0


def sync(fn):
    fn()


class Normalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, title) for i, title in enumerate(titles, start=1)]


class CountingSearcher:
    def __init__(self, results):
        self._results = results
        self.calls: list[str] = []

    def search(self, query):
        self.calls.append(query)
        return self._results.get(query, [])


class CountingFinder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, seeds):
        self.calls += 1
        return Franchise()


TIE = [AnimeCandidate(10, "Hellsing"), AnimeCandidate(20, "Hellsing")]


def test_advancing_never_calls_searcher_or_finder():
    searcher = CountingSearcher(
        {"Hellsing": TIE, "Naruto": TIE, "Bleach": [AnimeCandidate(3, "Bleach")]}
    )
    finder = CountingFinder()
    session = make_session(
        ["Hellsing", "Naruto", "Bleach"],
        Normalizer(),
        searcher,
        franchise_finder=finder,
        run_in_background=sync,
    )
    session.start()
    searches, finds = len(searcher.calls), finder.calls

    session.choose_many([(10, ListStatus.COMPLETED)])
    session.discard()

    assert (len(searcher.calls), finder.calls) == (searches, finds)
    assert (searches, finds) == (3, 3)  # every title was searched and looked up once


def test_order_and_last_wins_are_kept():
    results = {
        "A": [AnimeCandidate(5, "A")],
        "B": [AnimeCandidate(6, "B")],
        "C": [AnimeCandidate(5, "C")],
    }
    session = make_session(
        ["A", "B", "C"], Normalizer(), CountingSearcher(results), run_in_background=sync
    )

    step = session.start()

    assert isinstance(step, Finished)
    assert step.imported == (
        ImportedAnime(5, "C", ListStatus.COMPLETED),
        ImportedAnime(6, "B", ListStatus.COMPLETED),
    )


def test_resolution_progress_reaches_total():
    session = make_session(
        ["A", "B", "C"], Normalizer(), CountingSearcher({}), run_in_background=sync
    )
    assert session.resolution_progress is None

    session.start()

    assert session.resolution_progress == (3, 3)


class ExplodingSearcher:
    def search(self, query):
        if query == "B":
            raise RuntimeError("boom")
        return [AnimeCandidate(1, query)]


def test_unexpected_worker_error_raises_resolution_error_when_reached():
    session = make_session(["A", "B"], Normalizer(), ExplodingSearcher(), run_in_background=sync)

    with pytest.raises(ResolutionError) as exc_info:
        session.start()

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_real_thread_start_does_not_wait_for_the_whole_list():
    release = threading.Event()

    class BlockingSearcher:
        def search(self, query):
            if query in {"C", "D"}:
                assert release.wait(TIMEOUT), "test never released the searcher"
            return TIE if query == "A" else [AnimeCandidate(len(query) + ord(query), query)]

    session = make_session(
        ["A", "B", "C", "D"], Normalizer(), BlockingSearcher(), resolution_buffer=2
    )
    result: list = []
    starter = threading.Thread(target=lambda: result.append(session.start()), daemon=True)
    starter.start()
    starter.join(TIMEOUT)

    assert not starter.is_alive(), "start() waited for titles beyond the buffer"
    assert isinstance(result[0], CandidateChoice)
    assert session.resolution_progress is not None
    assert session.resolution_progress[0] < 4

    release.set()
    finisher: list = []
    runner = threading.Thread(
        target=lambda: finisher.append(session.choose_many([(10, ListStatus.COMPLETED)])),
        daemon=True,
    )
    runner.start()
    runner.join(TIMEOUT)

    assert not runner.is_alive()
    assert isinstance(finisher[0], Finished)
    assert session.resolution_progress == (4, 4)
