import json

import pytest
import requests

from anime_importer.adapters.http import Throttle
from anime_importer.adapters.mal import (
    MalDetailsProvider,
    MalSearcher,
    parse_anime_node,
    parse_details_response,
    parse_relation_type,
)
from anime_importer.domain.models import AiringStatus, MediaType, Relation, RelationType
from anime_importer.ports import DetailsError

DETAILS_FIELDS = "alternative_titles,media_type,start_season,num_episodes,status,related_anime"

NODE = {
    "id": 2,
    "title": "Mahoutsukai no Yome Season 2",
    "media_type": "tv",
    "start_season": {"year": 2023},
    "num_episodes": 12,
    "status": "finished_airing",
    "related_anime": [
        {"node": {"id": 1, "title": "S1"}, "relation_type": "prequel"},
        {"node": {"id": 3, "title": "OVA"}, "relation_type": "side_story"},
        {"node": {"id": 4, "title": "Weird"}, "relation_type": "something_new"},
        {"node": {"id": 5, "title": "NoType"}},
    ],
}


class RecordingSession:
    def __init__(self, body: dict | None = None, status: int = 200) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[dict] = []
        self._body = body if body is not None else NODE
        self._status = status

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        response = requests.Response()
        response.status_code = self._status
        response._content = json.dumps(self._body).encode()
        return response


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("sequel", RelationType.SEQUEL),
        ("prequel", RelationType.PREQUEL),
        ("side_story", RelationType.SIDE_STORY),
        ("parent_story", RelationType.PARENT_STORY),
        ("spin_off", RelationType.SPIN_OFF),
        ("character", RelationType.CHARACTER),
        ("something_new", RelationType.OTHER),
        (None, RelationType.OTHER),
    ],
)
def test_parse_relation_type(value, expected):
    assert parse_relation_type(value) is expected


def test_parse_details_response_reads_candidate_and_relations():
    details = parse_details_response(NODE)

    assert details.candidate.mal_id == 2
    assert details.candidate.media_type is MediaType.TV
    assert details.candidate.year == 2023
    assert details.candidate.airing_status is AiringStatus.FINISHED
    assert details.relations == (
        Relation(1, RelationType.PREQUEL),
        Relation(3, RelationType.SIDE_STORY),
        Relation(4, RelationType.OTHER),
        Relation(5, RelationType.OTHER),
    )


def test_parse_details_response_without_related_anime():
    details = parse_details_response({"id": 1, "title": "A"})
    assert details.relations == ()
    assert parse_details_response({"id": 1, "title": "A", "related_anime": None}).relations == ()


def test_parse_anime_node_matches_search_parsing():
    candidate = parse_anime_node({"id": 7, "title": "X", "num_episodes": 0})
    assert (candidate.mal_id, candidate.title, candidate.episodes) == (7, "X", None)


def test_details_provider_sends_header_and_fields():
    session = RecordingSession()

    details = MalDetailsProvider(client_id="abc", session=session).get_details(2)

    assert session.headers["X-MAL-CLIENT-ID"] == "abc"
    assert session.calls[0]["url"].endswith("/anime/2")
    assert session.calls[0]["params"]["fields"] == DETAILS_FIELDS
    assert details.candidate.mal_id == 2


def test_details_provider_wraps_404_in_details_error():
    class NotFoundSession:
        headers: dict[str, str] = {}  # noqa: RUF012

        def get(self, *args, **kwargs):
            response = requests.Response()
            response.status_code = 404
            return response

    with pytest.raises(DetailsError) as exc_info:
        MalDetailsProvider(client_id="abc", session=NotFoundSession()).get_details(999)

    assert isinstance(exc_info.value.__cause__, requests.HTTPError)


def test_shared_throttle_spans_different_adapters():
    sleeps: list[float] = []
    clock = FakeClock()
    throttle = Throttle(1.0, clock=clock, sleep=sleeps.append)
    searcher = MalSearcher(
        client_id="abc", session=RecordingSession({"data": []}), throttle=throttle
    )
    provider = MalDetailsProvider(client_id="abc", session=RecordingSession(), throttle=throttle)

    searcher.search("Naruto")
    clock.now += 0.25
    provider.get_details(2)

    assert sleeps == [pytest.approx(0.75)]
