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


def test_tie_above_threshold_is_not_auto_accepted():
    candidates = [
        AnimeCandidate(mal_id=10, title="Gintama"),
        AnimeCandidate(mal_id=20, title="Gintama"),
    ]
    result = match_candidates("Gintama", candidates)
    assert result.accepted is None
    assert {c.mal_id for c in result.options} == {10, 20}


def test_alternative_title_match_is_accepted():
    target = AnimeCandidate(
        mal_id=1, title="Shingeki no Kyojin", alternative_titles=("Attack on Titan",)
    )
    other = AnimeCandidate(mal_id=2, title="Kimetsu no Yaiba", alternative_titles=("Demon Slayer",))
    result = match_candidates("attack on titan", [other, target])
    assert result.accepted == target


def test_candidate_with_many_alternatives_appears_once_in_options():
    multi = AnimeCandidate(
        mal_id=1,
        title="Fullmetal Alchemist",
        alternative_titles=("Fullmetal Alchemist TV", "Hagane no Renkinjutsushi", "FMA"),
    )
    other = AnimeCandidate(mal_id=2, title="Samurai Champloo")
    result = match_candidates("Alchemist", [multi, other])
    assert result.accepted is None
    assert [c.mal_id for c in result.options].count(1) == 1


def test_tie_from_identical_synonyms_is_not_auto_accepted():
    candidates = [
        AnimeCandidate(mal_id=10, title="Foo", alternative_titles=("Attack on Titan",)),
        AnimeCandidate(mal_id=20, title="Bar", alternative_titles=("Attack on Titan",)),
    ]
    result = match_candidates("Attack on Titan", candidates)
    assert result.accepted is None
    assert {c.mal_id for c in result.options} == {10, 20}
