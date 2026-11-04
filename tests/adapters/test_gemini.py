import json
import time
from types import SimpleNamespace

import pytest
from google.genai import errors

from anime_importer.adapters.gemini import (
    BatchValidationError,
    GeminiNormalizer,
    is_retryable,
    parse_normalization_response,
    wait_seconds,
)
from anime_importer.ports import NormalizationError


def _response(count: int) -> str:
    return json.dumps([{"n": i, "romaji": f"T{i}"} for i in range(1, count + 1)])


def test_parse_strips_fences_and_converts_fields():
    text = '```json\n[{"n": 1, "romaji": "A", "ambiguous": true, "options": ["x", "y"]}]\n```'
    (item,) = parse_normalization_response(text, 1)
    assert item.index == 1
    assert item.romaji == "A"
    assert item.ambiguous is True
    assert item.options == ("x", "y")


def test_parse_missing_romaji_defaults_to_empty():
    (item,) = parse_normalization_response('[{"n": 1}]', 1)
    assert item.romaji == ""
    assert item.is_anime is True
    assert item.options == ()


def test_parse_wrong_length_raises():
    with pytest.raises(BatchValidationError):
        parse_normalization_response(_response(1), 2)


def test_parse_wrong_indexes_raises():
    with pytest.raises(BatchValidationError):
        parse_normalization_response('[{"n": 1}, {"n": 3}]', 2)


def test_parse_not_a_list_raises():
    with pytest.raises(BatchValidationError):
        parse_normalization_response("{}", 1)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (errors.ClientError(429, {}), True),
        (errors.ClientError(400, {}), False),
        (errors.ServerError(500, {}), True),
        (ValueError(), False),
    ],
)
def test_is_retryable(exc, expected):
    assert is_retryable(exc) is expected


def test_normalize_chunks_renumbers_and_sleeps_between_chunks():
    calls = []

    def generate_content(model, contents, config):
        calls.append(contents)
        count = 2 if len(calls) == 1 else 1
        return SimpleNamespace(text=_response(count))

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    sleeps = []
    normalizer = GeminiNormalizer(client=client, chunk_size=2, sleep=sleeps.append)

    result = normalizer.normalize(["a", "b", "c"])

    assert [t.index for t in result] == [1, 2, 3]
    assert len(calls) == 2
    assert sleeps == [13]


def _client_raising(exc: Exception | None = None, text: str = ""):
    def generate_content(model, contents, config):
        if exc is not None:
            raise exc
        return SimpleNamespace(text=text)

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))


def test_normalize_wraps_api_error_in_normalization_error():
    error = errors.ClientError(400, {})
    normalizer = GeminiNormalizer(client=_client_raising(error), sleep=lambda _: None)

    with pytest.raises(NormalizationError) as exc_info:
        normalizer.normalize(["a"])

    assert exc_info.value.__cause__ is error


def test_normalize_wraps_missing_key_in_normalization_error():
    client = _client_raising(text='[{"romaji": "X"}]')
    normalizer = GeminiNormalizer(client=client, chunk_size=1, sleep=lambda _: None)

    with pytest.raises(NormalizationError):
        normalizer.normalize(["a"])


@pytest.mark.parametrize("text", [None, "   "])
def test_parse_empty_response_raises(text):
    with pytest.raises(BatchValidationError):
        parse_normalization_response(text, 1)


def test_parse_ignores_trailing_text():
    text = '[{"n": 1, "romaji": "A"}]\n\nSources: https://example.com [1]'
    (item,) = parse_normalization_response(text, 1)
    assert item.romaji == "A"


def test_parse_ignores_leading_text():
    (item,) = parse_normalization_response('Here you go:\n[{"n": 1, "romaji": "A"}]', 1)
    assert item.romaji == "A"


def test_parse_without_list_raises():
    with pytest.raises(BatchValidationError):
        parse_normalization_response("Sorry, I can't help with that.", 1)


def test_normalize_empty_text_every_attempt_raises_normalization_error(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)  # tenacity waits between retries
    calls = []

    def generate_content(model, contents, config):
        calls.append(contents)
        return SimpleNamespace(text=None)

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    normalizer = GeminiNormalizer(client=client, sleep=lambda _: None)

    with pytest.raises(NormalizationError):
        normalizer.normalize(["a"])

    assert len(calls) == 4


def test_normalize_calls_on_chunk_with_relative_indexes():
    def generate_content(model, contents, config):
        count = 2 if "1. a" in contents else 1
        return SimpleNamespace(text=_response(count))

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    normalizer = GeminiNormalizer(client=client, chunk_size=2, sleep=lambda _: None)
    seen = []

    normalizer.normalize(
        ["a", "b", "c"],
        on_chunk=lambda chunk, res: seen.append((list(chunk), [t.index for t in res])),
    )

    assert seen == [(["a", "b"], [1, 2]), (["c"], [1])]


@pytest.mark.parametrize(
    ("exc", "attempt", "expected"),
    [
        (errors.ClientError(429, {}), 2, 60),
        (errors.ServerError(503, {}), 1, 15),
        (errors.ServerError(503, {}), 2, 30),
        (errors.ServerError(503, {}), 3, 60),
        (BatchValidationError("x"), 3, 2),
        (json.JSONDecodeError("x", "", 0), 3, 12),
    ],
)
def test_wait_seconds(exc, attempt, expected):
    state = SimpleNamespace(outcome=SimpleNamespace(exception=lambda: exc), attempt_number=attempt)

    assert wait_seconds(state) == expected
