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
from anime_importer.ports import NormalizationError
from anime_importer.services.import_session import Finished, ImportSession, Step

logger = logging.getLogger(__name__)

SessionFactory = Callable[[Sequence[str]], ImportSession]


class SessionNotFoundError(Exception):
    """No existe una sesión con ese id."""


class InvalidStateError(Exception):
    """La operación no es válida en el estado actual de la sesión."""


@dataclass
class ManagedSession:
    id: str
    session: ImportSession
    status: SessionStatus = "normalizing"
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def run_start(self) -> None:
        """Se ejecuta en segundo plano. Nunca debe dejar el estado en "normalizing"."""
        with self.lock:
            try:
                self._apply(self.session.start())
            except NormalizationError as exc:
                self.error = str(exc)
                self.status = "failed"
            except Exception:
                logger.exception("Falló la sesión %s", self.id)
                self.error = "Error interno al procesar la lista"
                self.status = "failed"

    def choose(self, option: int) -> None:
        with self.lock:
            self._require("question")
            self._apply(self.session.choose(option))

    def choose_many(self, selections: Sequence[tuple[int, ListStatus]]) -> None:
        with self.lock:
            self._require("question")
            self._apply(self.session.choose_many(selections))

    def discard(self) -> None:
        with self.lock:
            self._require("question")
            self._apply(self.session.discard())

    def finished(self) -> Finished:
        self._require("finished")
        step = self.session.current
        assert isinstance(step, Finished)
        return step

    def view(self) -> SessionView:
        """No toma el lock: run_start lo retiene durante minutos y bloquearía el polling."""
        status = self.status
        done, total = self.session.progress
        question = None
        summary = None
        if status == "question":
            step = self.session.current
            if not isinstance(step, Finished):
                question = question_out(step)
        elif status == "finished":
            step = self.session.current
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
            progress=ProgressOut(done=done, total=total),
            error=self.error,
            question=question,
            summary=summary,
        )

    def _apply(self, step: Step) -> None:
        self.status = "finished" if isinstance(step, Finished) else "question"

    def _require(self, expected: SessionStatus) -> None:
        if self.status != expected:
            raise InvalidStateError(f"Operación no válida en estado '{self.status}'")


class SessionRegistry:
    def __init__(self, factory: SessionFactory) -> None:
        self._factory = factory
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = threading.Lock()

    def create(self, titles: Sequence[str]) -> ManagedSession:
        session = self._factory(titles)
        managed = ManagedSession(id=uuid.uuid4().hex, session=session)
        with self._lock:
            self._sessions[managed.id] = managed
        return managed

    def get(self, session_id: str) -> ManagedSession:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFoundError(session_id) from None
