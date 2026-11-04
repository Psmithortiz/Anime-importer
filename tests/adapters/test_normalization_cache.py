import json
from pathlib import Path

import pytest

from anime_importer.adapters.gemini import cache_version
from anime_importer.adapters.normalization_cache import (
    CachingNormalizer,
    JsonCacheStore,
    cache_key,
)
from anime_importer.domain.models import NormalizedTitle
from anime_importer.ports import NormalizationError


class FakeInner:
    """Normalizador falso que simula chunks de 2 y registra con qué títulos lo llamaron."""

    def __init__(self, fail_after_first_chunk: bool = False) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail_after_first_chunk

    def normalize(self, titles, on_chunk=None):
        self.calls.append(list(titles))
        results = []
        for start in range(0, len(titles), 2):
            chunk = titles[start : start + 2]
            chunk_results = [
                NormalizedTitle(i, f"R:{title}") for i, title in enumerate(chunk, start=1)
            ]
            if on_chunk is not None:
                on_chunk(chunk, chunk_results)
            if self._fail:
                raise NormalizationError("boom")
            results.extend(chunk_results)
        return results


def _normalizer(tmp_path: Path, inner: FakeInner | None = None):
    inner = inner or FakeInner()
    store = JsonCacheStore(tmp_path / "cache" / "v1.json")
    return CachingNormalizer(inner, store), inner, store


def test_second_run_uses_cache_only(tmp_path):
    normalizer, inner, _ = _normalizer(tmp_path)
    titles = ["a", "b", "c"]

    first = normalizer.normalize(titles)
    second = normalizer.normalize(titles)

    assert inner.calls == [["a", "b", "c"]]
    assert (tmp_path / "cache" / "v1.json").exists()
    assert second == first


def test_partial_cache_only_requests_missing_and_keeps_order(tmp_path):
    normalizer, inner, store = _normalizer(tmp_path)
    store.put_many(
        {"a": NormalizedTitle(0, "R:a"), "c": NormalizedTitle(0, "R:c")},
    )

    result = normalizer.normalize(["a", "b", "c"])

    assert inner.calls == [["b"]]
    assert [(t.index, t.romaji) for t in result] == [(1, "R:a"), (2, "R:b"), (3, "R:c")]


def test_whitespace_and_case_share_entry(tmp_path):
    normalizer, inner, _ = _normalizer(tmp_path)

    normalizer.normalize(["Cowboy  Bebop "])
    result = normalizer.normalize(["cowboy bebop"])

    assert len(inner.calls) == 1
    assert result[0].index == 1
    assert cache_key("Cowboy  Bebop ") == cache_key("cowboy bebop")


def test_duplicates_are_requested_once_and_result_keeps_all(tmp_path):
    normalizer, inner, _ = _normalizer(tmp_path)

    result = normalizer.normalize(["a", "b", "a"])

    assert inner.calls == [["a", "b"]]
    assert [t.index for t in result] == [1, 2, 3]
    assert result[0].romaji == result[2].romaji == "R:a"


def test_error_after_first_chunk_keeps_saved_titles(tmp_path):
    normalizer, _, store = _normalizer(tmp_path, FakeInner(fail_after_first_chunk=True))

    with pytest.raises(NormalizationError):
        normalizer.normalize(["a", "b", "c"])

    assert set(store.get_all()) == {"a", "b"}


def test_corrupt_json_is_treated_as_empty(tmp_path):
    path = tmp_path / "v1.json"
    path.write_text("{no es json", encoding="utf-8")
    store = JsonCacheStore(path)

    assert store.get_all() == {}
    store.put_many({"a": NormalizedTitle(0, "R:a")})
    assert set(store.get_all()) == {"a"}


def test_put_many_is_atomic_and_leaves_no_tmp(tmp_path):
    store = JsonCacheStore(tmp_path / "sub" / "v1.json")

    store.put_many({"a": NormalizedTitle(5, "A", ambiguous=True, options=("x", "y"))})

    assert sorted(p.name for p in (tmp_path / "sub").iterdir()) == ["v1.json"]
    on_disk = json.loads((tmp_path / "sub" / "v1.json").read_text(encoding="utf-8"))
    assert on_disk == {
        "a": {"romaji": "A", "is_anime": True, "ambiguous": True, "options": ["x", "y"]}
    }
    assert store.get_all()["a"] == NormalizedTitle(0, "A", ambiguous=True, options=("x", "y"))


def test_missing_file_is_empty(tmp_path):
    assert JsonCacheStore(tmp_path / "nope.json").get_all() == {}


def test_cache_version_depends_on_model_and_is_stable():
    assert cache_version("m1") == cache_version("m1")
    assert cache_version("m1") != cache_version("m2")
    assert len(cache_version("m1")) == 12
