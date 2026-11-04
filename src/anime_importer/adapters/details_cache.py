import json
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anime_importer.adapters.json_files import write_json_atomic
from anime_importer.domain.models import (
    AiringStatus,
    AnimeCandidate,
    AnimeDetails,
    MediaType,
    Relation,
    RelationType,
)
from anime_importer.ports import AnimeDetailsProvider

logger = logging.getLogger(__name__)


def _to_dict(details: AnimeDetails) -> dict[str, Any]:
    candidate = details.candidate
    return {
        "candidate": {
            "mal_id": candidate.mal_id,
            "title": candidate.title,
            "image_url": candidate.image_url,
            "alternative_titles": list(candidate.alternative_titles),
            "media_type": candidate.media_type.value if candidate.media_type else None,
            "year": candidate.year,
            "episodes": candidate.episodes,
            "airing_status": candidate.airing_status.value,
        },
        "relations": [
            {"mal_id": relation.mal_id, "relation_type": relation.relation_type.value}
            for relation in details.relations
        ],
    }


def _from_dict(data: dict[str, Any]) -> AnimeDetails:
    raw = data["candidate"]
    media_type = raw["media_type"]
    candidate = AnimeCandidate(
        mal_id=raw["mal_id"],
        title=raw["title"],
        image_url=raw["image_url"],
        alternative_titles=tuple(raw["alternative_titles"]),
        media_type=MediaType(media_type) if media_type is not None else None,
        year=raw["year"],
        episodes=raw["episodes"],
        airing_status=AiringStatus(raw["airing_status"]),
    )
    relations = tuple(
        Relation(item["mal_id"], RelationType(item["relation_type"])) for item in data["relations"]
    )
    return AnimeDetails(candidate=candidate, relations=relations)


class CachingDetailsProvider:
    """Cache anime details in a JSON file {mal_id: {fetched_at, details}} with a TTL."""

    def __init__(
        self,
        inner: AnimeDetailsProvider,
        path: Path,
        ttl_seconds: float = 7 * 24 * 3600,
        clock: Callable[[], float] = time.time,  # wall clock: the timestamp is persisted
    ) -> None:
        self._inner = inner
        self._path = path
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()

    def get_details(self, mal_id: int) -> AnimeDetails:
        with self._lock:
            entry = self._read().get(str(mal_id))
        if entry is not None:
            try:
                if self._clock() - entry["fetched_at"] < self._ttl_seconds:
                    return _from_dict(entry["details"])
            except (KeyError, TypeError, ValueError):
                logger.warning("Invalid details cache entry for %s, refetching", mal_id)

        details = self._inner.get_details(mal_id)
        with self._lock:
            entries = self._read()
            entries[str(mal_id)] = {"fetched_at": self._clock(), "details": _to_dict(details)}
            write_json_atomic(self._path, entries)
        return details

    def _read(self) -> dict[str, Any]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            logger.warning("Corrupt details cache, ignoring it: %s", self._path)
            return {}
        return data
