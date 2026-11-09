import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from anime_importer.domain.models import NormalizedTitle
from anime_importer.domain.session import (
    Decision,
    Resolution,
    SessionSummary,
    StoredSession,
)
from anime_importer.ports import PersistenceError


@dataclass(slots=True)
class _Record:
    titles: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    normalized: tuple[NormalizedTitle, ...] | None = None
    resolutions: list[Resolution] = field(default_factory=list)
    answers: dict[tuple[int, str], Resolution] = field(default_factory=dict)
    decisions: list[tuple[int, Decision]] = field(default_factory=list)


class InMemorySessionRepository:
    """SessionRepository kept in memory. Thread-safe."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._records: dict[str, _Record] = {}

    def _get(self, session_id: str) -> _Record:
        record = self._records.get(session_id)
        if record is None:
            raise PersistenceError(f"Unknown session: {session_id}")
        return record

    def create(self, session_id: str, titles: Sequence[str]) -> None:
        with self._lock:
            if session_id in self._records:
                raise PersistenceError(f"Session already exists: {session_id}")
            now = self._clock()
            self._records[session_id] = _Record(tuple(titles), created_at=now, updated_at=now)

    def save_normalization(self, session_id: str, normalized: Sequence[NormalizedTitle]) -> None:
        with self._lock:
            record = self._get(session_id)
            record.normalized = tuple(normalized)
            record.updated_at = self._clock()

    def add_resolution(self, session_id: str, position: int, resolution: Resolution) -> None:
        with self._lock:
            record = self._get(session_id)
            if position != len(record.resolutions):
                raise PersistenceError(
                    f"Expected resolution position {len(record.resolutions)}, got {position}"
                )
            record.resolutions.append(resolution)
            record.updated_at = self._clock()

    def save_answer(
        self, session_id: str, position: int, query: str, resolution: Resolution
    ) -> None:
        with self._lock:
            record = self._get(session_id)
            record.answers[(position, query)] = resolution
            record.updated_at = self._clock()

    def add_decision(self, session_id: str, position: int, decision: Decision) -> None:
        with self._lock:
            record = self._get(session_id)
            record.decisions.append((position, decision))
            record.updated_at = self._clock()

    def remove_last_decision(self, session_id: str) -> bool:
        with self._lock:
            record = self._get(session_id)
            if not record.decisions:
                return False
            record.decisions.pop()
            record.updated_at = self._clock()
            return True

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._records.pop(session_id, None) is not None

    def load(self, session_id: str) -> StoredSession | None:
        with self._lock:
            record = self._records.get(session_id)
            if record is None:
                return None
            return StoredSession(
                id=session_id,
                titles=record.titles,
                normalized=record.normalized,
                resolutions=tuple(record.resolutions),
                answers=dict(record.answers),
                decisions=tuple(record.decisions),
            )

    def list_recent(self, limit: int) -> list[SessionSummary]:
        with self._lock:
            items = sorted(self._records.items(), key=lambda kv: kv[1].updated_at, reverse=True)
            return [
                SessionSummary(
                    id=session_id,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    title_count=len(r.titles),
                    preview=r.titles[:3],
                    decision_count=len(r.decisions),
                )
                for session_id, r in items[: max(limit, 0)]
            ]
