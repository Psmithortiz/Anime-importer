import threading
from collections.abc import Callable, Sequence
from typing import Any, Self

from anime_importer.domain.matching import match_candidates
from anime_importer.domain.models import (
    AnimeCandidate,
    Franchise,
    ImportedAnime,
    ListStatus,
    NormalizedTitle,
    RejectedTitle,
    suggest_list_status,
)
from anime_importer.domain.session import (
    Ask,
    CandidateChoice,
    Decision,
    Discard,
    Finished,
    Imported,
    NormalizationChoice,
    PickCandidates,
    PickQuery,
    Rejected,
    Resolution,
    Step,
    StoredSession,
)
from anime_importer.ports import (
    AnimeSearcher,
    PersistenceError,
    SearchError,
    SessionRepository,
    TitleNormalizer,
)


class ResolutionError(Exception):
    """The background resolution of the titles failed unexpectedly."""


FranchiseFinder = Callable[[Sequence[int]], Franchise]
BackgroundRunner = Callable[[Callable[[], None]], None]


_MISMATCH = "stored decisions do not match the session"


def _available_candidates(step: CandidateChoice) -> dict[int, AnimeCandidate]:
    """Options of the question plus its franchise, by mal_id (options win)."""
    available = {candidate.mal_id: candidate for candidate in step.options}
    for entry in step.franchise.entries:
        available.setdefault(entry.candidate.mal_id, entry.candidate)
    return available


def _imported_from(candidate: AnimeCandidate) -> ImportedAnime:
    return ImportedAnime(
        mal_id=candidate.mal_id,
        title=candidate.title,
        list_status=suggest_list_status(candidate.airing_status),
    )


def _same_query(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _start_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


class ImportSession:
    """Orchestrate the import of a list. Pauses every time it needs the user.

    A background worker resolves the titles ahead of the user (search + franchise lookup) and
    appends the results, in order, to a list. The session only consumes that list: advancing
    never calls the searcher or the finder.

    Every fact is saved to the repository BEFORE it is applied: resolutions (worker), search
    answers and user decisions. The consumer state (position, imported, rejected, current step)
    is a pure function of the stored resolutions, answers and decisions, so a session can be
    rebuilt from a StoredSession and its last decision can be undone.
    """

    def __init__(
        self,
        stored: StoredSession,
        *,
        normalizer: TitleNormalizer,
        searcher: AnimeSearcher,
        repository: SessionRepository,
        franchise_finder: FranchiseFinder | None = None,
        resolution_buffer: int = 20,
        run_in_background: BackgroundRunner = _start_thread,
    ) -> None:
        self._id = stored.id
        self._titles = list(stored.titles)
        self._normalizer = normalizer
        self._searcher = searcher
        self._repository = repository
        self._franchise_finder = franchise_finder
        self._resolution_buffer = resolution_buffer
        self._run_in_background = run_in_background
        self._normalized: dict[int, NormalizedTitle] = (
            {t.index: t for t in stored.normalized} if stored.normalized else {}
        )
        self._answers: dict[tuple[int, str], Resolution] = dict(stored.answers)
        self._decisions: list[tuple[int, Decision]] = list(stored.decisions)
        self._position = 0
        self._imported: list[ImportedAnime] = []
        self._rejected: list[RejectedTitle] = []
        self._current: Step | None = None
        self._normalization_progress: tuple[int, int] | None = None
        # Shared with the worker: only the worker appends to _resolutions.
        self._cond = threading.Condition()
        self._resolutions: list[Resolution] = list(stored.resolutions)
        self._worker_error: BaseException | None = None
        self._worker_started = False

    @classmethod
    def create(
        cls,
        session_id: str,
        titles: Sequence[str],
        *,
        repository: SessionRepository,
        **deps: Any,
    ) -> Self:
        """Register a new session in the repository and build it."""
        if not titles:
            raise ValueError("The title list is empty")
        repository.create(session_id, titles)
        stored = StoredSession(session_id, tuple(titles), None, (), {}, ())
        return cls(stored, repository=repository, **deps)

    @property
    def id(self) -> str:
        return self._id

    @property
    def current(self) -> Step:
        if self._current is None:
            raise RuntimeError("The session has not started: call start()")
        return self._current

    @property
    def progress(self) -> tuple[int, int]:
        """(resolved titles, total)."""
        return self._position, len(self._titles)

    @property
    def normalization_progress(self) -> tuple[int, int] | None:
        """(normalized titles, total) reported by the normalizer, or None if it has not reported."""
        return self._normalization_progress

    @property
    def resolution_progress(self) -> tuple[int, int] | None:
        """(titles looked up on MAL, total), or None until the worker has been launched."""
        with self._cond:
            if not self._worker_started:
                return None
            return len(self._resolutions), len(self._titles)

    def _set_normalization_progress(self, done: int, total: int) -> None:
        self._normalization_progress = (done, total)

    def start(self) -> Step:
        """Normalize the whole list (unless it is already stored), start resolving the missing
        titles in the background, wait for a buffer of resolutions and replay the stored
        decisions up to the first pending question.

        Raises NormalizationError if the normalizer fails, ResolutionError if the background
        resolution fails before the first question, and PersistenceError if the repository
        fails or the stored decisions do not match the session.
        """
        if self._current is not None:
            raise RuntimeError("The session has already started")
        if not self._normalized:
            normalized = self._normalizer.normalize(
                self._titles, on_progress=self._set_normalization_progress
            )
            self._repository.save_normalization(self._id, normalized)
            self._normalized = {t.index: t for t in normalized}
        with self._cond:
            self._worker_started = True
            missing = len(self._resolutions) < len(self._titles)
        if missing:
            self._run_in_background(self._work)
        needed = min(self._resolution_buffer, len(self._titles))
        with self._cond:
            self._cond.wait_for(
                lambda: len(self._resolutions) >= needed or self._worker_error is not None
            )
        return self._replay()

    def choose(self, option_number: int) -> Step:
        """Answer the current question by choosing option `option_number` (1-based)."""
        step = self._pending_question()
        if not 1 <= option_number <= len(step.options):
            raise ValueError(f"Option out of range: {option_number}")
        index = option_number - 1
        decision: Decision
        if isinstance(step, NormalizationChoice):
            query = step.options[index]
            key = (self._position, query)
            if key not in self._answers:
                # The user changed the query: resolve it now, in the caller's thread.
                resolution = self._resolve_query(step.original_title, query)
                self._repository.save_answer(self._id, self._position, query, resolution)
                self._answers[key] = resolution
            decision = PickQuery(query)
        else:
            chosen = step.options[index]
            decision = PickCandidates(((chosen.mal_id, suggest_list_status(chosen.airing_status)),))
        return self._record(decision)

    def choose_many(self, selections: Sequence[tuple[int, ListStatus]]) -> Step:
        """Import several anime of the current question, each with its list status.

        Selections are (mal_id, status) pairs; a mal_id may belong to the options or to the
        franchise. Only valid for CandidateChoice. On a ValueError the session does not change.
        """
        step = self._pending_question()
        if not isinstance(step, CandidateChoice):
            raise ValueError("choose_many only applies to candidate questions")  # noqa: TRY004
        if not selections:
            raise ValueError("You must choose at least one option")
        available = _available_candidates(step)
        ids = [mal_id for mal_id, _ in selections]
        if len(set(ids)) != len(ids):
            raise ValueError("Repeated selections")
        for mal_id in ids:
            if mal_id not in available:
                raise ValueError(f"Unknown MAL id for this question: {mal_id}")
        return self._record(
            PickCandidates(tuple((mal_id, status) for mal_id, status in selections))
        )

    def discard(self) -> Step:
        """Discard the title of the current question."""
        self._pending_question()
        return self._record(Discard())

    def undo(self) -> Step:
        """Undo the last decision and return to the question it answered.

        Titles that resolved on their own have no decision: they are imported again when the
        stored decisions are replayed. Works from a finished session too. Resolutions and
        answers are kept, so answering the same normalization option again never searches again.
        """
        _ = self.current  # must have started
        if not self._decisions:
            raise ValueError("Nothing to undo")
        if not self._repository.remove_last_decision(self._id):
            raise PersistenceError(_MISMATCH)
        self._decisions.pop()
        return self._replay()

    def _pending_question(self) -> NormalizationChoice | CandidateChoice:
        step = self.current
        if isinstance(step, Finished):
            raise RuntimeError("The import has already finished")  # noqa: TRY004
        return step

    def _record(self, decision: Decision) -> Step:
        """Persist a decision, then apply it. Nothing is applied if it cannot be saved."""
        position = self._position
        self._repository.add_decision(self._id, position, decision)
        self._decisions.append((position, decision))
        return self._apply_decision(decision)

    # ------------------------------------------------------------------ replay

    def _replay(self) -> Step:
        """Rebuild the consumer state from the resolutions and the stored decisions."""
        self._position = 0
        self._imported = []
        self._rejected = []
        self._current = None
        step = self._advance()
        for position, decision in self._decisions:
            if isinstance(step, Finished) or self._position != position:
                raise PersistenceError(_MISMATCH)
            step = self._apply_decision(decision)
        return step

    def _apply_decision(self, decision: Decision) -> Step:
        """Apply an already persisted and validated decision.

        Never touches the repository nor the searcher.
        """
        step = self._current
        if step is None or isinstance(step, Finished):
            raise PersistenceError(_MISMATCH)
        match decision:
            case PickQuery(query):
                resolution = self._answers.get((self._position, query))
                if not isinstance(step, NormalizationChoice) or resolution is None:
                    raise PersistenceError(_MISMATCH)
                question = self._apply(resolution, step.original_title)
                if question is not None:
                    self._current = question
                    return question
            case PickCandidates(selections):
                if not isinstance(step, CandidateChoice):
                    raise PersistenceError(_MISMATCH)
                available = _available_candidates(step)
                if any(mal_id not in available for mal_id, _ in selections):
                    raise PersistenceError(_MISMATCH)
                for mal_id, status in selections:
                    chosen = available[mal_id]
                    self._imported.append(
                        ImportedAnime(mal_id=chosen.mal_id, title=chosen.title, list_status=status)
                    )
            case Discard():
                if isinstance(step, NormalizationChoice):
                    reason = "Discarded in normalization menu"
                else:
                    reason = f"Discarded in search menu (query: {step.query})"
                self._reject(step.original_title, reason)
        self._position += 1
        return self._advance()

    # ------------------------------------------------------------------ worker side

    def _work(self) -> None:
        """Resolve the missing titles in order. Runs in the background.

        It never mutates the consumer state. Each resolution is saved before it is published.
        """
        try:
            for position in range(len(self._resolutions), len(self._titles)):
                resolution = self._resolve(
                    self._titles[position], self._normalized.get(position + 1)
                )
                self._repository.add_resolution(self._id, position, resolution)
                with self._cond:
                    self._resolutions.append(resolution)
                    self._cond.notify_all()
        except BaseException as exc:  # noqa: BLE001 - a dying worker must wake up the waiters
            with self._cond:
                self._worker_error = exc
                self._cond.notify_all()

    def _resolve(self, original: str, data: NormalizedTitle | None) -> Resolution:
        if data is None:
            return Rejected("No normalization data")
        if not data.is_anime:
            return Rejected("Not an anime (according to the normalizer)")
        if data.ambiguous:
            options = tuple(data.options)
            original_option = None
            if not any(_same_query(original, option) for option in options):
                options = (*options, original)  # the user's own line is always an option
                original_option = len(options)
            return Ask(
                NormalizationChoice(
                    original_title=original, options=options, original_option=original_option
                )
            )
        return self._resolve_query(original, data.romaji)

    def _resolve_query(self, original: str, query: str) -> Resolution:
        try:
            candidates = self._searcher.search(query)
        except SearchError as exc:
            return Rejected(f"Search error: {exc}")
        used_fallback = False
        if not candidates:
            if _same_query(original, query):
                return Rejected(f"No results (query: {query})")
            # The normalized title found nothing: try the user's original line.
            try:
                candidates = self._searcher.search(original)
            except SearchError as exc:
                return Rejected(f"Search error: {exc}")
            if not candidates:
                return Rejected(f"No results (queries: {query!r}, {original!r})")
            query = original
            used_fallback = True
        result = match_candidates(query, candidates)
        finder = self._franchise_finder
        if result.accepted is not None:
            accepted = result.accepted
            franchise = finder([accepted.mal_id]) if finder is not None else Franchise()
            if not franchise.entries and not franchise.truncated:
                return Imported(_imported_from(accepted))
            return Ask(
                CandidateChoice(
                    original_title=original,
                    query=query,
                    options=(accepted,),
                    franchise=franchise,
                    preselected=frozenset({accepted.mal_id}),
                    used_fallback=used_fallback,
                )
            )
        franchise = (
            finder([c.mal_id for c in result.options]) if finder is not None else Franchise()
        )
        return Ask(
            CandidateChoice(
                original_title=original,
                query=query,
                options=result.options,
                franchise=franchise,
                used_fallback=used_fallback,
            )
        )

    # ------------------------------------------------------------------ consumer side

    def _advance(self) -> Step:
        """Consume resolutions in order until a question or the end. Never searches."""
        while self._position < len(self._titles):
            resolution = self._wait_for_resolution(self._position)
            question = self._apply(resolution, self._titles[self._position])
            if question is not None:
                self._current = question
                return question
            self._position += 1
        # If the same anime was imported several times, the last one wins.
        unique = {entry.mal_id: entry for entry in self._imported}
        self._current = Finished(
            imported=tuple(unique.values()),
            rejected=tuple(sorted(self._rejected, key=lambda r: r.reason)),
        )
        return self._current

    def _wait_for_resolution(self, index: int) -> Resolution:
        with self._cond:
            self._cond.wait_for(
                lambda: len(self._resolutions) > index or self._worker_error is not None
            )
            if len(self._resolutions) > index:
                return self._resolutions[index]
            raise ResolutionError(
                f"Resolving title {index + 1} of {len(self._titles)} failed"
            ) from self._worker_error

    def _apply(
        self, resolution: Resolution, original: str
    ) -> NormalizationChoice | CandidateChoice | None:
        """Record a resolution; return the question if it needs the user."""
        match resolution:
            case Imported(entry):
                self._imported.append(entry)
            case Rejected(reason):
                self._reject(original, reason)
            case Ask(question):
                return question
        return None

    def _reject(self, original: str, reason: str) -> None:
        self._rejected.append(RejectedTitle(original_title=original, reason=reason))
