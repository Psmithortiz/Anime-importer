# Anime Importer

A Python tool that normalizes a messy personal anime list (with typos, mixed Spanish/English/romaji, and personal notes) and imports it into [MyAnimeList](https://myanimelist.net/) via native XML.

Two interfaces are available: a **CLI** for batch processing in the terminal, and a **Flask web UI** for interactive resolution of ambiguous titles with poster previews.

## Why this exists

I had ~300 anime titles in a Word document, written over years with inconsistent spelling, mixing languages, and personal annotations like `S1 S2`, `MANGA?`, or `Novela`. Manually re-entering them into MAL was not an option. Existing importers expected clean data; this tool handles the mess.

## Stack

- **Python 3.13**
- **Flask + Jinja2** — web UI
- **Google Gemini 2.5 Flash** with Google Search grounding — title normalization
- **[Jikan API](https://jikan.moe/)** — MyAnimeList search (unofficial mirror, better recall than MAL's official search for modern anime)
- **`thefuzz`** — fuzzy matching against search results
- **`requests`, `python-dotenv`, `tqdm`**

## Setup

```bash
git clone https://github.com/Psmithortiz/Anime-importer
cd Anime-importer
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

Create a `.env` file in the project root with:

```
GEMINI_API_KEY=your_key_here
MAL_CLIENT_ID=your_client_id_here
```

Place your anime list in `anime_list.txt`, one title per line. Notes like `MANGA?`, `S1 S2`, or `Novela` are ignored by the normalizer.

## Usage

### Web UI (recommended for interactive use)

```bash
python web.py
```

Open `http://127.0.0.1:5000` in your browser and click "EMPEZAR".

The app will:
1. Send your titles to Gemini in batches for romaji normalization
2. Search each romaji in Jikan
3. Show you menus only when the AI is uncertain (ambiguous titles) or the fuzzy match score is below threshold
4. Let you discard titles that don't match anything
5. Generate `output.xml` for upload to MAL and `errores.txt` for skipped titles

### CLI

```bash
python main.py
```

Same pipeline, terminal-based menus. Faster if you trust the defaults, less informative for ambiguous cases.

## How it works

```
anime_list.txt
    ↓
Gemini batch normalization (chunks of 20, ~13s sleep between chunks)
    ↓
For each title:
    ├─ ambiguous? → ask user (Gemini menu)
    ↓
    Jikan search by romaji
    ├─ fuzzy match score >= 95? → auto-resolve
    ├─ score < 95? → ask user (Jikan menu with poster preview)
    └─ no results? → log to errores.txt
    ↓
Export to output.xml
```

### Key design decisions

- **"Always-anime" prompt approach.** Every title in the input is something the user has personally watched, so the LLM doesn't need to classify whether it's anime — it just normalizes spelling. This eliminated persistent false negatives on post-cutoff titles.
- **Jikan over MAL's official search API.** MAL v2 search has poor recall for modern anime (2024+). Jikan is a public mirror that returns the same `mal_id` values, so the resulting XML imports cleanly.
- **State in a global module dict for the web UI.** Single-user local app; sessions and databases would be overkill. The state persists across HTTP requests via simple module-level scope.
- **Helper functions modify state and return True/False.** Routes orchestrate; helpers don't know about Flask. Clear separation between business logic and HTTP layer.

## Development mode

For iterating on the web UI without burning Gemini quota, the app supports a local cache:

- Set `DEV_MODE = True` at the top of `web.py`
- The first successful Gemini run is saved to `gemini_cache.json`
- Subsequent runs of `/empezar` read from cache instead of calling Gemini

The cache file is in `.gitignore` and should not be committed.

## File structure

```
.
├── web.py                  # Flask app (entry point for web UI)
├── main.py                 # CLI orchestrator
├── normalizer_gemini.py    # Gemini batch normalization
├── jikan_client.py         # Jikan search wrapper
├── mal_client.py           # Fallback MAL search (currently inactive)
├── resolver.py             # CLI interactive menus
├── retry.py                # Retry wrapper with exponential backoff
├── exporter.py             # File I/O (read list, write XML, write error log)
├── templates/              # Jinja2 templates for web UI
│   ├── inicio.html
│   ├── menu_gemini.html
│   ├── menu_jikan.html
│   └── listo.html
├── anime_list.txt          # Input (gitignored)
├── output.xml              # Output (gitignored)
└── errores.txt             # Error log (gitignored)
```

## Rate limits

- **Gemini 2.5 Flash free tier**: 5 RPM, 20 RPD. Hence the 13s sleep between batches.
- **Jikan**: ~3 req/sec, no documented daily cap.

If you have 300+ titles, expect the initial normalization phase to take ~3-5 minutes.

## TODOs

- [ ] Reset button to clear state without restarting the server
- [ ] Guard rails for routes accessed without going through `/empezar`
- [ ] Refactor `web.py` into separate modules (`app.py`, `processing.py`, `state.py`)
- [ ] Extract shared CSS into `static/styles.css`
- [ ] Use Jinja2 template inheritance for a shared base layout
- [ ] Type hints across helper functions
- [ ] Cache Jikan results during a single run to avoid duplicate searches when the user goes back

## License

MIT