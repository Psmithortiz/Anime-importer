import json
import logging
import os
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

from anime_importer.domain.models import NormalizedTitle
from anime_importer.ports import ChunkedNormalizer

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
        index=0,  # provisorio: el índice depende de la lista que se esté procesando
        romaji=data["romaji"],
        is_anime=data["is_anime"],
        ambiguous=data["ambiguous"],
        options=tuple(data["options"]),
    )


class JsonCacheStore:
    """Caché en un archivo JSON {clave: datos de normalización}, con escritura atómica."""

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
            logger.warning("Caché de normalización corrupto, se ignora: %s", self._path)
            return {}


class CachingNormalizer:
    """Evita volver a pedir al normalizador títulos que ya normalizó (por título, no por lista)."""

    def __init__(self, inner: ChunkedNormalizer, store: JsonCacheStore) -> None:
        self._inner = inner
        self._store = store

    def normalize(self, titles: list[str] | tuple[str, ...]) -> list[NormalizedTitle]:
        cached = self._store.get_all()
        keys = [cache_key(title) for title in titles]

        missing: list[str] = []
        seen: set[str] = set()
        for title, key in zip(titles, keys, strict=True):
            if key not in cached and key not in seen:
                seen.add(key)
                missing.append(title)

        logger.info(
            "Normalización: %d títulos, %d del caché, %d a pedir",
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

            self._inner.normalize(missing, on_chunk=on_chunk)

        return [replace(cached[key], index=i) for i, key in enumerate(keys, start=1)]
