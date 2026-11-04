import logging
from collections import deque
from collections.abc import Sequence

from anime_importer.domain.models import (
    FOLLOWED_RELATIONS,
    SHOWN_RELATIONS,
    AnimeDetails,
    Franchise,
    FranchiseEntry,
    RelationType,
)
from anime_importer.ports import AnimeDetailsProvider, DetailsError

logger = logging.getLogger(__name__)


def discover_franchise(
    seed_ids: Sequence[int], provider: AnimeDetailsProvider, max_nodes: int = 40
) -> Franchise:
    """Breadth-first walk over MAL relations starting at `seed_ids`.

    Followed relations (sequel, prequel, ...) are expanded; shown relations (spin-off, ...) are
    listed but not expanded. The visited set prevents loops: MAL relations are mutual
    (S1 -> S2 is a sequel, S2 -> S1 is a prequel), so without it the walk would never end.
    Each get_details() call counts as one node against `max_nodes`. Seeds are not in the result.
    """
    visited: set[int] = set(seed_ids)
    queue: deque[int] = deque(dict.fromkeys(seed_ids))
    reached_by: dict[int, RelationType] = {}  # followed ids discovered but not yet fetched
    entries: list[FranchiseEntry] = []
    fetched = 0
    truncated = False

    def fetch(mal_id: int) -> AnimeDetails | None:
        nonlocal fetched
        fetched += 1
        try:
            return provider.get_details(mal_id)
        except DetailsError as exc:
            logger.warning("Skipping anime %d: %s", mal_id, exc)
            return None

    while queue:
        if fetched >= max_nodes:
            truncated = True
            break
        mal_id = queue.popleft()
        details = fetch(mal_id)
        if details is None:
            continue
        if mal_id in reached_by:
            entries.append(FranchiseEntry(details.candidate, reached_by[mal_id]))
        for relation in details.relations:
            if relation.mal_id in visited:
                continue
            if relation.relation_type in FOLLOWED_RELATIONS:
                visited.add(relation.mal_id)
                reached_by[relation.mal_id] = relation.relation_type
                queue.append(relation.mal_id)
            elif relation.relation_type in SHOWN_RELATIONS:
                if fetched >= max_nodes:
                    truncated = True
                    break
                visited.add(relation.mal_id)
                shown = fetch(relation.mal_id)
                if shown is not None:
                    entries.append(FranchiseEntry(shown.candidate, relation.relation_type))
        if truncated:
            break

    entries.sort(
        key=lambda e: (e.candidate.year is None, e.candidate.year or 0, e.candidate.mal_id)
    )
    return Franchise(entries=tuple(entries), truncated=truncated)
