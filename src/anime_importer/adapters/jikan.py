import re
import time
from collections.abc import Callable

import requests

from anime_importer.adapters.http import Throttle, http_retry
from anime_importer.domain.models import AnimeCandidate
from anime_importer.ports import SearchError

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
        self._throttle = Throttle(min_interval, clock=clock, sleep=sleep)

    @http_retry
    def _search_with_retry(self, query: str) -> list[AnimeCandidate]:
        self._throttle.wait()
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
