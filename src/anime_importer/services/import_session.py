from collections.abc import Sequence
from dataclasses import dataclass

from anime_importer.domain.matching import match_candidates
from anime_importer.domain.models import (
    AnimeCandidate,
    ImportedAnime,
    NormalizedTitle,
    RejectedTitle,
)
from anime_importer.ports import AnimeSearcher, SearchError, TitleNormalizer


@dataclass(frozen=True, slots=True)
class NormalizationChoice:
    """El normalizador no está seguro: el usuario elige entre títulos posibles."""

    original_title: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateChoice:
    """La búsqueda no dio un match seguro: el usuario elige entre candidatos."""

    original_title: str
    query: str
    options: tuple[AnimeCandidate, ...]


@dataclass(frozen=True, slots=True)
class Finished:
    imported: tuple[ImportedAnime, ...]
    rejected: tuple[RejectedTitle, ...]


Step = NormalizationChoice | CandidateChoice | Finished


class ImportSession:
    """Orquesta la importación de una lista. Se pausa cada vez que necesita al usuario."""

    def __init__(
        self,
        titles: Sequence[str],
        normalizer: TitleNormalizer,
        searcher: AnimeSearcher,
    ) -> None:
        self._titles = list(titles)
        self._normalizer = normalizer
        self._searcher = searcher
        self._normalized: dict[int, NormalizedTitle] = {}
        self._position = 0
        self._imported: list[ImportedAnime] = []
        self._rejected: list[RejectedTitle] = []
        self._current: Step | None = None

    @property
    def current(self) -> Step:
        if self._current is None:
            raise RuntimeError("La sesión no ha comenzado: llama a start()")
        return self._current

    def start(self) -> Step:
        """Normaliza la lista completa y avanza hasta la primera pregunta.

        Lanza NormalizationError si el normalizador falla.
        """
        if self._current is not None:
            raise RuntimeError("La sesión ya comenzó")
        normalized = self._normalizer.normalize(self._titles)
        self._normalized = {t.index: t for t in normalized}
        return self._advance()

    def choose(self, option_number: int) -> Step:
        """Responde la pregunta actual eligiendo la opción `option_number` (1-based)."""
        step = self._pending_question()
        if not 1 <= option_number <= len(step.options):
            raise ValueError(f"Opción fuera de rango: {option_number}")
        index = option_number - 1
        if isinstance(step, NormalizationChoice):
            question = self._search(step.original_title, step.options[index])
            if question is not None:
                self._current = question
                return question
        else:
            chosen = step.options[index]
            self._imported.append(ImportedAnime(mal_id=chosen.mal_id, title=chosen.title))
        self._position += 1
        return self._advance()

    def discard(self) -> Step:
        """Descarta el título de la pregunta actual."""
        step = self._pending_question()
        if isinstance(step, NormalizationChoice):
            reason = "Descartado en menú de normalización"
        else:
            reason = f"Descartado en menú de búsqueda (query: {step.query})"
        self._reject(step.original_title, reason)
        self._position += 1
        return self._advance()

    def _pending_question(self) -> NormalizationChoice | CandidateChoice:
        step = self.current
        if isinstance(step, Finished):
            raise RuntimeError("La importación ya terminó")  # noqa: TRY004
        return step

    def _advance(self) -> Step:
        while self._position < len(self._titles):
            original = self._titles[self._position]
            question = self._process(original, self._normalized.get(self._position + 1))
            if question is not None:
                self._current = question
                return question
            self._position += 1
        self._current = Finished(
            imported=tuple(self._imported),
            rejected=tuple(sorted(self._rejected, key=lambda r: r.reason)),
        )
        return self._current

    def _process(
        self, original: str, data: NormalizedTitle | None
    ) -> NormalizationChoice | CandidateChoice | None:
        if data is None:
            self._reject(original, "Sin datos de normalización")
            return None
        if not data.is_anime:
            self._reject(original, "No es un anime (según el normalizador)")
            return None
        if data.ambiguous:
            return NormalizationChoice(original_title=original, options=data.options)
        return self._search(original, data.romaji)

    def _search(self, original: str, query: str) -> CandidateChoice | None:
        try:
            candidates = self._searcher.search(query)
        except SearchError as exc:
            self._reject(original, f"Error de búsqueda: {exc}")
            return None
        if not candidates:
            self._reject(original, f"Sin resultados (query: {query})")
            return None
        result = match_candidates(query, candidates)
        if result.accepted is not None:
            accepted = result.accepted
            self._imported.append(ImportedAnime(mal_id=accepted.mal_id, title=accepted.title))
            return None
        return CandidateChoice(original_title=original, query=query, options=result.options)

    def _reject(self, original: str, reason: str) -> None:
        self._rejected.append(RejectedTitle(original_title=original, reason=reason))
