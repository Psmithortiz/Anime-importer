import json
import logging
import os
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from anime_importer.domain.models import NormalizedTitle
from anime_importer.ports import ChunkedNormalizer, ProgressCallback

logger = logging.getLogger(__name__)


def cache_key(title: str) -> str:
    return " ".join(title.split()).casefold()


def _to_dict(item: NormalizedTitle) -> dict[str, Any]:
    return {
        "romaji": item.romaji,
        "is_anime": item.is_anime,
        "ambiguous": item.ambiguous,
        "options": list(item.options),
    }


def _from_dict(data: dict[str, Any]) -> NormalizedTitle:
    return NormalizedTitle(
        index=0,  # provisional: the index depends on the list being processed
        romaji=data["romaji"],
        is_anime=data["is_anime"],
        ambiguous=data["ambiguous"],
        options=tuple(data["options"]),
    )


class JsonCacheStore:
    """Cache in a JSON file {key: normalization data}, with atomic writes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def get_all(self) -> dict[str, NormalizedTitle]:
        with self._lock:
            return self._read()

    def put_many(self, entries: dict[str, NormalizedTitle]) -> None:
        with self._lock:
            merged = self._read()
            merged.update(entries)
            payload = {key: _to_dict(item) for key, item in merged.items()}
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_name(self._path.name + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)

    def _read(self) -> dict[str, NormalizedTitle]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            data = json.loads(raw)
            return {key: _from_dict(value) for key, value in data.items()}
        except (ValueError, KeyError, TypeError, AttributeError):
            logger.warning("Corrupt normalization cache, ignoring it: %s", self._path)
            return {}


class CachingNormalizer:
    """Avoid asking the normalizer again for titles it already normalized (per title, not per list)."""

    def __init__(self, inner: ChunkedNormalizer, store: JsonCacheStore) -> None:
        self._inner = inner
        self._store = store

    def normalize(
        self,
        titles: list[str] | tuple[str, ...],
        on_progress: ProgressCallback | None = None,
    ) -> list[NormalizedTitle]:
        cached = self._store.get_all()
        keys = [cache_key(title) for title in titles]

        def report() -> None:
            # Counts positions of the full list (not unique keys); the inner normalizer
            # only sees the missing titles, so this wrapper reports the overall progress.
            if on_progress is not None:
                on_progress(sum(1 for key in keys if key in cached), len(titles))

        report()

        missing: list[str] = []
        seen: set[str] = set()
        for title, key in zip(titles, keys, strict=True):
            if key not in cached and key not in seen:
                seen.add(key)
                missing.append(title)

        logger.info(
            "Normalization: %d titles, %d from cache, %d to request",
            len(titles),
            len(set(keys)) - len(missing),
            len(missing),
        )

        if missing:

            def on_chunk(chunk, chunk_results) -> None:
                entries = {
                    cache_key(chunk[item.index - 1]): item
                    for item in chunk_results
                    if 1 <= item.index <= len(chunk)
                }
                self._store.put_many(entries)
                cached.update(entries)
                report()

            self._inner.normalize(missing, on_chunk=on_chunk)

        return [replace(cached[key], index=i) for i, key in enumerate(keys, start=1)]
