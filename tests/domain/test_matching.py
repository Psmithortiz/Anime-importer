from anime_importer.domain.matching import MAX_OPTIONS, match_candidates
from anime_importer.domain.models import AnimeCandidate


def test_empty_candidates():
    result = match_candidates("naruto", [])
    assert result.accepted is None
    assert result.options == ()


def test_exact_title_case_insensitive():
    target = AnimeCandidate(mal_id=1, title="Cowboy Bebop")
    others = [AnimeCandidate(mal_id=2, title="Samurai Champloo")]
    result = match_candidates("cowboy bebop", [others[0], target])
    assert result.accepted == target


def test_ambiguous_query_returns_five_options():
    candidates = [AnimeCandidate(mal_id=i, title=f"Fullmetal Alchemist {i}") for i in range(7)]
    result = match_candidates("Alchemist", candidates)
    assert result.accepted is None
    assert len(result.options) == MAX_OPTIONS


def test_duplicate_titles_keep_both_ids():
    candidates = [
        AnimeCandidate(mal_id=10, title="Gintama"),
        AnimeCandidate(mal_id=20, title="Gintama"),
    ]
    result = match_candidates("Gintama Movie", candidates)
    assert result.accepted is None
    assert {c.mal_id for c in result.options} == {10, 20}
