import json

from anime_importer.adapters.details_cache import CachingDetailsProvider
from anime_importer.domain.models import (
    AiringStatus,
    AnimeCandidate,
    AnimeDetails,
    MediaType,
    Relation,
    RelationType,
)

DETAILS = AnimeDetails(
    candidate=AnimeCandidate(
        mal_id=2,
        title="Season 2",
        image_url="http://img/2.jpg",
        alternative_titles=("Alt", "別名"),
        media_type=MediaType.TV,
        year=2023,
        episodes=12,
        airing_status=AiringStatus.FINISHED,
    ),
    relations=(Relation(1, RelationType.PREQUEL), Relation(3, RelationType.SPIN_OFF)),
)


class FakeInner:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def get_details(self, mal_id: int) -> AnimeDetails:
        self.calls.append(mal_id)
        return DETAILS


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _provider(tmp_path, clock, ttl=100.0):
    inner = FakeInner()
    path = tmp_path / "cache" / "details.json"
    return CachingDetailsProvider(inner, path, ttl_seconds=ttl, clock=clock), inner, path


def test_miss_asks_inner_and_persists(tmp_path):
    provider, inner, path = _provider(tmp_path, Clock())

    assert provider.get_details(2) == DETAILS

    assert inner.calls == [2]
    assert json.loads(path.read_text(encoding="utf-8"))["2"]["fetched_at"] == 1000.0
    assert [p.name for p in path.parent.iterdir()] == ["details.json"]


def test_hit_within_ttl_does_not_ask_inner(tmp_path):
    clock = Clock()
    provider, inner, _ = _provider(tmp_path, clock)

    provider.get_details(2)
    clock.now += 99
    provider.get_details(2)

    assert inner.calls == [2]


def test_expired_entry_is_fetched_again(tmp_path):
    clock = Clock()
    provider, inner, _ = _provider(tmp_path, clock)

    provider.get_details(2)
    clock.now += 100
    provider.get_details(2)

    assert inner.calls == [2, 2]


def test_roundtrip_keeps_every_field(tmp_path):
    clock = Clock()
    provider, _, path = _provider(tmp_path, clock)
    provider.get_details(2)

    # A new provider on the same file must rebuild the exact same object from disk.
    fresh_inner = FakeInner()
    fresh = CachingDetailsProvider(fresh_inner, path, ttl_seconds=100, clock=clock)
    restored = fresh.get_details(2)

    assert fresh_inner.calls == []
    assert restored == DETAILS
    assert isinstance(restored.candidate.alternative_titles, tuple)
    assert isinstance(restored.relations, tuple)
    assert restored.candidate.media_type is MediaType.TV
    assert restored.relations[1].relation_type is RelationType.SPIN_OFF


def test_corrupt_json_is_treated_as_empty(tmp_path):
    provider, inner, path = _provider(tmp_path, Clock())
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert provider.get_details(2) == DETAILS

    assert inner.calls == [2]
    assert "2" in json.loads(path.read_text(encoding="utf-8"))


def test_default_clock_is_wall_time():
    provider = CachingDetailsProvider(FakeInner(), path=None)  # type: ignore[arg-type]
    import time

    assert provider._clock is time.time
