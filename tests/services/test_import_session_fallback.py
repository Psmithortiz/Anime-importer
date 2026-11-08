from anime_importer.domain.models import AnimeCandidate, ImportedAnime, NormalizedTitle
from anime_importer.domain.session import CandidateChoice, Finished
from anime_importer.ports import SearchError
from anime_importer.services.import_session import ImportSession


class Normalizer:
    def __init__(self, romaji: str) -> None:
        self._romaji = romaji

    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(1, self._romaji)]


class Searcher:
    def __init__(self, results: dict[str, list[AnimeCandidate] | Exception]) -> None:
        self._results = results
        self.queries: list[str] = []

    def search(self, query):
        self.queries.append(query)
        result = self._results.get(query, [])
        if isinstance(result, Exception):
            raise result
        return result


def _session(original: str, romaji: str, results):
    searcher = Searcher(results)
    session = ImportSession(
        [original], Normalizer(romaji), searcher, run_in_background=lambda fn: fn()
    )
    return session, searcher


TIE = [AnimeCandidate(10, "Hellsing"), AnimeCandidate(20, "Hellsing")]


def test_fallback_to_original_line_asks_with_original_as_query():
    session, searcher = _session("hellsing", "Hellsingu", {"hellsing": TIE})

    step = session.start()

    assert isinstance(step, CandidateChoice)
    assert step.query == "hellsing"
    assert step.used_fallback is True
    assert searcher.queries == ["Hellsingu", "hellsing"]


def test_fallback_match_uses_the_effective_query():
    # Only the original line matches the candidate title exactly: auto-accepted.
    session, _ = _session(
        "Hellsing Ultimate", "Zzz", {"Hellsing Ultimate": [AnimeCandidate(7, "Hellsing Ultimate")]}
    )

    step = session.start()

    assert isinstance(step, Finished)
    assert step.imported == (ImportedAnime(7, "Hellsing Ultimate"),)


def test_both_queries_empty_is_rejected_with_both_in_the_message():
    session, searcher = _session("my line", "Romaji Name", {})

    step = session.start()

    assert isinstance(step, Finished)
    assert step.rejected[0].reason == "No results (queries: 'Romaji Name', 'my line')"
    assert searcher.queries == ["Romaji Name", "my line"]


def test_same_query_up_to_case_and_spaces_searches_once():
    session, searcher = _session("Naruto  Shippuden", "naruto shippuden", {})

    step = session.start()

    assert step.rejected[0].reason == "No results (query: naruto shippuden)"
    assert searcher.queries == ["naruto shippuden"]


def test_gemini_query_with_results_never_searches_the_original():
    session, searcher = _session("my line", "Hellsing", {"Hellsing": TIE})

    step = session.start()

    assert isinstance(step, CandidateChoice)
    assert step.query == "Hellsing"
    assert step.used_fallback is False
    assert searcher.queries == ["Hellsing"]


def test_search_error_on_the_fallback_is_a_rejection():
    session, _ = _session("my line", "Romaji", {"my line": SearchError("down")})

    step = session.start()

    assert step.rejected[0].reason == "Search error: down"


def test_fallback_also_applies_to_a_query_chosen_from_a_normalization_menu():
    class AmbiguousNormalizer:
        def normalize(self, titles, on_progress=None):
            return [NormalizedTitle(1, "X", ambiguous=True, options=("Option A", "Option B"))]

    searcher = Searcher({"my line": TIE})
    session = ImportSession(
        ["my line"], AmbiguousNormalizer(), searcher, run_in_background=lambda fn: fn()
    )
    session.start()

    step = session.choose(1)

    assert isinstance(step, CandidateChoice)
    assert step.used_fallback is True
    assert searcher.queries == ["Option A", "my line"]
