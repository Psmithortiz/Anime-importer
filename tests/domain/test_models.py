import dataclasses

import pytest

from anime_importer.domain.models import AnimeCandidate, NormalizedTitle


def test_anime_candidate_is_immutable():
    candidate = AnimeCandidate(mal_id=1, title="Cowboy Bebop")
    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.title = "Otro"  # type: ignore[misc]


def test_equal_candidates_collapse_in_set():
    a = AnimeCandidate(mal_id=1, title="Cowboy Bebop", image_url="x.jpg")
    b = AnimeCandidate(mal_id=1, title="Cowboy Bebop", image_url="x.jpg")
    assert a == b
    assert len({a, b}) == 1


def test_normalized_title_defaults():
    title = NormalizedTitle(index=0, romaji="Shingeki no Kyojin")
    assert title.is_anime is True
    assert title.ambiguous is False
    assert title.options == ()
