import json
from pathlib import Path

import pytest

from anime_importer.adapters import demo
from anime_importer.adapters.demo import (
    DemoRecording,
    RecordingDetailsProvider,
    RecordingNormalizer,
    RecordingSearcher,
    ReplayDetailsProvider,
    ReplayNormalizer,
    ReplaySearcher,
)
from anime_importer.domain.models import (
    AiringStatus,
    AnimeCandidate,
    AnimeDetails,
    MediaType,
    NormalizedTitle,
    Relation,
    RelationType,
)
from anime_importer.ports import DetailsError, SearchError

FULL = AnimeCandidate(
    mal_id=5,
    title="Hellsing",
    image_url="http://img/5.jpg",
    alternative_titles=("Hellsing TV", "ヘルシング"),
    media_type=MediaType.TV,
    year=2001,
    episodes=13,
    airing_status=AiringStatus.FINISHED,
)
BARE = AnimeCandidate(mal_id=6, title="Bare")
DETAILS = AnimeDetails(FULL, (Relation(7, RelationType.SEQUEL), Relation(8, RelationType.SPIN_OFF)))
DETAILS_BARE = AnimeDetails(BARE, ())


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# ---------------------------------------------------------------- serialization


@pytest.mark.parametrize("candidate", [FULL, BARE])
def test_candidate_round_trip(candidate):
    data = demo.candidate_to_dict(candidate)

    assert json.loads(json.dumps(data)) == data  # JSON-compatible
    assert demo.candidate_from_dict(data) == candidate


@pytest.mark.parametrize("details", [DETAILS, DETAILS_BARE])
def test_details_round_trip(details):
    data = demo.details_to_dict(details)

    assert json.loads(json.dumps(data)) == data
    assert demo.details_from_dict(data) == details


@pytest.mark.parametrize(
    "title",
    [
        NormalizedTitle(0, "Hellsing"),
        NormalizedTitle(0, "Fullmetal", ambiguous=True, options=("A", "B")),
        NormalizedTitle(0, "Breaking Bad", is_anime=False),
    ],
)
def test_normalized_round_trip_drops_the_index(title):
    data = demo.normalized_to_dict(title)

    assert "index" not in data
    assert json.loads(json.dumps(data)) == data
    assert demo.normalized_from_dict(data, index=0) == title
    assert demo.normalized_from_dict(data, index=3).index == 3


def test_serialization_uses_plain_values_and_lists():
    data = demo.candidate_to_dict(FULL)

    assert data["media_type"] == "tv"
    assert data["airing_status"] == "finished"
    assert data["alternative_titles"] == ["Hellsing TV", "ヘルシング"]
    assert demo.candidate_to_dict(BARE)["media_type"] is None


# ---------------------------------------------------------------- recording


def _filled() -> DemoRecording:
    recording = DemoRecording()
    recording.record_normalization("hellsing", NormalizedTitle(0, "Hellsing"))
    recording.record_search("Hellsing", [FULL, BARE])
    recording.record_details(DETAILS)
    recording.record_details(DETAILS_BARE)
    return recording


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "sub" / "recording.json"

    _filled().save(path)
    loaded = DemoRecording.load(path)

    assert loaded.normalizations == {"hellsing": NormalizedTitle(0, "Hellsing")}
    assert loaded.searches == {"Hellsing": [FULL, BARE]}
    assert loaded.details == {5: DETAILS, 6: DETAILS_BARE}
    assert not path.with_name("recording.json.tmp").exists()


def test_save_is_readable_and_deterministic(tmp_path):
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    recording = _filled()
    recording.record_search("Another", [])

    recording.save(first)
    recording.save(second)

    text = first.read_text(encoding="utf-8")
    assert text == second.read_text(encoding="utf-8")
    assert "\n  " in text  # indented
    assert "ヘルシング" in text  # not ASCII-escaped
    assert list(json.loads(text)["searches"]) == ["Another", "Hellsing"]  # sorted keys


def test_shipped_recording_loads():
    path = Path(demo.__file__).parent / "demo_data" / "recording.json"

    loaded = DemoRecording.load(path)

    assert isinstance(loaded.searches, dict)


def test_shipped_sample_list_has_the_expected_lines():
    path = Path(demo.__file__).parent / "demo_data" / "list.txt"

    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 12
    assert lines[0] == "shingeki no kyojin S2 ***"
    assert lines[-1] == "Breaking Bad"


# ---------------------------------------------------------------- replay


def test_replay_normalizer_known_and_unknown_lines():
    recording = DemoRecording()
    recording.record_normalization(
        "fullmetal", NormalizedTitle(0, "Fullmetal", ambiguous=True, options=("A", "B"))
    )
    normalizer = ReplayNormalizer(recording, delay=0.5, sleep=Sleeps())

    result = normalizer.normalize(["hellsing", "fullmetal"])

    assert result == [
        NormalizedTitle(1, "hellsing"),
        NormalizedTitle(2, "Fullmetal", ambiguous=True, options=("A", "B")),
    ]


def test_replay_normalizer_progress_and_sleep_per_chunk():
    sleep = Sleeps()
    progress: list[tuple[int, int]] = []
    normalizer = ReplayNormalizer(DemoRecording(), delay=0.25, sleep=sleep, chunk_size=2)

    result = normalizer.normalize(list("abcde"), on_progress=lambda d, t: progress.append((d, t)))

    assert [t.index for t in result] == [1, 2, 3, 4, 5]
    assert progress == [(2, 5), (4, 5), (5, 5)]
    assert sleep.calls == [0.25, 0.25, 0.25]


def test_replay_normalizer_without_progress_callback():
    normalizer = ReplayNormalizer(DemoRecording(), delay=0, sleep=Sleeps())

    assert len(normalizer.normalize(["a"])) == 1


def test_replay_searcher_known_unknown_and_sleep():
    sleep = Sleeps()
    searcher = ReplaySearcher(_filled(), delay=0.1, sleep=sleep)

    assert searcher.search("Hellsing") == [FULL, BARE]
    assert searcher.search("hellsing") == []  # exact query only
    assert sleep.calls == [0.1, 0.1]


def test_replay_details_known_and_unknown():
    provider = ReplayDetailsProvider(_filled())

    assert provider.get_details(5) == DETAILS
    with pytest.raises(DetailsError):
        provider.get_details(999)


# ---------------------------------------------------------------- recording decorators


class InnerNormalizer:
    def normalize(self, titles, on_progress=None):
        return [NormalizedTitle(i, t.title()) for i, t in enumerate(titles, start=1)]


class InnerSearcher:
    def search(self, query):
        return [FULL]


class InnerDetails:
    def get_details(self, mal_id):
        return DETAILS


class Failing:
    def normalize(self, titles, on_progress=None):
        raise RuntimeError("boom")

    def search(self, query):
        raise SearchError("boom")

    def get_details(self, mal_id):
        raise DetailsError("boom")


def test_recording_normalizer_records_by_line():
    recording = DemoRecording()

    result = RecordingNormalizer(InnerNormalizer(), recording).normalize(["abc", "def"])

    assert result == [NormalizedTitle(1, "Abc"), NormalizedTitle(2, "Def")]
    assert recording.normalizations["abc"].romaji == "Abc"
    assert recording.normalizations["def"].romaji == "Def"


def test_recording_searcher_records_success():
    recording = DemoRecording()

    assert RecordingSearcher(InnerSearcher(), recording).search("q") == [FULL]
    assert recording.searches == {"q": [FULL]}


def test_recording_details_records_success():
    recording = DemoRecording()

    assert RecordingDetailsProvider(InnerDetails(), recording).get_details(5) == DETAILS
    assert recording.details == {5: DETAILS}


def test_recorders_do_not_record_failures():
    recording = DemoRecording()

    with pytest.raises(RuntimeError):
        RecordingNormalizer(Failing(), recording).normalize(["a"])
    with pytest.raises(SearchError):
        RecordingSearcher(Failing(), recording).search("q")
    with pytest.raises(DetailsError):
        RecordingDetailsProvider(Failing(), recording).get_details(1)

    assert (recording.normalizations, recording.searches, recording.details) == ({}, {}, {})
