from anime_importer.domain.models import (
    AnimeCandidate,
    AnimeDetails,
    Relation,
    RelationType,
)
from anime_importer.ports import DetailsError
from anime_importer.services.franchise import discover_franchise

R = RelationType


def _node(mal_id: int, year: int | None, *relations: tuple[int, RelationType]) -> AnimeDetails:
    return AnimeDetails(
        candidate=AnimeCandidate(mal_id, f"A{mal_id}", year=year),
        relations=tuple(Relation(target, kind) for target, kind in relations),
    )


class FakeProvider:
    def __init__(self, nodes: list[AnimeDetails], failing: set[int] = frozenset()) -> None:
        self._nodes = {n.candidate.mal_id: n for n in nodes}
        self._failing = failing
        self.calls: list[int] = []

    def get_details(self, mal_id: int) -> AnimeDetails:
        self.calls.append(mal_id)
        if mal_id in self._failing:
            raise DetailsError("boom")
        return self._nodes[mal_id]


def _chain(length: int) -> list[AnimeDetails]:
    nodes = []
    for i in range(1, length + 1):
        relations = []
        if i > 1:
            relations.append((i - 1, R.PREQUEL))
        if i < length:
            relations.append((i + 1, R.SEQUEL))
        nodes.append(_node(i, 2000 + i, *relations))
    return nodes


def _ids(franchise) -> list[int]:
    return [e.candidate.mal_id for e in franchise.entries]


def test_mutual_sequel_prequel_chain_has_no_loop_and_excludes_seed():
    provider = FakeProvider(_chain(3))

    result = discover_franchise([2], provider)

    assert _ids(result) == [1, 3]
    assert {e.candidate.mal_id: e.relation for e in result.entries} == {
        1: R.PREQUEL,
        3: R.SEQUEL,
    }
    assert result.truncated is False
    assert sorted(provider.calls) == [1, 2, 3]  # each node fetched once


def test_side_story_and_parent_story_appear_once():
    provider = FakeProvider(
        [
            _node(1, 2000, (9, R.SIDE_STORY)),
            _node(9, 2001, (1, R.PARENT_STORY)),
        ]
    )

    result = discover_franchise([1], provider)

    assert _ids(result) == [9]
    assert result.entries[0].relation is R.SIDE_STORY


def test_spin_off_is_listed_but_not_expanded():
    provider = FakeProvider(
        [
            _node(1, 2000, (5, R.SPIN_OFF)),
            _node(5, 2005, (6, R.SEQUEL)),
            _node(6, 2006),
        ]
    )

    result = discover_franchise([1], provider)

    assert _ids(result) == [5]
    assert result.entries[0].relation is R.SPIN_OFF
    assert 6 not in provider.calls


def test_character_and_other_relations_are_ignored():
    provider = FakeProvider(
        [_node(1, 2000, (2, R.CHARACTER), (3, R.OTHER)), _node(2, 1), _node(3, 1)]
    )

    result = discover_franchise([1], provider)

    assert result.entries == ()
    assert provider.calls == [1]


def test_max_nodes_truncates_long_chain():
    provider = FakeProvider(_chain(6))

    result = discover_franchise([1], provider, max_nodes=3)

    assert result.truncated is True
    assert len(provider.calls) <= 3


def test_exact_max_nodes_without_pending_work_is_not_truncated():
    provider = FakeProvider(_chain(3))

    result = discover_franchise([1], provider, max_nodes=3)

    assert result.truncated is False
    assert _ids(result) == [2, 3]


def test_failing_node_is_skipped_and_the_rest_continues():
    provider = FakeProvider(
        [
            _node(1, 2000, (2, R.SEQUEL), (3, R.SIDE_STORY)),
            _node(2, 2001),
            _node(3, 2002),
        ],
        failing={2},
    )

    result = discover_franchise([1], provider)

    assert _ids(result) == [3]


def test_entries_are_sorted_by_year_with_unknown_last():
    provider = FakeProvider(
        [
            _node(1, 2010, (2, R.SEQUEL), (3, R.SIDE_STORY), (4, R.SPIN_OFF), (5, R.SEQUEL)),
            _node(2, 2020),
            _node(3, None),
            _node(4, 2005),
            _node(5, 2020),
        ]
    )

    result = discover_franchise([1], provider)

    assert _ids(result) == [4, 2, 5, 3]
