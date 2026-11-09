import pytest
from session_helpers import make_session

from anime_importer.adapters.memory_repository import InMemorySessionRepository
from anime_importer.domain.models import (
    AnimeCandidate,
    Franchise,
    FranchiseEntry,
    ListStatus,
    NormalizedTitle,
    RelationType,
)
from anime_importer.domain.session import (
    CandidateChoice,
    Discard,
    Finished,
    NormalizationChoice,
    PickCandidates,
    PickQuery,
    Rejected,
)
from anime_importer.ports import PersistenceError
from anime_importer.services.import_session import ImportSession, ResolutionError


def sync(fn):
    fn()


class PlainNormalizer:
    """Normalizes every title to itself; `overrides` maps an index to a custom NormalizedTitle."""

    def __init__(self, overrides: dict[int, NormalizedTitle] | None = None) -> None:
        self._overrides = overrides or {}
        self.calls = 0

    def normalize(self, titles, on_progress=None):
        self.calls += 1
        return [
            self._overrides.get(i, NormalizedTitle(i, title))
            for i, title in enumerate(titles, start=1)
        ]


class RecordingSearcher:
    def __init__(self, results: dict[str, list[AnimeCandidate]]) -> None:
        self._results = results
        self.queries: list[str] = []

    def search(self, query):
        self.queries.append(query)
        return self._results.get(query, [])


class ForbiddenNormalizer:
    def normalize(self, titles, on_progress=None):
        raise AssertionError("the normalizer must not be called")


class ForbiddenSearcher:
    def search(self, query):
        raise AssertionError("the searcher must not be called")


def forbidden_finder(seed_ids):
    raise AssertionError("the franchise finder must not be called")


class FailingRepository(InMemorySessionRepository):
    """In-memory repository whose chosen operations raise PersistenceError while armed."""

    def __init__(self) -> None:
        super().__init__()
        self.failing: set[str] = set()

    def _check(self, operation: str) -> None:
        if operation in self.failing:
            raise PersistenceError(f"{operation} failed")

    def add_decision(self, session_id, position, decision):
        self._check("add_decision")
        super().add_decision(session_id, position, decision)

    def save_answer(self, session_id, position, query, resolution):
        self._check("save_answer")
        super().save_answer(session_id, position, query, resolution)

    def add_resolution(self, session_id, position, resolution):
        self._check("add_resolution")
        super().add_resolution(session_id, position, resolution)


def tie(name: str, first_id: int) -> list[AnimeCandidate]:
    return [AnimeCandidate(first_id, name), AnimeCandidate(first_id + 1, name)]


def one(name: str, mal_id: int) -> list[AnimeCandidate]:
    return [AnimeCandidate(mal_id, name)]


def resume(repository, session_id="s", **deps) -> ImportSession:
    """Rebuild a session from the repository, with collaborators that fail if used."""
    deps.setdefault("normalizer", ForbiddenNormalizer())
    deps.setdefault("searcher", ForbiddenSearcher())
    deps.setdefault("franchise_finder", forbidden_finder)
    stored = repository.load(session_id)
    assert stored is not None
    return ImportSession(stored, repository=repository, run_in_background=sync, **deps)


# ------------------------------------------------------------------ rebuilding


SEQUEL = AnimeCandidate(2, "Alpha 2")
ALPHA_FRANCHISE = Franchise(entries=(FranchiseEntry(SEQUEL, RelationType.SEQUEL),))


def _alpha_finder(seed_ids):
    return ALPHA_FRANCHISE if list(seed_ids) == [1] else Franchise()


def _full_scenario(repository):
    titles = ["amb", "Tie", "Auto", "skip", "Tie2"]
    normalizer = PlainNormalizer(
        {
            1: NormalizedTitle(1, "amb", ambiguous=True, options=("Alpha", "Beta")),
            4: NormalizedTitle(4, "skip", is_anime=False),
        }
    )
    searcher = RecordingSearcher(
        {
            "Alpha": one("Alpha", 1),
            "Tie": tie("Tie", 10),
            "Auto": one("Auto", 3),
            "Tie2": tie("Tie2", 30),
        }
    )
    session = make_session(
        titles,
        normalizer,
        searcher,
        repository=repository,
        session_id="s",
        franchise_finder=_alpha_finder,
        run_in_background=sync,
    )
    return session


def test_rebuilt_session_is_equivalent_at_every_point():
    repository = InMemorySessionRepository()
    session = _full_scenario(repository)

    steps = [session.start()]
    assert isinstance(steps[-1], NormalizationChoice)
    steps.append(session.choose(1))  # "Alpha" -> auto match with franchise -> asks
    assert isinstance(steps[-1], CandidateChoice)
    assert steps[-1].franchise == ALPHA_FRANCHISE
    steps.append(session.choose_many([(1, ListStatus.WATCHING), (2, ListStatus.PLAN_TO_WATCH)]))
    steps.append(session.choose(2))  # second "Tie" candidate
    assert isinstance(steps[-1], CandidateChoice)
    assert steps[-1].query == "Tie2"

    rebuilt = resume(repository)
    assert rebuilt.start() == session.current
    assert rebuilt.progress == session.progress

    final = session.discard()
    assert isinstance(final, Finished)

    rebuilt = resume(repository)
    assert rebuilt.start() == final
    assert rebuilt.progress == session.progress
    assert final.rejected == rebuilt.current.rejected
    assert {e.mal_id: e.list_status for e in final.imported} == {
        1: ListStatus.WATCHING,
        2: ListStatus.PLAN_TO_WATCH,
        11: ListStatus.COMPLETED,
        3: ListStatus.COMPLETED,
    }
    assert {r.original_title for r in final.rejected} == {"skip", "Tie2"}


def test_stored_decisions_record_identity_not_option_numbers():
    repository = InMemorySessionRepository()
    session = _full_scenario(repository)
    session.start()
    session.choose(1)
    session.choose_many([(1, ListStatus.WATCHING), (2, ListStatus.DROPPED)])
    session.choose(2)
    session.discard()

    assert repository.load("s").decisions == (
        (0, PickQuery("Alpha")),
        (0, PickCandidates(((1, ListStatus.WATCHING), (2, ListStatus.DROPPED)))),
        (1, PickCandidates(((11, ListStatus.COMPLETED),))),
        (4, Discard()),
    )


def test_session_exposes_its_id():
    session = make_session(["a"], PlainNormalizer(), RecordingSearcher({}), session_id="abc")

    assert session.id == "abc"


def test_resume_from_stored_session_does_not_normalize_again():
    repository = InMemorySessionRepository()
    session = _full_scenario(repository)
    session.start()

    resume(repository).start()  # ForbiddenNormalizer would raise


def test_normalization_is_saved_before_use():
    repository = InMemorySessionRepository()
    session = make_session(
        ["a", "b"], PlainNormalizer(), RecordingSearcher({}), repository=repository, session_id="s"
    )
    assert repository.load("s").normalized is None

    session.start()

    assert [t.index for t in repository.load("s").normalized] == [1, 2]


def test_resume_halfway_only_searches_missing_positions():
    repository = InMemorySessionRepository()
    repository.create("s", ["A", "B", "C", "D"])
    repository.save_normalization("s", [NormalizedTitle(i, t) for i, t in enumerate("ABCD", 1)])
    repository.add_resolution("s", 0, Rejected("done before"))
    repository.add_resolution("s", 1, Rejected("done before"))
    searcher = RecordingSearcher({"C": one("C", 3), "D": one("D", 4)})

    step = resume(repository, searcher=searcher, franchise_finder=None).start()

    assert searcher.queries == ["C", "D"]
    assert isinstance(step, Finished)
    assert [e.mal_id for e in step.imported] == [3, 4]
    assert len(repository.load("s").resolutions) == 4


def test_mismatching_stored_decisions_raise_persistence_error():
    repository = InMemorySessionRepository()
    session = make_session(
        ["Tie", "Auto"],
        PlainNormalizer(),
        RecordingSearcher({"Tie": tie("Tie", 10), "Auto": one("Auto", 3)}),
        repository=repository,
        session_id="s",
        run_in_background=sync,
    )
    session.start()
    repository.add_decision("s", 0, Discard())
    repository.add_decision("s", 1, Discard())  # there is no question at position 1

    with pytest.raises(PersistenceError, match="do not match"):
        resume(repository).start()


# ------------------------------------------------------------------ undo


def _undo_session():
    """Question at 0, automatic 1-3, question at 4."""
    titles = ["q0", "a1", "a2", "a3", "q4"]
    searcher = RecordingSearcher(
        {
            "q0": tie("q0", 100),
            "a1": one("a1", 1),
            "a2": one("a2", 2),
            "a3": one("a3", 3),
            "q4": tie("q4", 200),
        }
    )
    session = make_session(titles, PlainNormalizer(), searcher, run_in_background=sync)
    return session, searcher


def test_undo_walks_back_question_by_question():
    session, _ = _undo_session()
    first = session.start()
    second = session.choose(1)
    assert second.original_title == "q4"
    finished = session.choose(1)
    assert isinstance(finished, Finished)

    back_to_last = session.undo()
    assert back_to_last == second
    assert session.progress == (4, 5)

    back_to_first = session.undo()
    assert back_to_first == first
    assert session.progress == (0, 5)

    # Redo: the automatic titles 1-3 are imported again when the answers are replayed.
    session.choose(2)
    finished = session.choose(2)
    assert isinstance(finished, Finished)
    assert {e.mal_id for e in finished.imported} == {101, 1, 2, 3, 201}


def test_undo_keeps_automatic_titles_imported_while_on_the_later_question():
    session, _ = _undo_session()
    session.start()
    session.choose(1)
    session.choose(1)

    session.undo()
    finished = session.choose(2)

    assert {e.mal_id for e in finished.imported} == {100, 1, 2, 3, 201}


def test_undo_removes_the_decision_from_the_repository():
    repository = InMemorySessionRepository()
    session = make_session(
        ["Tie", "Tie2"],
        PlainNormalizer(),
        RecordingSearcher({"Tie": tie("Tie", 10), "Tie2": tie("Tie2", 20)}),
        repository=repository,
        session_id="s",
        run_in_background=sync,
    )
    session.start()
    session.choose(1)
    assert len(repository.load("s").decisions) == 1

    session.undo()

    assert repository.load("s").decisions == ()
    assert session.progress == (0, 2)


def test_undo_without_decisions_raises_value_error():
    session, _ = _undo_session()
    session.start()

    with pytest.raises(ValueError, match="Nothing to undo"):
        session.undo()


def test_undo_from_finished_returns_to_the_last_question():
    repository = InMemorySessionRepository()
    session = make_session(
        ["Tie"],
        PlainNormalizer(),
        RecordingSearcher({"Tie": tie("Tie", 10)}),
        repository=repository,
        session_id="s",
        run_in_background=sync,
    )
    question = session.start()
    assert isinstance(session.choose(1), Finished)

    assert session.undo() == question
    assert repository.load("s").decisions == ()


def test_undo_of_a_normalization_answer_reuses_the_stored_search():
    normalizer = PlainNormalizer(
        {1: NormalizedTitle(1, "amb", ambiguous=True, options=("Alpha", "Beta"))}
    )
    searcher = RecordingSearcher({"Alpha": tie("Alpha", 1), "Beta": tie("Beta", 5)})
    repository = InMemorySessionRepository()
    session = make_session(
        ["amb"],
        normalizer,
        searcher,
        repository=repository,
        session_id="s",
        run_in_background=sync,
    )
    question = session.start()
    assert isinstance(question, NormalizationChoice)

    alpha_question = session.choose(1)
    assert isinstance(alpha_question, CandidateChoice)
    assert searcher.queries == ["Alpha"]

    assert session.undo() == question
    assert session.choose(1) == alpha_question
    assert searcher.queries == ["Alpha"]  # same option again: no new search

    session.undo()
    beta_question = session.choose(2)
    assert beta_question.query == "Beta"
    assert searcher.queries == ["Alpha", "Beta"]
    assert set(repository.load("s").answers) == {(0, "Alpha"), (0, "Beta")}


# ------------------------------------------------------------------ save before applying


def _tie_session(repository, normalizer=None, searcher=None):
    return make_session(
        ["Tie", "Auto"],
        normalizer or PlainNormalizer(),
        searcher or RecordingSearcher({"Tie": tie("Tie", 10), "Auto": one("Auto", 3)}),
        repository=repository,
        session_id="s",
        run_in_background=sync,
    )


def test_failed_add_decision_leaves_the_session_untouched():
    repository = FailingRepository()
    session = _tie_session(repository)
    question = session.start()
    repository.failing = {"add_decision"}

    with pytest.raises(PersistenceError):
        session.choose(1)

    assert session.current == question
    assert session.progress == (0, 2)
    assert repository.load("s").decisions == ()

    repository.failing = set()
    finished = session.choose(1)
    assert [e.mal_id for e in finished.imported] == [10, 3]  # nothing applied twice


@pytest.mark.parametrize("action", ["choose_many", "discard"])
def test_failed_add_decision_in_other_actions_leaves_the_session_untouched(action):
    repository = FailingRepository()
    session = _tie_session(repository)
    question = session.start()
    repository.failing = {"add_decision"}

    with pytest.raises(PersistenceError):
        if action == "choose_many":
            session.choose_many([(10, ListStatus.COMPLETED)])
        else:
            session.discard()

    assert session.current == question
    assert session.progress == (0, 2)
    repository.failing = set()
    finished = session.discard()
    assert finished.rejected[0].original_title == "Tie"
    assert [e.mal_id for e in finished.imported] == [3]


def test_failed_save_answer_leaves_the_session_untouched_and_caches_nothing():
    repository = FailingRepository()
    normalizer = PlainNormalizer(
        {1: NormalizedTitle(1, "amb", ambiguous=True, options=("Alpha", "Beta"))}
    )
    searcher = RecordingSearcher({"Alpha": tie("Alpha", 1)})
    session = make_session(
        ["amb"],
        normalizer,
        searcher,
        repository=repository,
        session_id="s",
        run_in_background=sync,
    )
    question = session.start()
    repository.failing = {"save_answer"}

    with pytest.raises(PersistenceError):
        session.choose(1)

    assert session.current == question
    assert session.progress == (0, 1)
    assert repository.load("s").answers == {}
    assert repository.load("s").decisions == ()

    repository.failing = set()
    session.choose(1)
    assert searcher.queries == ["Alpha", "Alpha"]  # the failed answer was not cached


def test_persistence_error_in_the_worker_surfaces_as_resolution_error():
    repository = FailingRepository()
    repository.failing = {"add_resolution"}
    session = _tie_session(repository)

    with pytest.raises(ResolutionError) as info:
        session.start()

    assert isinstance(info.value.__cause__, PersistenceError)
    assert repository.load("s").resolutions == ()


# ------------------------------------------------------------------ atomic publication


def _recording_apply(session, seen):
    original = session._apply_decision

    def wrapper(work, decision):
        seen.append(session.snapshot())
        return original(work, decision)

    session._apply_decision = wrapper


def test_undo_never_exposes_intermediate_state():
    searcher = RecordingSearcher({f"q{n}": tie(f"q{n}", n * 10) for n in range(4)})
    session = make_session(
        [f"q{n}" for n in range(4)], PlainNormalizer(), searcher, run_in_background=sync
    )
    session.start()
    for _ in range(4):
        session.choose(1)
    before = session.snapshot()
    assert isinstance(before.current, Finished)
    seen: list = []
    _recording_apply(session, seen)

    after_undo = session.undo()

    assert len(seen) == 3  # the three remaining decisions were replayed
    assert all(snapshot == before for snapshot in seen)
    after = session.snapshot()
    assert after != before
    assert after.current == after_undo
    assert after.position == 3


def test_resumed_start_never_exposes_intermediate_state():
    repository = InMemorySessionRepository()
    searcher = RecordingSearcher({f"q{n}": tie(f"q{n}", n * 10) for n in range(3)})
    first = make_session(
        [f"q{n}" for n in range(3)],
        PlainNormalizer(),
        searcher,
        repository=repository,
        session_id="s",
        run_in_background=sync,
    )
    first.start()
    first.choose(1)
    first.choose(2)
    resumed = resume(repository, searcher=searcher)
    seen: list = []
    _recording_apply(resumed, seen)

    step = resumed.start()

    assert len(seen) == 2
    assert all(snapshot.current is None for snapshot in seen)
    assert resumed.snapshot().current == step
    assert resumed.snapshot().position == 2


def test_failure_in_the_middle_of_an_action_keeps_the_decision_and_the_snapshot():
    class BrokenSearcher(RecordingSearcher):
        def search(self, query):
            if query == "Auto":
                raise RuntimeError("boom")
            return super().search(query)

    repository = InMemorySessionRepository()
    session = make_session(
        ["Tie", "Auto"],
        PlainNormalizer(),
        BrokenSearcher({"Tie": tie("Tie", 10)}),
        repository=repository,
        session_id="s",
        run_in_background=sync,
    )
    session.start()
    before = session.snapshot()

    with pytest.raises(ResolutionError):
        session.choose(1)  # advancing needs the resolution that the worker could not produce

    assert session.snapshot() == before
    assert session.progress == (0, 2)
    # The saved decision is a fact: it stays in the log...
    assert repository.load("s").decisions == ((0, PickCandidates(((10, ListStatus.COMPLETED),))),)
    assert session.can_undo

    # ...and a session rebuilt with a healthy worker applies it.
    healthy = RecordingSearcher({"Tie": tie("Tie", 10), "Auto": one("Auto", 3)})
    rebuilt = resume(repository, searcher=healthy, franchise_finder=None)
    finished = rebuilt.start()
    assert isinstance(finished, Finished)
    assert [e.mal_id for e in finished.imported] == [10, 3]


def test_can_undo_follows_the_decisions():
    session, _ = _undo_session()
    session.start()
    assert not session.can_undo

    session.choose(1)
    assert session.can_undo

    session.undo()
    assert not session.can_undo


def test_snapshot_is_consistent_and_frozen():
    session, _ = _undo_session()
    session.start()

    snap = session.snapshot()

    assert snap.total == 5
    assert snap.position == 0
    assert snap.current == session.current
