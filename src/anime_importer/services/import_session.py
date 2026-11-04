from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

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
from anime_importer.ports import AnimeSearcher, SearchError, TitleNormalizer


@dataclass(frozen=True, slots=True)
class NormalizationChoice:
    """The normalizer is unsure: the user picks among possible titles."""

    original_title: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateChoice:
    """The search gave no confident match: the user picks among candidates."""

    original_title: str
    query: str
    options: tuple[AnimeCandidate, ...]
    franchise: Franchise = field(default_factory=Franchise)
    preselected: frozenset[int] = frozenset()  # mal_ids marked in advance


@dataclass(frozen=True, slots=True)
class Finished:
    imported: tuple[ImportedAnime, ...]
    rejected: tuple[RejectedTitle, ...]


Step = NormalizationChoice | CandidateChoice | Finished

FranchiseFinder = Callable[[Sequence[int]], Franchise]


def _imported_from(candidate: AnimeCandidate) -> ImportedAnime:
    return ImportedAnime(
        mal_id=candidate.mal_id,
        title=candidate.title,
        list_status=suggest_list_status(candidate.airing_status),
    )


class ImportSession:
    """Orchestrate the import of a list. Pauses every time it needs the user."""

    def __init__(
        self,
        titles: Sequence[str],
        normalizer: TitleNormalizer,
        searcher: AnimeSearcher,
        franchise_finder: FranchiseFinder | None = None,
    ) -> None:
        self._titles = list(titles)
        if not self._titles:
            raise ValueError("The title list is empty")
        self._normalizer = normalizer
        self._searcher = searcher
        self._franchise_finder = franchise_finder
        self._normalized: dict[int, NormalizedTitle] = {}
        self._position = 0
        self._imported: list[ImportedAnime] = []
        self._rejected: list[RejectedTitle] = []
        self._current: Step | None = None
        self._normalization_progress: tuple[int, int] | None = None

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

    def _set_normalization_progress(self, done: int, total: int) -> None:
        self._normalization_progress = (done, total)

    def start(self) -> Step:
        """Normalize the whole list and advance to the first question.

        Raises NormalizationError if the normalizer fails.
        """
        if self._current is not None:
            raise RuntimeError("The session has already started")
        normalized = self._normalizer.normalize(
            self._titles, on_progress=self._set_normalization_progress
        )
        self._normalized = {t.index: t for t in normalized}
        return self._advance()

    def choose(self, option_number: int) -> Step:
        """Answer the current question by choosing option `option_number` (1-based)."""
        step = self._pending_question()
        if not 1 <= option_number <= len(step.options):
            raise ValueError(f"Option out of range: {option_number}")
        index = option_number - 1
        if isinstance(step, NormalizationChoice):
            question = self._search(step.original_title, step.options[index])
            if question is not None:
                self._current = question
                return question
        else:
            self._imported.append(_imported_from(step.options[index]))
        self._position += 1
        return self._advance()

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
        available = {candidate.mal_id: candidate for candidate in step.options}
        for entry in step.franchise.entries:
            available.setdefault(entry.candidate.mal_id, entry.candidate)
        ids = [mal_id for mal_id, _ in selections]
        if len(set(ids)) != len(ids):
            raise ValueError("Repeated selections")
        for mal_id in ids:
            if mal_id not in available:
                raise ValueError(f"Unknown MAL id for this question: {mal_id}")
        for mal_id, status in selections:
            chosen = available[mal_id]
            self._imported.append(
                ImportedAnime(mal_id=chosen.mal_id, title=chosen.title, list_status=status)
            )
        self._position += 1
        return self._advance()

    def discard(self) -> Step:
        """Discard the title of the current question."""
        step = self._pending_question()
        if isinstance(step, NormalizationChoice):
            reason = "Discarded in normalization menu"
        else:
            reason = f"Discarded in search menu (query: {step.query})"
        self._reject(step.original_title, reason)
        self._position += 1
        return self._advance()

    def _pending_question(self) -> NormalizationChoice | CandidateChoice:
        step = self.current
        if isinstance(step, Finished):
            raise RuntimeError("The import has already finished")  # noqa: TRY004
        return step

    def _advance(self) -> Step:
        while self._position < len(self._titles):
            original = self._titles[self._position]
            question = self._process(original, self._normalized.get(self._position + 1))
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

    def _process(
        self, original: str, data: NormalizedTitle | None
    ) -> NormalizationChoice | CandidateChoice | None:
        if data is None:
            self._reject(original, "No normalization data")
            return None
        if not data.is_anime:
            self._reject(original, "Not an anime (according to the normalizer)")
            return None
        if data.ambiguous:
            return NormalizationChoice(original_title=original, options=data.options)
        return self._search(original, data.romaji)

    def _search(self, original: str, query: str) -> CandidateChoice | None:
        try:
            candidates = self._searcher.search(query)
        except SearchError as exc:
            self._reject(original, f"Search error: {exc}")
            return None
        if not candidates:
            self._reject(original, f"No results (query: {query})")
            return None
        result = match_candidates(query, candidates)
        finder = self._franchise_finder
        if result.accepted is not None:
            accepted = result.accepted
            franchise = finder([accepted.mal_id]) if finder is not None else Franchise()
            if not franchise.entries and not franchise.truncated:
                self._imported.append(_imported_from(accepted))
                return None
            return CandidateChoice(
                original_title=original,
                query=query,
                options=(accepted,),
                franchise=franchise,
                preselected=frozenset({accepted.mal_id}),
            )
        franchise = (
            finder([c.mal_id for c in result.options]) if finder is not None else Franchise()
        )
        return CandidateChoice(
            original_title=original, query=query, options=result.options, franchise=franchise
        )

    def _reject(self, original: str, reason: str) -> None:
        self._rejected.append(RejectedTitle(original_title=original, reason=reason))
