import pytest
import requests

from anime_importer.adapters.mal import MalSearcher, parse_search_response, sanitize_query
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
    assert params["fields"] == "alternative_titles"
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
