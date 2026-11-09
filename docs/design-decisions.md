# Design decisions

Back to the [README](../README.md).

## Architecture

```
src/anime_importer/
├── domain/        Pure models and rules. No I/O, no frameworks.
│   ├── models.py, matching.py   Dataclasses, enums and fuzzy matching.
│   └── session.py               Steps, resolutions, user decisions and stored snapshots.
├── ports.py       Protocols the core depends on (AnimeSearcher, TitleNormalizer,
│                  SessionRepository) and their errors.
├── adapters/      The outside world: Gemini, MAL, caches, XML and text files, demo replay.
│   ├── sqlite_repository.py     Sessions in SQLite (one connection per operation, WAL).
│   ├── memory_repository.py     The same contract in memory (CLI and tests).
│   └── session_codec.py         JSON serialization of resolutions and decisions.
├── services/      ImportSession: the state machine that drives an import and pauses for questions.
├── api/           FastAPI app, Pydantic schemas, session registry and the static frontend.
├── cli.py         Interactive terminal interface over the same service.
└── bootstrap.py   Composition root: the only place that wires concrete adapters together.
```

Dependencies point inward: `api / cli → services → domain ← adapters`. The domain never imports an
HTTP client, an SDK or a web framework, so it is tested without network access or API keys.
Outside the package, `scripts/record_demo.py` records the demo data with the real adapters (it
needs API keys).

## Decisions

### Ports and adapters, proven the hard way

The first version searched through Jikan, an unofficial
MAL mirror. In October 2026 Jikan's public API was discontinued. Because the service only depends on an
`AnimeSearcher` protocol, switching to the official MAL API meant writing one adapter and changing one
line in `bootstrap.py`. Each adapter also translates its own errors (`requests` exceptions become
`SearchError`) and its own vocabulary (`"currently_airing"` becomes `AiringStatus.AIRING`), so the core
never learns provider details.

### A state machine instead of a global dict

An import pauses for user input between HTTP requests.
`ImportSession` models each pause as a typed step (`NormalizationChoice`, `CandidateChoice`,
`Finished`), so an invalid combination (a normalization phase holding search results) cannot be built.
Every mutating method validates first and changes state second: a bad selection never leaves the session
half-updated.

### Background work with polling

Preparing an import takes minutes, so `POST /api/sessions` returns
`202 Accepted` immediately and the frontend polls the session, showing progress for both phases. A lock
serializes actions on a session (a double click can't advance it twice), but reads never take the lock,
so polling stays responsive. Endpoints are plain `def`: they call blocking code, which FastAPI runs in a
thread pool instead of stalling the event loop.

### Sessions as an event log

What gets saved is the input list, what Gemini and MAL computed for
each title, and the user's decisions, identified by query text and MAL id rather than by option
number. The state of a session is never stored: it is rebuilt by replaying those decisions over the
stored results, which is how a session resumes after a restart. Every fact is saved *before* it is
applied, so nothing is ever applied that could not be persisted. Undo is just removing the last
decision and replaying: it returns to the last answered question and never repeats a search, because
the results and the answers to earlier searches are kept. The consumer-side state is published with
copy-on-write (each action works on a copy and swaps it in with a single assignment), so the
lock-free readers behind the polling endpoint never see a half-applied step. The adapters are built
once per app and shared by all sessions, so MAL's rate limit and the JSON caches are not duplicated
when several sessions are open.

### Franchise discovery as a breadth-first search

MAL only exposes `related_anime` on each anime's
detail endpoint, so the franchise is a graph explored one request per node. Relations are mutual
(S1 → S2 is a *sequel*, S2 → S1 a *prequel*), so nodes are marked visited when they are **enqueued**, not
when they are processed — otherwise two seasons pointing at the same OVA would queue it twice. Only
in-continuity relations are expanded (sequel, prequel, side story, summary and their inverses);
spin-offs and alternative versions are shown but not followed, and character crossovers are ignored, so
a walk from *Re:Zero* never wanders into *Overlord*. A node cap bounds huge franchises, and details are
cached per MAL id for seven days. If the matched title has a franchise, the question is shown even when
the match itself was certain: that is how forgotten first seasons and announced sequels surface.

### Look-ahead resolution, like a video buffer

Each title needs a search plus a franchise walk, which
at one request per second is too slow to do after every answer. A background worker resolves titles in
order and appends each *resolution* (import, reject or ask) to a list; answering a question only
*applies* the next resolution. The first question appears once an initial buffer is ready, and the
worker keeps going while you answer, so most questions show up instantly. The worker and the request
threads coordinate through a `threading.Condition` (no polling loops), never hold a lock during network
I/O, and share a single thread-safe throttle so MAL's rate limit holds across both. In tests, the
background runner is injected and runs synchronously, which keeps the suite deterministic.

### Cache by title, not by chunk

Gemini answers a whole chunk or nothing, but results are stored per
title, keyed by the lightly normalized input line and versioned by a hash of the model and prompt.
A callback persists each chunk as soon as it validates, with atomic writes, so a quota error in chunk 11
keeps chunks 1–10. Inserting a title, reordering the list or changing the chunk size invalidates nothing.

### Matching bugs found with real data

Two examples:
- The query sanitizer deleted punctuation, turning `Geiko-hen` into `Geikohen`. MAL's search requires
  every word to match, so modern season titles returned nothing. Symbols now become spaces.
- Fuzzy matching originally mapped results back by title text, so two entries with the same title
  collapsed into one. Matching now keeps candidate identity, and a tie above the threshold is never
  auto-accepted.

### Reading the import contract carefully

I first assumed `update_on_import=0` meant "add only what's
missing". The real import showed MAL *ignores* those entries; protecting an existing list is done with
MAL's own "Don't overwrite entries already on my list" checkbox. The export now always sets `1` and the
UI tells you which box to check.

### No frontend framework

The UI is plain HTML, CSS and JavaScript served by FastAPI. All data from
external APIs is inserted with `textContent`, never `innerHTML`, to rule out XSS from titles.

### Demo mode as a second swap of adapters

`DEMO=1` makes `bootstrap.py` build replaying
adapters instead of Gemini and MAL; the domain and the service do not change. The data is not
written by hand: `scripts/record_demo.py` wraps the real adapters in recorders and walks a full
import, including every option of ambiguous titles, so the demo replays real responses. The
recording format is deliberately independent from the details cache, so changing one never
invalidates the other.

### A small, safe container

The image is built in two stages: the first resolves dependencies with
uv (cached as its own layer, so code changes don't reinstall them), the second copies only the
virtual environment and runs as a non-root user. `.dockerignore` is an allowlist, so local
caches and secrets can never end up in the image; keys are entered at run time. The server binds to `0.0.0.0`
only inside the container (through the `HOST` setting, so there is still a single entry point),
and compose publishes it on `127.0.0.1` only, because the app has no authentication.

### A desktop launcher without races

The launcher binds the socket itself and hands it to uvicorn.
Because it is already listening, the browser can be opened immediately (the OS queues the connection
until the server accepts it), and there is no gap between "check that the port is free" and "use
it". If the port is taken, the launcher asks `/api/info` to tell one of its own instances from
another program. On Windows it uses `SO_EXCLUSIVEADDRUSE`, because `SO_REUSEADDR` would let a second
process take a port that is already in use.

## Matching on real data

The 3 remaining lines each exposed a different issue: a query cut mid-word by the 64-character limit, a
normalization that was worse than the original line (the LLM "corrected" `Mob wo` to `Mobu o`, and
expanded an anime title to its manga's full name), and an abbreviation the LLM didn't recognize. Cutting
at word boundaries and falling back to the original line now resolve all three.
