from fastapi.testclient import TestClient
from session_helpers import make_session

from anime_importer.api.app import create_app
from anime_importer.domain.models import AnimeCandidate, NormalizedTitle
from anime_importer.domain.session import CandidateChoice, NormalizationChoice


def _normalizer(options):
    class Normalizer:
        def normalize(self, titles, on_progress=None):
            return [NormalizedTitle(1, "R", ambiguous=True, options=tuple(options))]

    return Normalizer()


class Searcher:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query):
        self.queries.append(query)
        return [AnimeCandidate(1, query), AnimeCandidate(2, query)]


def _session(original, options, searcher=None):
    return make_session(
        [original],
        _normalizer(options),
        searcher or Searcher(),
        run_in_background=lambda fn: fn(),
    )


def test_original_line_is_appended_as_last_option():
    step = _session("x", ["A", "B"]).start()

    assert isinstance(step, NormalizationChoice)
    assert step.options == ("A", "B", "x")
    assert step.original_option == 3


def test_original_equal_to_an_option_up_to_case_and_spaces_is_not_added():
    step = _session("Naruto  Shippuden", ["Boruto", "naruto shippuden"]).start()

    assert step.options == ("Boruto", "naruto shippuden")
    assert step.original_option is None


def test_ambiguous_without_options_offers_only_the_original():
    step = _session("x", []).start()

    assert step.options == ("x",)
    assert step.original_option == 1


def test_choosing_the_original_option_searches_the_original_line():
    searcher = Searcher()
    session = _session("x", ["A", "B"], searcher)
    session.start()

    step = session.choose(3)

    assert isinstance(step, CandidateChoice)
    assert searcher.queries == ["x"]  # one search only: no fallback, query == original
    assert step.query == "x"
    assert step.used_fallback is False


def test_api_marks_the_original_option():
    def factory(session_id, titles):
        return _session(titles[0], ["A", "B"])

    client = TestClient(create_app(factory))
    session_id = client.post("/api/sessions", json={"text": "x"}).json()["id"]

    options = client.get(f"/api/sessions/{session_id}").json()["question"]["options"]

    assert [(o["label"], o["is_original"]) for o in options] == [
        ("A", False),
        ("B", False),
        ("x", True),
    ]
