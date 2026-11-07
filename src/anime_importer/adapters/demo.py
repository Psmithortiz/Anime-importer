"""Demo mode: record real Gemini/MAL responses once, replay them without API keys."""

import json
import os
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Self

from anime_importer.domain.models import (
    AiringStatus,
    AnimeCandidate,
    AnimeDetails,
    MediaType,
    NormalizedTitle,
    Relation,
    RelationType,
)
from anime_importer.ports import (
    AnimeDetailsProvider,
    AnimeSearcher,
    DetailsError,
    ProgressCallback,
    TitleNormalizer,
)

# ---------------------------------------------------------------- serialization

# Intentionally independent from details_cache.py: the demo recording and the details cache are
# separate file formats, and changing one must not invalidate the other.


def normalized_to_dict(title: NormalizedTitle) -> dict[str, Any]:
    """The index is not stored: it depends on the position in the list being processed."""
    return {
        "romaji": title.romaji,
        "is_anime": title.is_anime,
        "ambiguous": title.ambiguous,
        "options": list(title.options),
    }


def normalized_from_dict(data: dict[str, Any], index: int = 0) -> NormalizedTitle:
    return NormalizedTitle(
        index=index,
        romaji=data["romaji"],
        is_anime=data["is_anime"],
        ambiguous=data["ambiguous"],
        options=tuple(data["options"]),
    )


def candidate_to_dict(candidate: AnimeCandidate) -> dict[str, Any]:
    return {
        "mal_id": candidate.mal_id,
        "title": candidate.title,
        "image_url": candidate.image_url,
        "alternative_titles": list(candidate.alternative_titles),
        "media_type": candidate.media_type.value if candidate.media_type else None,
        "year": candidate.year,
        "episodes": candidate.episodes,
        "airing_status": candidate.airing_status.value,
    }


def candidate_from_dict(data: dict[str, Any]) -> AnimeCandidate:
    media_type = data["media_type"]
    return AnimeCandidate(
        mal_id=data["mal_id"],
        title=data["title"],
        image_url=data["image_url"],
        alternative_titles=tuple(data["alternative_titles"]),
        media_type=MediaType(media_type) if media_type is not None else None,
        year=data["year"],
        episodes=data["episodes"],
        airing_status=AiringStatus(data["airing_status"]),
    )


def details_to_dict(details: AnimeDetails) -> dict[str, Any]:
    return {
        "candidate": candidate_to_dict(details.candidate),
        "relations": [
            {"mal_id": relation.mal_id, "relation_type": relation.relation_type.value}
            for relation in details.relations
        ],
    }


def details_from_dict(data: dict[str, Any]) -> AnimeDetails:
    return AnimeDetails(
        candidate=candidate_from_dict(data["candidate"]),
        relations=tuple(
            Relation(mal_id=item["mal_id"], relation_type=RelationType(item["relation_type"]))
            for item in data["relations"]
        ),
    )


# ---------------------------------------------------------------- recording


class DemoRecording:
    """Recorded responses: normalizations by original line, searches by exact query, details by id.

    Writes are protected by a lock: the recording script writes from the session's worker thread
    and from the main thread. Recorded normalizations carry index 0 (they are re-indexed on replay).
    """

    def __init__(self) -> None:
        self.normalizations: dict[str, NormalizedTitle] = {}
        self.searches: dict[str, list[AnimeCandidate]] = {}
        self.details: dict[int, AnimeDetails] = {}
        self._lock = threading.Lock()

    def record_normalization(self, line: str, title: NormalizedTitle) -> None:
        with self._lock:
            self.normalizations[line] = title

    def record_search(self, query: str, candidates: Sequence[AnimeCandidate]) -> None:
        with self._lock:
            self.searches[query] = list(candidates)

    def record_details(self, mal_id: int, details: AnimeDetails) -> None:
        # Stored under the requested id because the replay looks it up by that id, and MAL may
        # answer with a different one (merged entries).
        with self._lock:
            self.details[mal_id] = details

    @classmethod
    def load(cls, path: Path) -> Self:
        data = json.loads(path.read_text(encoding="utf-8"))
        recording = cls()
        recording.normalizations = {
            line: normalized_from_dict(item) for line, item in data["normalizations"].items()
        }
        recording.searches = {
            query: [candidate_from_dict(item) for item in items]
            for query, items in data["searches"].items()
        }
        recording.details = {
            int(mal_id): details_from_dict(item) for mal_id, item in data["details"].items()
        }
        return recording

    def save(self, path: Path) -> None:
        with self._lock:
            payload = {
                "normalizations": {
                    line: normalized_to_dict(title) for line, title in self.normalizations.items()
                },
                "searches": {
                    query: [candidate_to_dict(c) for c in candidates]
                    for query, candidates in self.searches.items()
                },
                "details": {
                    str(mal_id): details_to_dict(details)
                    for mal_id, details in self.details.items()
                },
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        tmp.write_text(text + "\n", encoding="utf-8")
        os.replace(tmp, path)


# ---------------------------------------------------------------- replay adapters


class ReplayNormalizer:
    """Replays recorded normalizations, simulating chunked progress."""

    def __init__(
        self,
        recording: DemoRecording,
        delay: float,
        sleep: Callable[[float], None] = time.sleep,
        chunk_size: int = 20,
    ) -> None:
        self._recording = recording
        self._delay = delay
        self._sleep = sleep
        self._chunk_size = chunk_size

    def normalize(
        self, titles: Sequence[str], on_progress: ProgressCallback | None = None
    ) -> list[NormalizedTitle]:
        total = len(titles)
        result: list[NormalizedTitle] = []
        for start in range(0, total, self._chunk_size):
            self._sleep(self._delay)
            for position in range(start, min(start + self._chunk_size, total)):
                line = titles[position]
                recorded = self._recording.normalizations.get(line)
                if recorded is None:
                    result.append(NormalizedTitle(position + 1, romaji=line))
                else:
                    result.append(
                        NormalizedTitle(
                            index=position + 1,
                            romaji=recorded.romaji,
                            is_anime=recorded.is_anime,
                            ambiguous=recorded.ambiguous,
                            options=recorded.options,
                        )
                    )
            if on_progress is not None:
                on_progress(len(result), total)
        return result


class ReplaySearcher:
    """Replays recorded searches by exact query; unknown queries return no results."""

    def __init__(
        self,
        recording: DemoRecording,
        delay: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._recording = recording
        self._delay = delay
        self._sleep = sleep

    def search(self, query: str) -> list[AnimeCandidate]:
        self._sleep(self._delay)
        return list(self._recording.searches.get(query, []))


class ReplayDetailsProvider:
    def __init__(self, recording: DemoRecording) -> None:
        self._recording = recording

    def get_details(self, mal_id: int) -> AnimeDetails:
        try:
            return self._recording.details[mal_id]
        except KeyError:
            raise DetailsError(f"No recorded details for anime {mal_id}") from None


# ---------------------------------------------------------------- recording decorators


class RecordingNormalizer:
    """Wraps a real normalizer and records each successful normalization by original line."""

    def __init__(self, inner: TitleNormalizer, recording: DemoRecording) -> None:
        self._inner = inner
        self._recording = recording

    def normalize(
        self, titles: Sequence[str], on_progress: ProgressCallback | None = None
    ) -> list[NormalizedTitle]:
        result = self._inner.normalize(titles, on_progress=on_progress)
        by_index = {item.index: item for item in result}
        for position, line in enumerate(titles, start=1):
            item = by_index.get(position)
            if item is not None:
                self._recording.record_normalization(line, item)
        return result


class RecordingSearcher:
    def __init__(self, inner: AnimeSearcher, recording: DemoRecording) -> None:
        self._inner = inner
        self._recording = recording

    def search(self, query: str) -> list[AnimeCandidate]:
        result = self._inner.search(query)
        self._recording.record_search(query, result)
        return result


class RecordingDetailsProvider:
    def __init__(self, inner: AnimeDetailsProvider, recording: DemoRecording) -> None:
        self._inner = inner
        self._recording = recording

    def get_details(self, mal_id: int) -> AnimeDetails:
        details = self._inner.get_details(mal_id)
        self._recording.record_details(mal_id, details)
        return details
