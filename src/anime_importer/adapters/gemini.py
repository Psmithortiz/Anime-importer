import hashlib
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import replace

from google import genai
from google.genai import errors
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
)

from anime_importer.domain.models import NormalizedTitle
from anime_importer.ports import ChunkCallback, NormalizationError

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are an expert anime title normalizer.

    CRITICAL CONTEXT: The user has personally watched every title in this list.
    THEREFORE, EVERY ITEM IS A CONFIRMED ANIME. Your task is ONLY to normalize the spelling to the official japanese Romaji title used in MyAnimeList.

    For each input title, return a JSON object:
    - "n": input number (integer).
    - "romaji": official romaji title (string).
    - "is_anime": ALWAYS true (since all inputs are confirmed by the user).
    - "ambiguous": true ONLY if the input could refer to different seasons or separate entries (e.g., "Naruto" vs "Naruto Shippuden").
    - "options": array of romaji/title candidates if ambiguous=true.

    STRICT RULES:
    1. NEVER return "is_anime": false.
    2. If a title has notes like "MANGA?", "S1 S2", or "Novela", ignore the note and normalize the main title.
    3. Use Google Search to find the exact japanese Romaji/Title string for titles you don't recognize.
    4. Output raw JSON array only.
    Now normalize these titles:

{numbered_titles}
"""


class BatchValidationError(Exception):
    pass


def cache_version(model: str) -> str:
    """Identifica modelo + prompt: si cambia alguno, el caché anterior deja de valer."""
    return hashlib.sha256(f"{model}\n{PROMPT_TEMPLATE}".encode()).hexdigest()[:12]


def parse_normalization_response(text: str | None, expected_count: int) -> list[NormalizedTitle]:
    if text is None or not text.strip():
        raise BatchValidationError("Respuesta vacía de Gemini")
    start = text.find("[")
    if start == -1:
        raise BatchValidationError("La respuesta no contiene una lista JSON")
    data, _ = json.JSONDecoder().raw_decode(text, start)
    if not isinstance(data, list):
        raise BatchValidationError("No es una lista")
    if len(data) != expected_count:
        raise BatchValidationError(
            f"Lista incompleta, esperados: {expected_count}, recibidos: {len(data)}"
        )
    expected = set(range(1, expected_count + 1))
    received = {item["n"] for item in data}
    if expected != received:
        raise BatchValidationError(f"Faltan: {expected - received}, sobran:{received - expected}")
    results = [
        NormalizedTitle(
            index=item["n"],
            romaji=item.get("romaji") or "",
            is_anime=item.get("is_anime", True),
            ambiguous=bool(item.get("ambiguous", False)),
            options=tuple(item.get("options") or ()),
        )
        for item in data
    ]
    return sorted(results, key=lambda t: t.index)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (errors.ServerError, json.JSONDecodeError, BatchValidationError)):
        return True
    return isinstance(exc, errors.ClientError) and exc.code == 429


def wait_seconds(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    attempt = retry_state.attempt_number
    if isinstance(exc, errors.ClientError) and exc.code == 429:
        return 30 * attempt
    if isinstance(exc, errors.ServerError):
        return 15 * 2 ** (attempt - 1)
    if isinstance(exc, BatchValidationError):
        return 2
    return 3 * 2 ** (attempt - 1)


class GeminiNormalizer:
    def __init__(
        self,
        client: genai.Client | None = None,
        model: str = "gemini-2.5-flash",
        chunk_size: int = 20,
        sleep_seconds: float = 13,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or genai.Client()
        self._model = model
        self._chunk_size = chunk_size
        self._sleep_seconds = sleep_seconds
        self._sleep = sleep

    def normalize(
        self, titles: Sequence[str], on_chunk: ChunkCallback | None = None
    ) -> list[NormalizedTitle]:
        size = self._chunk_size
        chunks = [titles[i : i + size] for i in range(0, len(titles), size)]
        results: list[NormalizedTitle] = []
        for number, chunk in enumerate(chunks, start=1):
            logger.info("Normalizando chunk %d/%d", number, len(chunks))
            offset = (number - 1) * size
            try:
                chunk_results = self._normalize_chunk(chunk)
            except (errors.APIError, json.JSONDecodeError, BatchValidationError, KeyError) as exc:
                raise NormalizationError(
                    f"Falló la normalización del chunk {number}/{len(chunks)}: {exc}"
                ) from exc
            if on_chunk is not None:
                on_chunk(chunk, chunk_results)
            results.extend(replace(t, index=t.index + offset) for t in chunk_results)
            if number < len(chunks):
                self._sleep(self._sleep_seconds)
        return results

    @retry(
        retry=retry_if_exception(is_retryable),
        stop=stop_after_attempt(4),
        wait=wait_seconds,
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _normalize_chunk(self, chunk: Sequence[str]) -> list[NormalizedTitle]:
        numbered_titles = "\n".join(f"{i}. {title}" for i, title in enumerate(chunk, start=1))
        prompt = PROMPT_TEMPLATE.format(numbered_titles=numbered_titles)
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config={"tools": [{"google_search": {}}], "temperature": 0.1},
        )
        return parse_normalization_response(response.text, len(chunk))
