import pytest
import requests

from anime_importer.adapters.mal import (
    MalSearcher,
    parse_airing_status,
    parse_media_type,
    parse_search_response,
    sanitize_query,
)
from anime_importer.domain.models import AiringStatus, MediaType
from anime_importer.ports import SearchError


def test_parse_full_node():
    data = {
        "data": [
            {
                "node": {
                    "id": 16498,
                    "title": "Shingeki no Kyojin",
                    "main_picture": {"medium": "https://x/m.jpg", "large": "https://x/l.jpg"},
                    "alternative_titles": {
                        "en": "Attack on Titan",
                        "ja": "進撃の巨人",
                        "synonyms": ["AoT", "SnK"],
                    },
                }
            }
        ]
    }
    (candidate,) = parse_search_response(data)
    assert candidate.mal_id == 16498
    assert candidate.title == "Shingeki no Kyojin"
    assert candidate.image_url == "https://x/l.jpg"
    assert candidate.alternative_titles == ("Attack on Titan", "進撃の巨人", "AoT", "SnK")


def test_parse_node_without_picture_or_alternatives():
    (candidate,) = parse_search_response({"data": [{"node": {"id": 1, "title": "A"}}]})
    assert candidate.image_url is None
    assert candidate.alternative_titles == ()


def test_parse_skips_empty_alternative_title():
    data = {
        "data": [{"node": {"id": 1, "title": "A", "alternative_titles": {"en": "", "ja": "B"}}}]
    }
    (candidate,) = parse_search_response(data)
    assert candidate.alternative_titles == ("B",)


def test_sanitize_query_strips_special_chars_and_whitespace():
    assert sanitize_query("Re: Zero ") == "Re Zero"


def test_sanitize_query_replaces_symbols_with_spaces():
    assert (
        sanitize_query("Kimetsu no Yaiba: Hashira Geiko-hen")
        == "Kimetsu no Yaiba Hashira Geiko hen"
    )
    assert (
        sanitize_query("Shingeki no Kyojin: The Final Season - Kanketsu-hen")
        == "Shingeki no Kyojin The Final Season Kanketsu hen"
    )


def test_sanitize_query_does_not_cut_words_in_half():
    query = "Akujiki Reijou to Kyouketsu Koushaku: Sono Mamono, Watashi ga Oishiku Itadakimasu!"

    assert sanitize_query(query) == "Akujiki Reijou to Kyouketsu Koushaku Sono Mamono Watashi ga"


def test_sanitize_query_keeps_word_that_ends_exactly_at_the_limit():
    query = "a" * 30 + " " + "b" * 33 + " " + "cccc"  # 64th char ends "b...", 65th is a space

    result = sanitize_query(query)

    assert result == "a" * 30 + " " + "b" * 33
    assert len(result) == 64


def test_sanitize_query_trims_a_single_very_long_word():
    assert sanitize_query("x" * 100) == "x" * 64


def test_sanitize_query_short_text_is_unchanged():
    assert sanitize_query("Cowboy Bebop") == "Cowboy Bebop"


def test_sanitize_query_truncates_without_trailing_space():
    result = sanitize_query("abcdefg " * 10)
    assert len(result) <= 64
    assert not result.endswith(" ")


class _RecordingSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"data": []}'
        return response


def test_searcher_sends_header_and_params():
    session = _RecordingSession()
    MalSearcher(client_id="abc", session=session).search("Naruto")

    assert session.headers["X-MAL-CLIENT-ID"] == "abc"
    params = session.calls[0]["params"]
    assert params["q"] == "Naruto"
    assert params["limit"] == 100
    assert params["fields"] == "alternative_titles,media_type,start_season,num_episodes,status"
    assert params["nsfw"] == "true"


def test_search_wraps_http_error_in_search_error():
    response = requests.Response()
    response.status_code = 404
    error = requests.HTTPError(response=response)

    class FailingSession:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        def get(self, *args, **kwargs):
            raise error

    with pytest.raises(SearchError) as exc_info:
        MalSearcher(client_id="abc", session=FailingSession()).search("Naruto")

    assert exc_info.value.__cause__ is error


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("tv", MediaType.TV),
        ("movie", MediaType.MOVIE),
        ("ova", MediaType.OVA),
        ("ona", MediaType.ONA),
        ("special", MediaType.SPECIAL),
        ("tv_special", MediaType.SPECIAL),
        ("music", MediaType.MUSIC),
        ("cm", MediaType.OTHER),
        (None, MediaType.OTHER),
    ],
)
def test_parse_media_type(value, expected):
    assert parse_media_type(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("finished_airing", AiringStatus.FINISHED),
        ("currently_airing", AiringStatus.AIRING),
        ("not_yet_aired", AiringStatus.NOT_YET_AIRED),
        ("whatever", AiringStatus.UNKNOWN),
        (None, AiringStatus.UNKNOWN),
    ],
)
def test_parse_airing_status(value, expected):
    assert parse_airing_status(value) is expected


def test_parse_metadata_from_full_node():
    node = {
        "id": 1,
        "title": "A",
        "media_type": "movie",
        "start_season": {"year": 2016, "season": "summer"},
        "num_episodes": 1,
        "status": "finished_airing",
    }
    (candidate,) = parse_search_response({"data": [{"node": node}]})

    assert candidate.media_type is MediaType.MOVIE
    assert candidate.year == 2016
    assert candidate.episodes == 1
    assert candidate.airing_status is AiringStatus.FINISHED


def test_parse_metadata_defaults_when_missing():
    (candidate,) = parse_search_response({"data": [{"node": {"id": 1, "title": "A"}}]})

    assert candidate.media_type is MediaType.OTHER
    assert candidate.year is None
    assert candidate.episodes is None
    assert candidate.airing_status is AiringStatus.UNKNOWN


def test_parse_zero_episodes_is_none():
    node = {"id": 1, "title": "A", "num_episodes": 0}
    (candidate,) = parse_search_response({"data": [{"node": node}]})

    assert candidate.episodes is None


class _FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _throttled_searcher(sleeps: list[float], clock: _FakeClock) -> MalSearcher:
    return MalSearcher(
        client_id="abc",
        session=_RecordingSession(),
        min_interval=1.0,
        clock=clock,
        sleep=sleeps.append,
    )


def test_first_search_does_not_sleep():
    sleeps: list[float] = []
    _throttled_searcher(sleeps, _FakeClock()).search("Naruto")

    assert sleeps == []


def test_second_search_too_soon_sleeps_remaining_interval():
    sleeps: list[float] = []
    clock = _FakeClock()
    searcher = _throttled_searcher(sleeps, clock)

    searcher.search("Naruto")
    clock.now += 0.3
    searcher.search("Bleach")

    assert sleeps == [pytest.approx(0.7)]


def test_second_search_after_interval_does_not_sleep():
    sleeps: list[float] = []
    clock = _FakeClock()
    searcher = _throttled_searcher(sleeps, clock)

    searcher.search("Naruto")
    clock.now += 1.5
    searcher.search("Bleach")

    assert sleeps == []
