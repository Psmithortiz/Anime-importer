import logging
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from anime_importer.api.schemas import (
    ProgressOut,
    RejectedOut,
    SessionStatus,
    SessionView,
    SummaryOut,
    question_out,
)
from anime_importer.domain.models import ListStatus
from anime_importer.domain.session import Finished, Step
from anime_importer.ports import NormalizationError
from anime_importer.services.import_session import ImportSession, ResolutionError

logger = logging.getLogger(__name__)

SessionFactory = Callable[[str, Sequence[str]], ImportSession]


class SessionNotFoundError(Exception):
    """No session exists with that id."""


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
    def __init__(self, factory: SessionFactory) -> None:
        self._factory = factory
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = threading.Lock()

    def create(self, titles: Sequence[str]) -> ManagedSession:
        session_id = uuid.uuid4().hex
        session = self._factory(session_id, titles)
        managed = ManagedSession(id=session_id, session=session)
        with self._lock:
            self._sessions[managed.id] = managed
        return managed

    def get(self, session_id: str) -> ManagedSession:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFoundError(session_id) from None
