import re
import time
from collections.abc import Callable

import requests

from anime_importer.adapters.http import Throttle, http_retry
from anime_importer.domain.models import AnimeCandidate
from anime_importer.ports import SearchError

BASE_URL = "https://api.myanimelist.net/v2"
_MAX_QUERY_LENGTH = 64
_UNSAFE_CHARS = re.compile(r"[^a-zA-Z0-9 ]")


def sanitize_query(query: str) -> str:
    return _UNSAFE_CHARS.sub("", query)[:_MAX_QUERY_LENGTH].strip()


def parse_search_response(data: dict) -> list[AnimeCandidate]:
    candidates = []
    for item in data.get("data", []):
        node = item["node"]
        picture = node.get("main_picture") or {}
        alternatives = node.get("alternative_titles") or {}
        alternative_titles = tuple(
            title
            for title in (
                alternatives.get("en"),
                alternatives.get("ja"),
                *(alternatives.get("synonyms") or ()),
            )
            if title
        )
        candidates.append(
            AnimeCandidate(
                mal_id=node["id"],
                title=node["title"],
                image_url=picture.get("large") or picture.get("medium"),
                alternative_titles=alternative_titles,
            )
        )
    return candidates


class MalSearcher:
    """Búsqueda en la API oficial de MyAnimeList (v2)."""

    def __init__(
        self,
        client_id: str,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        timeout: tuple[float, float] = (10, 30),
        min_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers["X-MAL-CLIENT-ID"] = client_id
        self._base_url = base_url
        self._timeout = timeout
        self._throttle = Throttle(min_interval, clock=clock, sleep=sleep)

    def search(self, query: str) -> list[AnimeCandidate]:
        try:
            return self._search_with_retry(query)
        except requests.RequestException as exc:
            raise SearchError(str(exc)) from exc

    @http_retry
    def _search_with_retry(self, query: str) -> list[AnimeCandidate]:
        self._throttle.wait()
        response = self._session.get(
            f"{self._base_url}/anime",
            params={
                "q": sanitize_query(query),
                "limit": 100,
                "fields": "alternative_titles",
                "nsfw": "true",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        return parse_search_response(response.json())
