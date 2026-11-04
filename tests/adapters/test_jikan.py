import pytest
import requests

from anime_importer.adapters.jikan import (
    JikanSearcher,
    is_retryable,
    parse_search_response,
    sanitize_query,
)
from anime_importer.ports import SearchError


def _http_error(status: int) -> requests.HTTPError:
    r = requests.Response()
    r.status_code = status
    return requests.HTTPError(response=r)


def test_parse_search_response_image_variants():
    data = {
        "data": [
            {
                "mal_id": 1,
                "title": "A",
                "images": {"webp": {"large_image_url": "https://x/a.webp"}},
            },
            {
                "mal_id": 2,
                "title": "B",
                "images": {"jpg": {"image_url": "https://x/b.jpg"}},
            },
            {"mal_id": 3, "title": "C"},
        ]
    }
    a, b, c = parse_search_response(data)
    assert (a.mal_id, a.title, a.image_url) == (1, "A", "https://x/a.webp")
    assert (b.mal_id, b.title, b.image_url) == (2, "B", "https://x/b.jpg")
    assert (c.mal_id, c.title, c.image_url) == (3, "C", None)


def test_parse_search_response_empty():
    assert parse_search_response({}) == []


def test_sanitize_query_removes_special_chars():
    assert sanitize_query("Re:Zero!") == "ReZero"


def test_sanitize_query_truncates():
    assert len(sanitize_query("a" * 100)) == 64


@pytest.mark.parametrize(
    "exc",
    [requests.ConnectionError(), requests.Timeout(), _http_error(429), _http_error(503)],
)
def test_is_retryable_true(exc):
    assert is_retryable(exc)


@pytest.mark.parametrize("exc", [_http_error(404), ValueError()])
def test_is_retryable_false(exc):
    assert not is_retryable(exc)


def test_search_wraps_non_retryable_error_in_search_error():
    error = _http_error(404)

    class FakeSession:
        def get(self, *args, **kwargs):
            raise error

    with pytest.raises(SearchError) as exc_info:
        JikanSearcher(session=FakeSession()).search("Naruto")

    assert exc_info.value.__cause__ is error
