import logging
import re
import time
from collections.abc import Callable

import requests
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from anime_importer.domain.models import AnimeCandidate
from anime_importer.ports import SearchError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.jikan.moe/v4"
_MAX_QUERY_LENGTH = 64
_UNSAFE_CHARS = re.compile(r"[^a-zA-Z0-9 ]")


def sanitize_query(query: str) -> str:
    return _UNSAFE_CHARS.sub("", query)[:_MAX_QUERY_LENGTH]


def parse_search_response(data: dict) -> list[AnimeCandidate]:
    candidates = []
    for item in data.get("data", []):
        images = item.get("images", {})
        formats = images.get("webp") or images.get("jpg") or {}
        image_url = formats.get("large_image_url") or formats.get("image_url")
        candidates.append(
            AnimeCandidate(mal_id=item["mal_id"], title=item["title"], image_url=image_url)
        )
    return candidates


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


class JikanSearcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        timeout: tuple[float, float] = (10, 120),
        min_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session or requests.Session()
        self._base_url = base_url
        self._timeout = timeout
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    def _throttle(self) -> None:
        if self._last_request is not None:
            elapsed = self._clock() - self._last_request
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        self._last_request = self._clock()

    @retry(
        retry=retry_if_exception(is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=3),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _search_with_retry(self, query: str) -> list[AnimeCandidate]:
        self._throttle()
        response = self._session.get(
            f"{self._base_url}/anime",
            params={"q": sanitize_query(query), "limit": 25},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return parse_search_response(response.json())

    def search(self, query: str) -> list[AnimeCandidate]:
        try:
            return self._search_with_retry(query)
        except requests.RequestException as exc:
            raise SearchError(str(exc)) from exc
