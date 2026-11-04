import re
import time
from collections.abc import Callable

import requests

from anime_importer.adapters.http import Throttle, http_retry
from anime_importer.domain.models import (
    AiringStatus,
    AnimeCandidate,
    AnimeDetails,
    MediaType,
    Relation,
    RelationType,
)
from anime_importer.ports import DetailsError, SearchError

BASE_URL = "https://api.myanimelist.net/v2"
_MAX_QUERY_LENGTH = 64
_UNSAFE_CHARS = re.compile(r"[^a-zA-Z0-9 ]")


def sanitize_query(query: str) -> str:
    spaced = _UNSAFE_CHARS.sub(" ", query)
    collapsed = " ".join(spaced.split())
    return collapsed[:_MAX_QUERY_LENGTH].strip()


_MEDIA_TYPES = {
    "tv": MediaType.TV,
    "movie": MediaType.MOVIE,
    "ova": MediaType.OVA,
    "ona": MediaType.ONA,
    "special": MediaType.SPECIAL,
    "tv_special": MediaType.SPECIAL,
    "music": MediaType.MUSIC,
}
_AIRING_STATUSES = {
    "finished_airing": AiringStatus.FINISHED,
    "currently_airing": AiringStatus.AIRING,
    "not_yet_aired": AiringStatus.NOT_YET_AIRED,
}


def parse_media_type(value: str | None) -> MediaType:
    return _MEDIA_TYPES.get(value or "", MediaType.OTHER)


def parse_airing_status(value: str | None) -> AiringStatus:
    return _AIRING_STATUSES.get(value or "", AiringStatus.UNKNOWN)


_RELATION_TYPES = {relation.value: relation for relation in RelationType}


def parse_relation_type(value: str | None) -> RelationType:
    return _RELATION_TYPES.get(value or "", RelationType.OTHER)


def parse_anime_node(node: dict) -> AnimeCandidate:
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
    return AnimeCandidate(
        mal_id=node["id"],
        title=node["title"],
        image_url=picture.get("large") or picture.get("medium"),
        alternative_titles=alternative_titles,
        media_type=parse_media_type(node.get("media_type")),
        year=(node.get("start_season") or {}).get("year"),
        episodes=node.get("num_episodes") or None,
        airing_status=parse_airing_status(node.get("status")),
    )


def parse_search_response(data: dict) -> list[AnimeCandidate]:
    return [parse_anime_node(item["node"]) for item in data.get("data", [])]


def parse_details_response(data: dict) -> AnimeDetails:
    relations = tuple(
        Relation(item["node"]["id"], parse_relation_type(item.get("relation_type")))
        for item in data.get("related_anime") or []
    )
    return AnimeDetails(candidate=parse_anime_node(data), relations=relations)


class MalSearcher:
    """Search on the official MyAnimeList API (v2)."""

    def __init__(
        self,
        client_id: str,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        timeout: tuple[float, float] = (10, 30),
        min_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        throttle: Throttle | None = None,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers["X-MAL-CLIENT-ID"] = client_id
        self._base_url = base_url
        self._timeout = timeout
        self._throttle = (
            throttle if throttle is not None else Throttle(min_interval, clock=clock, sleep=sleep)
        )

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
                "fields": "alternative_titles,media_type,start_season,num_episodes,status",
                "nsfw": "true",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        return parse_search_response(response.json())


class MalDetailsProvider:
    """Fetch one anime with its relations from the official MyAnimeList API (v2)."""

    def __init__(
        self,
        client_id: str,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        timeout: tuple[float, float] = (10, 30),
        throttle: Throttle | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers["X-MAL-CLIENT-ID"] = client_id
        self._base_url = base_url
        self._timeout = timeout
        self._throttle = (
            throttle if throttle is not None else Throttle(1.0, clock=clock, sleep=sleep)
        )

    def get_details(self, mal_id: int) -> AnimeDetails:
        try:
            return self._get_with_retry(mal_id)
        except requests.RequestException as exc:
            raise DetailsError(str(exc)) from exc

    @http_retry
    def _get_with_retry(self, mal_id: int) -> AnimeDetails:
        self._throttle.wait()
        response = self._session.get(
            f"{self._base_url}/anime/{mal_id}",
            params={
                "fields": (
                    "alternative_titles,media_type,start_season,num_episodes,status,related_anime"
                ),
                "nsfw": "true",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        return parse_details_response(response.json())
