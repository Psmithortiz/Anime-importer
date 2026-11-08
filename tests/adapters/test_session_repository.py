import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anime_importer.adapters.memory_repository import InMemorySessionRepository
from anime_importer.adapters.sqlite_repository import SqliteSessionRepository
from anime_importer.domain.models import ImportedAnime, ListStatus, NormalizedTitle
from anime_importer.domain.session import (
    Ask,
    Discard,
    Imported,
    NormalizationChoice,
    PickCandidates,
    PickQuery,
    Rejected,
)
from anime_importer.ports import PersistenceError


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def tick(self, seconds: int = 1) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path: Path, clock: FakeClock):
    if request.param == "memory":
        return InMemorySessionRepository(clock=clock)
    return SqliteSessionRepository(tmp_path / "sessions.db", clock=clock)


def _imported(mal_id: int = 1) -> Imported:
    return Imported(ImportedAnime(mal_id=mal_id, title=f"T{mal_id}"))


# ------------------------------------------------------------------ contract (both)


def test_create_and_load(repo) -> None:
    repo.create("s1", ["a", "b"])

    stored = repo.load("s1")

    assert stored is not None
    assert stored.id == "s1"
    assert stored.titles == ("a", "b")
    assert stored.normalized is None
    assert stored.resolutions == ()
    assert stored.answers == {}
    assert stored.decisions == ()


def test_create_duplicate_raises(repo) -> None:
    repo.create("s1", ["a"])

    with pytest.raises(PersistenceError):
        repo.create("s1", ["a"])


def test_load_unknown_returns_none(repo) -> None:
    assert repo.load("missing") is None


def test_save_normalization_keeps_index(repo) -> None:
    repo.create("s1", ["a", "b"])
    normalized = [
        NormalizedTitle(index=1, romaji="A"),
        NormalizedTitle(index=2, romaji="B", ambiguous=True, options=("B1", "B2")),
    ]

    repo.save_normalization("s1", normalized)

    assert repo.load("s1").normalized == tuple(normalized)


def test_resolutions_are_returned_in_order(repo) -> None:
    repo.create("s1", ["a", "b", "c"])
    resolutions = [_imported(1), Rejected("nope"), Ask(NormalizationChoice("c", ("x", "c")))]

    for position, resolution in enumerate(resolutions):
        repo.add_resolution("s1", position, resolution)

    assert repo.load("s1").resolutions == tuple(resolutions)


@pytest.mark.parametrize("position", [1, 2, -1])
def test_add_resolution_rejects_wrong_position(repo, position: int) -> None:
    repo.create("s1", ["a", "b"])

    with pytest.raises(PersistenceError):
        repo.add_resolution("s1", position, _imported())

    assert repo.load("s1").resolutions == ()


def test_add_resolution_rejects_repeated_position(repo) -> None:
    repo.create("s1", ["a", "b"])
    repo.add_resolution("s1", 0, _imported())

    with pytest.raises(PersistenceError):
        repo.add_resolution("s1", 0, _imported(2))

    assert repo.load("s1").resolutions == (_imported(),)


def test_answers_are_keyed_by_position_and_query_and_replace(repo) -> None:
    repo.create("s1", ["a"])
    repo.save_answer("s1", 0, "q1", Rejected("first"))
    repo.save_answer("s1", 0, "q2", _imported(2))
    repo.save_answer("s1", 0, "q1", Rejected("second"))

    assert repo.load("s1").answers == {(0, "q1"): Rejected("second"), (0, "q2"): _imported(2)}


def test_decisions_in_order_and_remove_last(repo) -> None:
    repo.create("s1", ["a", "b", "c"])
    repo.add_decision("s1", 0, PickQuery("A"))
    repo.add_decision("s1", 1, PickCandidates(((5, ListStatus.WATCHING),)))
    repo.add_decision("s1", 2, Discard())

    assert repo.load("s1").decisions == (
        (0, PickQuery("A")),
        (1, PickCandidates(((5, ListStatus.WATCHING),))),
        (2, Discard()),
    )
    assert repo.remove_last_decision("s1") is True
    assert repo.load("s1").decisions == (
        (0, PickQuery("A")),
        (1, PickCandidates(((5, ListStatus.WATCHING),))),
    )
    repo.add_decision("s1", 2, PickQuery("again"))
    assert repo.load("s1").decisions[-1] == (2, PickQuery("again"))


def test_remove_last_decision_without_decisions_returns_false(repo) -> None:
    repo.create("s1", ["a"])

    assert repo.remove_last_decision("s1") is False


@pytest.mark.parametrize(
    "operation",
    [
        lambda r: r.save_normalization("x", []),
        lambda r: r.add_resolution("x", 0, Rejected("r")),
        lambda r: r.save_answer("x", 0, "q", Rejected("r")),
        lambda r: r.add_decision("x", 0, Discard()),
        lambda r: r.remove_last_decision("x"),
    ],
    ids=["normalization", "resolution", "answer", "add_decision", "remove_decision"],
)
def test_unknown_session_raises(repo, operation) -> None:
    with pytest.raises(PersistenceError):
        operation(repo)


def test_list_recent_orders_by_updated_at_and_respects_limit(repo, clock: FakeClock) -> None:
    for session_id in ("s1", "s2", "s3"):
        repo.create(session_id, [f"{session_id}-{n}" for n in range(5)])
        clock.tick()
    clock.tick()
    repo.add_decision("s1", 0, Discard())  # s1 becomes the most recent

    summaries = repo.list_recent(10)

    assert [s.id for s in summaries] == ["s1", "s3", "s2"]
    assert summaries[0].title_count == 5
    assert summaries[0].preview == ("s1-0", "s1-1", "s1-2")
    assert summaries[0].decision_count == 1
    assert summaries[1].decision_count == 0
    assert [s.id for s in repo.list_recent(2)] == ["s1", "s3"]


def test_list_recent_empty(repo) -> None:
    assert repo.list_recent(5) == []


def test_every_write_updates_updated_at(repo, clock: FakeClock) -> None:
    repo.create("s1", ["a"])
    created = clock.now
    writes = [
        lambda: repo.save_normalization("s1", [NormalizedTitle(index=1, romaji="A")]),
        lambda: repo.add_resolution("s1", 0, _imported()),
        lambda: repo.save_answer("s1", 0, "q", _imported()),
        lambda: repo.add_decision("s1", 0, Discard()),
        lambda: repo.remove_last_decision("s1"),
    ]

    for write in writes:
        clock.tick()
        write()
        summary = repo.list_recent(1)[0]
        assert summary.created_at == created
        assert summary.updated_at == clock.now


def test_load_returns_copies(repo) -> None:
    repo.create("s1", ["a"])
    repo.save_answer("s1", 0, "q", _imported())

    first = repo.load("s1")
    first.answers.clear()

    assert repo.load("s1").answers == {(0, "q"): _imported()}


# ------------------------------------------------------------------ sqlite only


def test_sqlite_reopening_keeps_everything(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "sessions.db"
    first = SqliteSessionRepository(path)
    first.create("s1", ["a", "b"])
    first.save_normalization("s1", [NormalizedTitle(index=1, romaji="A")])
    first.add_resolution("s1", 0, _imported())
    first.save_answer("s1", 0, "q", Rejected("r"))
    first.add_decision("s1", 0, Discard())

    stored = SqliteSessionRepository(path).load("s1")

    assert stored.titles == ("a", "b")
    assert stored.normalized == (NormalizedTitle(index=1, romaji="A"),)
    assert stored.resolutions == (_imported(),)
    assert stored.answers == {(0, "q"): Rejected("r")}
    assert stored.decisions == ((0, Discard()),)


def test_sqlite_sets_schema_version_and_wal(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    SqliteSessionRepository(path)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_sqlite_newer_schema_version_raises(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version=2")
    conn.close()

    with pytest.raises(PersistenceError, match="newer version"):
        SqliteSessionRepository(path)


def test_sqlite_delete_cascades(tmp_path: Path) -> None:
    path = tmp_path / "sessions.db"
    repo = SqliteSessionRepository(path)
    repo.create("s1", ["a"])
    repo.add_resolution("s1", 0, _imported())
    repo.save_answer("s1", 0, "q", _imported())
    repo.add_decision("s1", 0, Discard())

    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        with conn:
            conn.execute("DELETE FROM sessions WHERE id='s1'")
        counts = [
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("resolutions", "answers", "decisions")
        ]
    finally:
        conn.close()

    assert counts == [0, 0, 0]
    assert repo.load("s1") is None
