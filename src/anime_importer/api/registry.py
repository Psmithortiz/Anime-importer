import logging
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from anime_importer.api.schemas import (
    ProgressOut,
    RejectedOut,
    SessionStatus,
    SessionView,
    SummaryOut,
    question_out,
)
from anime_importer.domain.models import ListStatus
from anime_importer.domain.session import Finished, SessionSummary, Step
from anime_importer.ports import NormalizationError, PersistenceError
from anime_importer.services.import_session import (
    BackgroundRunner,
    ImportSession,
    ResolutionError,
    start_daemon_thread,
)

logger = logging.getLogger(__name__)


class SessionProvider(Protocol):
    """What the registry needs to create, restore and list sessions."""

    def new_session(self, session_id: str, titles: Sequence[str]) -> ImportSession: ...

    def restore_session(self, session_id: str) -> ImportSession | None: ...

    def list_recent(self, limit: int) -> list[SessionSummary]: ...


class SessionNotFoundError(Exception):
    """No session exists with that id."""


class NotConfiguredError(Exception):
    """The API keys are not configured yet, so sessions cannot be created or restored."""


class InvalidStateError(Exception):
    """The operation is not valid in the current state of the session."""


@dataclass
class ManagedSession:
    id: str
    session: ImportSession
    status: SessionStatus = "preparing"
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def run_start(self) -> None:
        """Runs in the background. Must never leave the status at "preparing"."""
        with self.lock:
            try:
                self._apply(self.session.start())
            except NormalizationError as exc:
                self.error = str(exc)
                self.status = "failed"
            except ResolutionError:
                self._fail_resolution()
            except PersistenceError:
                logger.exception("Session %s: persistence failed", self.id)
                self.error = "Could not read or save the session; try again"
                self.status = "failed"
            except Exception:
                logger.exception("Session %s failed", self.id)
                self.error = "Internal error while processing the list"
                self.status = "failed"

    def choose(self, option: int) -> None:
        with self.lock:
            self._require("question")
            self._advance_with(lambda: self.session.choose(option))

    def choose_many(self, selections: Sequence[tuple[int, ListStatus]]) -> None:
        with self.lock:
            self._require("question")
            self._advance_with(lambda: self.session.choose_many(selections))

    def discard(self) -> None:
        with self.lock:
            self._require("question")
            self._advance_with(self.session.discard)

    def undo(self) -> None:
        with self.lock:
            if self.status not in ("question", "finished"):
                raise InvalidStateError(f"Operation not valid in state '{self.status}'")
            try:
                self._advance_with(self.session.undo)
            except ValueError as exc:
                raise InvalidStateError(str(exc)) from None

    def finished(self) -> Finished:
        self._require("finished")
        step = self.session.current
        assert isinstance(step, Finished)
        return step

    def view(self) -> SessionView:
        """Does not take the lock: run_start holds it for minutes and would block polling.

        Reads one snapshot of the session; for "question"/"finished" the reported status is
        derived from that snapshot so status and content always agree.
        """
        snap = self.session.snapshot()
        status = self.status
        if status in ("question", "finished") and snap.current is not None:
            status = "finished" if isinstance(snap.current, Finished) else "question"
        question = None
        summary = None
        normalization = None
        resolution = None
        if status == "preparing":
            reported = self.session.normalization_progress  # tuple read: atomic snapshot
            if reported is not None:
                normalization = ProgressOut(done=reported[0], total=reported[1])
            looked_up = self.session.resolution_progress
            if looked_up is not None:
                resolution = ProgressOut(done=looked_up[0], total=looked_up[1])
        elif status == "question":
            step = snap.current
            if step is not None and not isinstance(step, Finished):
                question = question_out(step)
        elif status == "finished":
            step = snap.current
            if isinstance(step, Finished):
                counts = Counter(entry.list_status for entry in step.imported)
                summary = SummaryOut(
                    imported=len(step.imported),
                    by_status={kind: counts[kind] for kind in ListStatus},
                    rejected=[
                        RejectedOut(title=r.original_title, reason=r.reason) for r in step.rejected
                    ],
                )
        return SessionView(
            id=self.id,
            status=status,
            progress=ProgressOut(done=snap.position, total=snap.total),
            normalization=normalization,
            resolution=resolution,
            error=self.error,
            question=question,
            summary=summary,
            can_undo=status in ("question", "finished") and self.session.can_undo,
        )

    def _advance_with(self, action: Callable[[], Step]) -> None:
        """Run a session action; a failed background resolution turns the session into "failed"."""
        try:
            self._apply(action())
        except ResolutionError:
            self._fail_resolution()

    def _fail_resolution(self) -> None:
        logger.exception("Session %s: resolving titles failed", self.id)
        self.error = "Looking up titles on MAL failed; check the server logs"
        self.status = "failed"

    def _apply(self, step: Step) -> None:
        self.status = "finished" if isinstance(step, Finished) else "question"

    def _require(self, expected: SessionStatus) -> None:
        if self.status != expected:
            raise InvalidStateError(f"Operation not valid in state '{self.status}'")


class SessionRegistry:
    """Sessions of the app. Sessions not in memory are rebuilt lazily from the repository."""

    def __init__(
        self, services: SessionProvider, run_in_background: BackgroundRunner = start_daemon_thread
    ) -> None:
        self._services = services
        self._run_in_background = run_in_background
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = threading.Lock()

    def replace_services(self, services: SessionProvider) -> None:
        """Swap the session provider (used once, when the app gets configured while running)."""
        with self._lock:
            self._services = services

    def create(self, titles: Sequence[str]) -> ManagedSession:
        session_id = uuid.uuid4().hex
        session = self._services.new_session(session_id, titles)
        managed = ManagedSession(id=session_id, session=session)
        with self._lock:
            self._sessions[session_id] = managed
        return managed

    def get(self, session_id: str) -> ManagedSession:
        managed = self._sessions.get(session_id)
        if managed is not None:
            return managed
        with self._lock:
            # Another thread may have loaded it while this one waited for the lock.
            managed = self._sessions.get(session_id)
            if managed is not None:
                return managed
            managed = self._load(session_id)
            self._sessions[session_id] = managed
        self._run_in_background(managed.run_start)
        return managed

    def retry(self, session_id: str) -> ManagedSession:
        """Rebuild a failed session from the repository and start it again."""
        current = self.get(session_id)
        with self._lock:
            if self._sessions.get(session_id) is not current or current.status != "failed":
                raise InvalidStateError("Only a failed session can be retried")
            managed = self._load(session_id)
            self._sessions[session_id] = managed
        self._run_in_background(managed.run_start)
        return managed

    def list_recent(self, limit: int) -> list[SessionSummary]:
        return self._services.list_recent(limit)

    def _load(self, session_id: str) -> ManagedSession:
        session = self._services.restore_session(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return ManagedSession(id=session_id, session=session)
