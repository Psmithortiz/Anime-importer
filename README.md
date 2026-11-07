# Anime Importer

[![CI](https://github.com/Psmithortiz/Anime-importer/actions/workflows/ci.yml/badge.svg)](https://github.com/Psmithortiz/Anime-importer/actions/workflows/ci.yml)

Turn a messy, hand-written anime list into a clean [MyAnimeList](https://myanimelist.net/) import file.

Gemini normalizes each line (typos, mixed Spanish/English/romaji, personal notes like `S2 ***` or
`MANGA?`), the official MAL API finds the matching entries, and a small web UI with posters lets you
resolve the ambiguous ones, pick several seasons at once and set a list status for each. The result is a
native MAL XML file that you can import safely.

![Choosing between candidates](docs/candidates.png)

## Why this exists

Over the years I kept a list of the ~300 anime I had watched in a Word document, with inconsistent
spelling, three languages and my own shorthand for seasons. Existing importers expected clean data.
This tool handles the mess.

The first version (May 2026) was a working script with a Flask UI. This version is a full rewrite with a
layered architecture, tests and a proper API, built as a backend portfolio project.

## Features

- **LLM normalization** with Gemini 2.5 Flash and Google Search grounding, in chunks, with retries
  tuned per error type (rate limit, overload, malformed output).
- **Per-title normalization cache**: a failed or interrupted run never pays twice for titles it
  already normalized, and editing the list only costs the new lines.
- **Fuzzy matching** against each candidate's main and alternative titles (English, Japanese, synonyms).
- **Fallback to your own line**: when the normalized title finds nothing on MAL, the original line is
  searched instead, and it is always offered as an option when the normalizer is unsure.
- **Web UI** with posters, media type, year, episode count and airing status
  (*Airing*, *Not yet aired*).
- **Multi-select** with a per-entry list status (*Completed*, *Watching*, *Plan to Watch*, …),
  suggested from the airing status.
- **Franchise discovery**: a breadth-first walk over MAL relations shows sequels, prequels, OVAs and
  movies next to the candidates, so one line of the list can import a whole series.
- **Look-ahead resolution**: a background worker resolves upcoming titles while you answer, after a
  short initial buffer, so most questions appear instantly.
- **Keyboard-first**: `1`–`9` to select, `Enter` to confirm, `X` to discard.
- **REST API** documented automatically at `/docs`, plus an interactive CLI.
- **Demo mode** (`DEMO=1`): replays recorded Gemini and MAL responses, so you can try the whole
  flow without API keys.

![Selecting seasons from the candidates and the franchise column](docs/multi-select.png)
*Picking Season 2 and Part 2 from the candidates, and the Season 1 prequel from the franchise column.*
## How it works

```
anime_list.txt
   │
   ▼
Gemini normalization ──── per-title cache (JSON on disk, versioned by model + prompt)
   │   ambiguous? ──► ask: which title should I search for?
   ▼
MAL search (official API v2, throttled)
   │
   ▼
Fuzzy match (main + alternative titles)
   ├─ exactly one candidate ≥ 95 ──► accepted automatically, status suggested from airing status
   └─ otherwise ──► ask: pick one or more candidates, each with a list status
   ▼
MAL XML export (import with "Don't overwrite entries already on my list")
```

## Architecture

```
src/anime_importer/
├── domain/        Pure models and rules: dataclasses, enums, matching. No I/O, no frameworks.
├── ports.py       Protocols the core depends on (AnimeSearcher, TitleNormalizer) and their errors.
├── adapters/      The outside world: Gemini, MAL, caches, XML and text files, demo replay.
├── services/      ImportSession: the state machine that drives an import and pauses for questions.
├── api/           FastAPI app, Pydantic schemas, in-memory session registry and the static frontend.
├── cli.py         Interactive terminal interface over the same service.
└── bootstrap.py   Composition root: the only place that wires concrete adapters together.
```

Dependencies point inward: `api / cli → services → domain ← adapters`. The domain never imports an
HTTP client, an SDK or a web framework, so it is tested without network access or API keys.
Outside the package, `scripts/record_demo.py` records the demo data with the real adapters (it
needs API keys).

## Design decisions

**Ports and adapters, proven the hard way.** The first version searched through Jikan, an unofficial
MAL mirror. In October 2026 Jikan's public API was discontinued. Because the service only depends on an
`AnimeSearcher` protocol, switching to the official MAL API meant writing one adapter and changing one
line in `bootstrap.py`. Each adapter also translates its own errors (`requests` exceptions become
`SearchError`) and its own vocabulary (`"currently_airing"` becomes `AiringStatus.AIRING`), so the core
never learns provider details.

**A state machine instead of a global dict.** An import pauses for user input between HTTP requests.
`ImportSession` models each pause as a typed step (`NormalizationChoice`, `CandidateChoice`,
`Finished`), so an invalid combination (a normalization phase holding search results) cannot be built.
Every mutating method validates first and changes state second: a bad selection never leaves the session
half-updated.

**Background work with polling.** Preparing an import takes minutes, so `POST /api/sessions` returns
`202 Accepted` immediately and the frontend polls the session, showing progress for both phases. A lock
serializes actions on a session (a double click can't advance it twice), but reads never take the lock,
so polling stays responsive. Endpoints are plain `def`: they call blocking code, which FastAPI runs in a
thread pool instead of stalling the event loop.

**Franchise discovery as a breadth-first search.** MAL only exposes `related_anime` on each anime's
detail endpoint, so the franchise is a graph explored one request per node. Relations are mutual
(S1 → S2 is a *sequel*, S2 → S1 a *prequel*), so nodes are marked visited when they are **enqueued**, not
when they are processed — otherwise two seasons pointing at the same OVA would queue it twice. Only
in-continuity relations are expanded (sequel, prequel, side story, summary and their inverses);
spin-offs and alternative versions are shown but not followed, and character crossovers are ignored, so
a walk from *Re:Zero* never wanders into *Overlord*. A node cap bounds huge franchises, and details are
cached per MAL id for seven days. If the matched title has a franchise, the question is shown even when
the match itself was certain: that is how forgotten first seasons and announced sequels surface.

**Look-ahead resolution, like a video buffer.** Each title needs a search plus a franchise walk, which
at one request per second is too slow to do after every answer. A background worker resolves titles in
order and appends each *resolution* (import, reject or ask) to a list; answering a question only
*applies* the next resolution. The first question appears once an initial buffer is ready, and the
worker keeps going while you answer, so most questions show up instantly. The worker and the request
threads coordinate through a `threading.Condition` (no polling loops), never hold a lock during network
I/O, and share a single thread-safe throttle so MAL's rate limit holds across both. In tests, the
background runner is injected and runs synchronously, which keeps the suite deterministic.

**Cache by title, not by chunk.** Gemini answers a whole chunk or nothing, but results are stored per
title, keyed by the lightly normalized input line and versioned by a hash of the model and prompt.
A callback persists each chunk as soon as it validates, with atomic writes, so a quota error in chunk 11
keeps chunks 1–10. Inserting a title, reordering the list or changing the chunk size invalidates nothing.

**Matching bugs found with real data.** Two examples:
- The query sanitizer deleted punctuation, turning `Geiko-hen` into `Geikohen`. MAL's search requires
  every word to match, so modern season titles returned nothing. Symbols now become spaces.
- Fuzzy matching originally mapped results back by title text, so two entries with the same title
  collapsed into one. Matching now keeps candidate identity, and a tie above the threshold is never
  auto-accepted.

**Reading the import contract carefully.** I first assumed `update_on_import=0` meant "add only what's
missing". The real import showed MAL *ignores* those entries; protecting an existing list is done with
MAL's own "Don't overwrite entries already on my list" checkbox. The export now always sets `1` and the
UI tells you which box to check.

**No frontend framework.** The UI is plain HTML, CSS and JavaScript served by FastAPI. All data from
external APIs is inserted with `textContent`, never `innerHTML`, to rule out XSS from titles.

**Demo mode as a second swap of adapters.** `DEMO=1` makes `bootstrap.py` build replaying
adapters instead of Gemini and MAL; the domain and the service do not change. The data is not
written by hand: `scripts/record_demo.py` wraps the real adapters in recorders and walks a full
import, including every option of ambiguous titles, so the demo replays real responses. The
recording format is deliberately independent from the details cache, so changing one never
invalidates the other.

**A small, safe container.** The image is built in two stages: the first resolves dependencies with
uv (cached as its own layer, so code changes don't reinstall them), the second copies only the
virtual environment and runs as a non-root user. `.dockerignore` is an allowlist, so `.env` and local
caches can never end up in the image; keys are passed at run time. The server binds to `0.0.0.0`
only inside the container (through the `HOST` setting, so there is still a single entry point),
and compose publishes it on `127.0.0.1` only, because the app has no authentication.

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

### Try it without API keys

Demo mode replays real Gemini and MyAnimeList responses recorded for a sample list, so it needs
no `.env` and no network access to the APIs:

```bash
DEMO=1 uvx --from git+https://github.com/Psmithortiz/Anime-importer anime-importer-web
```

On Windows PowerShell: `$env:DEMO="1"; uvx --from git+https://github.com/Psmithortiz/Anime-importer anime-importer-web`

The sample list is preloaded. Titles outside it won't be found.

### Docker

```bash
docker compose up --build
```

Open <http://127.0.0.1:8000>. It starts in demo mode. To use your own keys, put the `.env` file in
the project root and run `DEMO=0 docker compose up` (PowerShell: `$env:DEMO="0"; docker compose up`).
Normalization and MAL caches are kept in a Docker volume between runs.

### Quick run (no clone)

With [uv](https://docs.astral.sh/uv/) installed, you can run the web UI straight from GitHub:

```bash
uvx --from git+https://github.com/Psmithortiz/Anime-importer anime-importer-web
```

Run it from a folder that contains your `.env` file (see below): settings are read from the
current directory, and the normalization cache is created there too.

### From source

```bash
git clone https://github.com/Psmithortiz/Anime-importer
cd Anime-importer
uv sync
```

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your_gemini_key        # from Google AI Studio
MAL_CLIENT_ID=your_mal_client_id      # from https://myanimelist.net/apiconfig
```

Optional settings: `GEMINI_MODEL`, `GEMINI_CHUNK_SIZE` (default 20) and `NORMALIZATION_CACHE_DIR`
(default `.cache/normalization`).

## Usage

### Web UI

```bash
uv run anime-importer-web
```

Open <http://127.0.0.1:8000>, paste your list or load a `.txt` file (one title per line) and start.
The API documentation is at <http://127.0.0.1:8000/docs>.

Download the XML at the end and import it from
[MAL's import page](https://myanimelist.net/import.php) (choose *MyAnimeList Import*). Check
*Don't overwrite entries already on my list* to keep your current list unchanged.

### CLI

```bash
uv run anime-importer --input anime_list.txt --output output.xml
```

## Rate limits

- **Gemini 2.5 Flash, free tier**: 5 requests per minute and 20 per day. A 317-title list takes 16
  requests with the default chunk size. If the daily quota runs out, switch keys and restart: the cache
  keeps everything already normalized.
- **MAL API**: requests are throttled to one per second.

## Testing

```bash
uv run pytest
uv run ruff check src tests
```

The suite runs without network access, API keys or real waits: adapters accept injected
sessions, clients, clocks and sleep functions.

CI runs both commands on Ubuntu and Windows for every pull request, and builds the Docker image
with a demo-mode smoke test.

## Roadmap

- Full pipeline: overlap Gemini normalization and MAL resolution.
- Undo the last decision.

## Results

Run end to end on my real list of 317 hand-written lines:

| | Version 1 (May 2026) | Version 2 |
|---|---|---|
| Lines resolved | 305 / 309 (98.7%) | 314 / 317 (99.1%) |
| MAL entries exported | 305 | 434 (franchise discovery added ~120 seasons, movies and OVAs) |
| Manual discards | 4 | 0 |

![Import summary](docs/finished.png)

Importing the file with *Don't overwrite entries already on my list* left the 349 entries I already
had untouched and added 85 that were missing — mostly first seasons and side entries of franchises I
had only partially logged by hand.

![MAL import result](docs/mal-import-result.png)

The 3 remaining lines each exposed a different issue: a query cut mid-word by the 64-character limit, a
normalization that was worse than the original line (the LLM "corrected" `Mob wo` to `Mobu o`, and
expanded an anime title to its manga's full name), and an abbreviation the LLM didn't recognize. Cutting
at word boundaries and falling back to the original line now resolve all three.

## License

MIT