# Anime Importer

[![CI](https://github.com/Psmithortiz/Anime-importer/actions/workflows/ci.yml/badge.svg)](https://github.com/Psmithortiz/Anime-importer/actions/workflows/ci.yml)

**[Download for Windows](https://github.com/Psmithortiz/Anime-importer/releases/latest)**
· [Try the demo with Docker](docs/setup.md#docker) · [Design decisions](docs/design-decisions.md)

Turn a messy, hand-written anime list into a clean [MyAnimeList](https://myanimelist.net/) import file.

Gemini normalizes each line (typos, mixed Spanish/English/romaji, personal notes like `S2 ***` or
`MANGA?`), the official MAL API finds the matching entries, and a small web UI with posters lets you
resolve the ambiguous ones, pick several seasons at once and set a list status for each. The result is a
native MAL XML file that you can import safely.

I kept a list of ~300 watched anime in a Word document, with inconsistent spelling, three languages and
my own shorthand for seasons, and existing importers expected clean data. This is a full rewrite of my
first script (May 2026, Flask) with a layered architecture, tests and a proper API, built as a backend
portfolio project.

![Choosing between candidates](docs/candidates.png)

## Results

Run end to end on my real list of 317 hand-written lines:

| | Version 1 (May 2026) | Version 2 |
|---|---|---|
| Lines resolved | 305 / 309 (98.7%) | 314 / 317 (99.1%) |
| MAL entries exported | 305 | 434 (franchise discovery added ~120 seasons, movies and OVAs) |
| Manual discards | 4 | 0 |

Importing the file with *Don't overwrite entries already on my list* left the 349 entries I already
had untouched and added 85 that were missing — mostly first seasons and side entries of franchises I
had only partially logged by hand.

![MAL import result](docs/mal-import-result.png)

The 3 remaining lines each exposed a different issue; see
[Matching on real data](docs/design-decisions.md#matching-on-real-data).

## Features

- **LLM normalization** with Gemini 2.5 Flash and Google Search grounding, in chunks, cached per title.
- **Fuzzy matching** on main and alternative titles, with a fallback to your own original line.
- **Web UI** with posters and metadata, and **multi-select** with a per-entry list status (*Completed*, *Watching*, *Plan to Watch*, …).
- **Franchise discovery**: sequels, prequels, OVAs and movies next to the candidates, so one line can import a whole series.
- **Look-ahead resolution**: a background worker resolves upcoming titles while you answer.
- **Keyboard-first** (`1`–`9`, `Enter`, `X`) and **unlimited undo** with `Ctrl+Z`, also after the last question.
- **Resumable sessions** in SQLite, a recent-sessions list and one-click **retry when MAL fails**.
- **REST API** documented at `/docs`, plus an interactive CLI.
- **Demo mode** (`DEMO=1`): replays recorded Gemini and MAL responses, no API keys needed.

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

## Highlights

- **[Ports and adapters](docs/design-decisions.md#ports-and-adapters-proven-the-hard-way).** When
  Jikan's public API shut down in October 2026, switching to the official MAL API took one new adapter
  and one line in the composition root.
- **[Franchise discovery as a BFS](docs/design-decisions.md#franchise-discovery-as-a-breadth-first-search).**
  One request per node over MAL relations, with nodes marked visited when enqueued so mutual relations
  never queue the same entry twice.
- **[Look-ahead resolution](docs/design-decisions.md#look-ahead-resolution-like-a-video-buffer).** A
  background worker resolves upcoming titles while you answer, coordinated through a
  `threading.Condition` and a shared throttle that keeps MAL's rate limit.
- **[Cache by title, not by chunk](docs/design-decisions.md#cache-by-title-not-by-chunk).** Versioned by
  model and prompt: a quota error in chunk 11 keeps chunks 1–10, and editing the list only pays for the
  new lines.
- **[Sessions as an event log](docs/design-decisions.md#sessions-as-an-event-log).** Decisions are saved
  to SQLite before they are applied, and the state is rebuilt by replaying them: unlimited undo and
  resumable sessions.

All design decisions: [docs/design-decisions.md](docs/design-decisions.md)

## Quick start

### Windows

Download `AnimeImporter-vX.Y.Z-windows-x64.zip` from **Assets** in the
[latest release](https://github.com/Psmithortiz/Anime-importer/releases/latest) (not "Source code"),
unzip it and run `AnimeImporter.exe`. The executable is not signed, so Windows may show a SmartScreen
warning: see [how to run it anyway](docs/setup.md#windows-app).

### Demo without API keys (Docker)

```bash
docker compose up --build
```

Open <http://127.0.0.1:8000>: it starts in demo mode with a sample list.

### From source

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Psmithortiz/Anime-importer
cd Anime-importer
uv sync
uv run anime-importer-web
```

The app asks for your API keys in its Settings screen.

Every option, configuration and the CLI: [docs/setup.md](docs/setup.md)

## Testing

```bash
uv run pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

The suite runs without network access or API keys. More in [docs/development.md](docs/development.md#tests-and-lint).

## Roadmap

- Full pipeline: overlap Gemini normalization and MAL resolution.

## License

MIT