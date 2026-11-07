"""Record the demo data (demo_data/recording.json) from real Gemini and MAL responses.

Usage: `uv run python scripts/record_demo.py` (needs GEMINI_API_KEY and MAL_CLIENT_ID).

The script walks the whole demo list through an ImportSession built on recording decorators.
NOTE: the logic of `ImportSession._resolve_query` is intentionally duplicated here, limited to
this script. When the session asks a normalization question, the user's answer (option 1) is
resolved *later*, in the caller's thread, with a query that was never searched during the
background pass. To have every option available at replay time, the script searches each option
(and the original line) and discovers its franchise *before* answering, exactly as the service
would do. The domain and the service stay untouched.
"""

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from anime_importer.adapters.demo import (
    DemoRecording,
    RecordingDetailsProvider,
    RecordingNormalizer,
    RecordingSearcher,
)
from anime_importer.bootstrap import build_real_adapters
from anime_importer.config import Settings
from anime_importer.domain.matching import match_candidates
from anime_importer.domain.models import Franchise
from anime_importer.ports import SearchError
from anime_importer.services.franchise import discover_franchise
from anime_importer.services.import_session import (
    CandidateChoice,
    Finished,
    ImportSession,
    NormalizationChoice,
)

DEMO_DATA_DIR = Path(__file__).resolve().parent.parent / "src/anime_importer/adapters/demo_data"


def main() -> int:
    settings = Settings(demo=False)
    normalizer, searcher, details = build_real_adapters(settings)
    assert details is not None
    recording = DemoRecording()
    rec_normalizer = RecordingNormalizer(normalizer, recording)
    rec_searcher = RecordingSearcher(searcher, recording)
    rec_details = RecordingDetailsProvider(details, recording)

    def finder(seed_ids: Sequence[int]) -> Franchise:
        return discover_franchise(seed_ids, rec_details, settings.franchise_max_nodes)

    titles = [
        line.strip()
        for line in (DEMO_DATA_DIR / "list.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    session = ImportSession(
        titles,
        normalizer=rec_normalizer,
        searcher=rec_searcher,
        franchise_finder=finder,
        resolution_buffer=settings.resolution_buffer,
    )

    step = session.start()
    while not isinstance(step, Finished):
        if isinstance(step, NormalizationChoice):
            for query in dict.fromkeys((*step.options, step.original_title)):
                _prefetch(query, rec_searcher, finder)
        elif not isinstance(step, CandidateChoice):
            raise TypeError(f"Unexpected step: {step!r}")
        step = session.choose(1)

    recording.save(DEMO_DATA_DIR / "recording.json")
    print(
        f"Recorded {len(recording.normalizations)} normalizations, "
        f"{len(recording.searches)} searches and {len(recording.details)} details."
    )
    print(f"Rejected titles: {len(step.rejected)}")
    for rejected in step.rejected:
        print(f"  - {rejected.original_title}: {rejected.reason}")
    return 0


def _prefetch(
    query: str, searcher: RecordingSearcher, finder: Callable[[Sequence[int]], Franchise]
) -> None:
    """Search `query` and discover the franchise the service would look up for it."""
    try:
        candidates = searcher.search(query)
    except SearchError as exc:
        print(f"Search failed for {query!r}: {exc}", file=sys.stderr)
        return
    if not candidates:
        return
    result = match_candidates(query, candidates)
    if result.accepted is not None:
        seeds = [result.accepted.mal_id]
    else:
        seeds = [candidate.mal_id for candidate in result.options]
    finder(seeds)


if __name__ == "__main__":
    raise SystemExit(main())
