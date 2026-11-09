import json
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anime_importer.adapters.session_codec import (
    decision_from_dict,
    decision_to_dict,
    normalized_from_dict,
    normalized_to_dict,
    resolution_from_dict,
    resolution_to_dict,
)
from anime_importer.domain.models import NormalizedTitle
from anime_importer.domain.session import (
    Decision,
    Resolution,
    SessionSummary,
    StoredSession,
)
from anime_importer.ports import PersistenceError

SCHEMA_VERSION = 1

_SCHEMA_V1 = (
    """CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        titles TEXT NOT NULL,
        normalized TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE resolutions (
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (session_id, position)
    )""",
    """CREATE TABLE answers (
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        query TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (session_id, position, query)
    )""",
    """CREATE TABLE decisions (
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        seq INTEGER NOT NULL,
        position INTEGER NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (session_id, seq)
    )""",
)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


class SqliteSessionRepository:
    """SessionRepository backed by a SQLite file. A new connection per operation."""

    def __init__(
        self, path: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._path = path
        self._clock = clock
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(self._connect()) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                self._migrate(conn)
        except (sqlite3.Error, OSError) as exc:
            raise PersistenceError(f"Cannot open the session database: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise PersistenceError("The database was created by a newer version")
        if version == 0:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA_V1:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat()

    @staticmethod
    def _touch(conn: sqlite3.Connection, session_id: str, now: str) -> None:
        """Update updated_at; doubles as the existence check (inside the caller's transaction)."""
        cursor = conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        if cursor.rowcount == 0:
            raise PersistenceError(f"Unknown session: {session_id}")

    def create(self, session_id: str, titles: Sequence[str]) -> None:
        now = self._now()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    "INSERT INTO sessions (id, titles, normalized, created_at, updated_at)"
                    " VALUES (?, ?, NULL, ?, ?)",
                    (session_id, _dumps(list(titles)), now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise PersistenceError(f"Session already exists: {session_id}") from exc
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot create the session: {exc}") from exc

    def save_normalization(self, session_id: str, normalized: Sequence[NormalizedTitle]) -> None:
        payload = _dumps([normalized_to_dict(t) for t in normalized])
        now = self._now()
        try:
            with closing(self._connect()) as conn, conn:
                self._touch(conn, session_id, now)
                conn.execute("UPDATE sessions SET normalized=? WHERE id=?", (payload, session_id))
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot save the normalization: {exc}") from exc

    def add_resolution(self, session_id: str, position: int, resolution: Resolution) -> None:
        payload = _dumps(resolution_to_dict(resolution))
        now = self._now()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                self._touch(conn, session_id, now)
                count = conn.execute(
                    "SELECT COUNT(*) FROM resolutions WHERE session_id=?", (session_id,)
                ).fetchone()[0]
                if position != count:
                    raise PersistenceError(f"Expected resolution position {count}, got {position}")
                conn.execute(
                    "INSERT INTO resolutions (session_id, position, payload) VALUES (?, ?, ?)",
                    (session_id, position, payload),
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot add the resolution: {exc}") from exc

    def save_answer(
        self, session_id: str, position: int, query: str, resolution: Resolution
    ) -> None:
        payload = _dumps(resolution_to_dict(resolution))
        now = self._now()
        try:
            with closing(self._connect()) as conn, conn:
                self._touch(conn, session_id, now)
                conn.execute(
                    "INSERT OR REPLACE INTO answers (session_id, position, query, payload)"
                    " VALUES (?, ?, ?, ?)",
                    (session_id, position, query, payload),
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot save the answer: {exc}") from exc

    def add_decision(self, session_id: str, position: int, decision: Decision) -> None:
        payload = _dumps(decision_to_dict(decision))
        now = self._now()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                self._touch(conn, session_id, now)
                conn.execute(
                    "INSERT INTO decisions (session_id, seq, position, payload)"
                    " SELECT ?, COALESCE(MAX(seq) + 1, 0), ?, ? FROM decisions WHERE session_id=?",
                    (session_id, position, payload, session_id),
                )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot add the decision: {exc}") from exc

    def remove_last_decision(self, session_id: str) -> bool:
        now = self._now()
        try:
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                self._touch(conn, session_id, now)
                cursor = conn.execute(
                    "DELETE FROM decisions WHERE session_id=? AND seq ="
                    " (SELECT MAX(seq) FROM decisions WHERE session_id=?)",
                    (session_id, session_id),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot remove the decision: {exc}") from exc

    def delete(self, session_id: str) -> bool:
        try:
            with closing(self._connect()) as conn, conn:
                cursor = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
                return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot delete the session: {exc}") from exc

    def load(self, session_id: str) -> StoredSession | None:
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute(
                    "SELECT titles, normalized FROM sessions WHERE id=?", (session_id,)
                ).fetchone()
                if row is None:
                    return None
                resolutions = conn.execute(
                    "SELECT payload FROM resolutions WHERE session_id=? ORDER BY position",
                    (session_id,),
                ).fetchall()
                answers = conn.execute(
                    "SELECT position, query, payload FROM answers WHERE session_id=?",
                    (session_id,),
                ).fetchall()
                decisions = conn.execute(
                    "SELECT position, payload FROM decisions WHERE session_id=? ORDER BY seq",
                    (session_id,),
                ).fetchall()
            titles, normalized = row
            return StoredSession(
                id=session_id,
                titles=tuple(json.loads(titles)),
                normalized=(
                    None
                    if normalized is None
                    else tuple(normalized_from_dict(d) for d in json.loads(normalized))
                ),
                resolutions=tuple(resolution_from_dict(json.loads(p)) for (p,) in resolutions),
                answers={
                    (position, query): resolution_from_dict(json.loads(p))
                    for position, query, p in answers
                },
                decisions=tuple((pos, decision_from_dict(json.loads(p))) for pos, p in decisions),
            )
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot load the session: {exc}") from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise PersistenceError(f"Corrupt data in session {session_id}: {exc}") from exc

    def list_recent(self, limit: int) -> list[SessionSummary]:
        try:
            with closing(self._connect()) as conn, conn:
                rows = conn.execute(
                    "SELECT s.id, s.titles, s.created_at, s.updated_at,"
                    " (SELECT COUNT(*) FROM decisions d WHERE d.session_id = s.id)"
                    " FROM sessions s ORDER BY s.updated_at DESC, s.rowid DESC LIMIT ?",
                    (max(limit, 0),),
                ).fetchall()
            summaries = []
            for session_id, titles_json, created_at, updated_at, decision_count in rows:
                titles = json.loads(titles_json)
                summaries.append(
                    SessionSummary(
                        id=session_id,
                        created_at=datetime.fromisoformat(created_at),
                        updated_at=datetime.fromisoformat(updated_at),
                        title_count=len(titles),
                        preview=tuple(titles[:3]),
                        decision_count=decision_count,
                    )
                )
            return summaries
        except sqlite3.Error as exc:
            raise PersistenceError(f"Cannot list the sessions: {exc}") from exc
        except (ValueError, TypeError) as exc:
            raise PersistenceError(f"Corrupt session data: {exc}") from exc
