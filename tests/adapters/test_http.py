import pytest
import requests

from anime_importer.adapters.http import is_retryable


def _http_error(status: int) -> requests.HTTPError:
    r = requests.Response()
    r.status_code = status
    return requests.HTTPError(response=r)


@pytest.mark.parametrize(
    "exc",
    [requests.ConnectionError(), requests.Timeout(), _http_error(429), _http_error(503)],
)
def test_is_retryable_true(exc):
    assert is_retryable(exc)


@pytest.mark.parametrize("exc", [_http_error(404), ValueError()])
def test_is_retryable_false(exc):
    assert not is_retryable(exc)
