# Setup and usage

Back to the [README](../README.md). Building, testing and CI are in [development.md](development.md).

This guide takes you from nothing installed to your list imported in MyAnimeList:

1. [Install](#1-install): pick one of four ways to run the app.
2. [Get your API keys](#2-get-your-api-keys), or skip them and try the demo.
3. [Import your list](#3-import-your-list) with the web app.

The [command line](#4-command-line) and the [reference](#5-reference) (configuration, file locations,
limits) come after.

## 1. Install

| Option | Best for | You need | Demo without keys |
| --- | --- | --- | --- |
| [Windows app](#windows-app) | Using it on Windows | Nothing else | Yes |
| [Docker](#docker) | macOS or Linux, or a quick look | Docker and Git | Yes (the default) |
| [uvx](#uvx) | Running it without keeping a copy of the code | uv and Git | Yes |
| [From source](#from-source) | Reading or changing the code | uv and Git | Yes |

**Demo mode** replays real Gemini and MyAnimeList responses recorded for a sample list. It needs no
API keys and no internet access to those APIs. The sample list is preloaded on the start screen;
titles outside it are not found. Every option below explains how to start it.

### Windows app

**You need:** Windows 10 or 11 (64-bit). Python is not needed.

1. Open the [latest release](https://github.com/Psmithortiz/Anime-importer/releases/latest).
2. Scroll down to **Assets** (click it if it is collapsed) and download
   `AnimeImporter-vX.Y.Z-windows-x64.zip`. Do not download "Source code": it does not contain the app.
3. Right-click the zip → **Extract All…** → **Extract**.
4. Open the extracted folder and the `AnimeImporter` folder inside it, then double-click
   `AnimeImporter.exe`.
5. If Windows shows **"Windows protected your PC"**, click **More info** → **Run anyway**. This appears
   because the app is not signed with a paid certificate, not because something is wrong with it.
   To check that the zip is the published one, see [Verify the download](#verify-the-download).

A console window opens, and then the app opens in your browser. If the browser does not open, copy
the address shown in the console (usually <http://127.0.0.1:8000/>) into your browser.

- **Keep the console open while you use the app.** Closing the browser tab does not stop it.
- **To stop it**, close the console window. Your sessions are saved; nothing is lost.
- **Keep the `.exe` next to its `_internal` folder.** To move it, move the whole `AnimeImporter`
  folder. To launch it from the desktop, right-click the `.exe` → **Show more options** →
  **Send to** → **Desktop (create shortcut)**.
- **If you open it again while it is running**, it opens a new browser tab instead of a second copy.

**Demo mode:** in the `AnimeImporter` folder, click the address bar of the File Explorer window, type
`powershell` and press Enter. In the window that opens, run:

```powershell
$env:DEMO="1"; .\AnimeImporter.exe
```

#### Verify the download

Download the `.sha256` file from the same release. Open PowerShell in the folder that has both files
(as above) and run:

```powershell
Get-FileHash .\AnimeImporter-vX.Y.Z-windows-x64.zip -Algorithm SHA256
```

Open the `.sha256` file with Notepad. The long code in it must be the same as the `Hash` shown by
PowerShell (PowerShell prints it in capital letters; that does not matter).

#### Update

Download the new zip and extract it. You can delete the old folder: your keys, sessions and caches
are not stored in it (see [Where files are stored](#where-files-are-stored)).

### Docker

**You need:**
[Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, macOS) or Docker Engine
with the Compose plugin (Linux), running; and [Git](https://git-scm.com/downloads). Python is not
needed.

1. **Get the code.** The image is built from the source, so you need a copy of the repository. In a
   terminal:

   ```bash
   git clone https://github.com/Psmithortiz/Anime-importer
   cd Anime-importer
   ```

2. **Start it**, from that folder:

   | | macOS / Linux (bash) | Windows (PowerShell) |
   | --- | --- | --- |
   | Demo, no keys | `docker compose up --build` | `docker compose up --build` |
   | With your keys | `DEMO=0 docker compose up --build` | `$env:DEMO="0"; docker compose up --build` |

   The first build takes a few minutes; later starts take seconds. When the log shows
   `Application startup complete`, open <http://127.0.0.1:8000> in your browser. With your keys, the
   app asks for them in its Settings screen (see [Get your API keys](#2-get-your-api-keys)).

3. **Stop it** with `Ctrl+C` in that terminal, or run `docker compose down` from the same folder in
   another terminal.

**Your data** lives in two Docker volumes and survives restarts and rebuilds:

- `cache`: the Gemini and MyAnimeList caches. It is safe to delete; rebuilding it only costs API quota.
- `data`: your API keys and your sessions. **`docker compose down -v` deletes it**, together with
  the cache. Use plain `docker compose down` to keep it.

**Update** to a newer version, from the same folder:

```bash
git pull
docker compose up --build
```

The app is published on `127.0.0.1` only, because it has no login: other devices on your network
cannot reach it.

### uvx

Runs the app straight from GitHub without keeping a copy of the code.

**You need:** [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Git](https://git-scm.com/downloads). uv downloads Python 3.13 by itself if you don't have it.

| | macOS / Linux (bash) | Windows (PowerShell) |
| --- | --- | --- |
| With your keys | `uvx --from git+https://github.com/Psmithortiz/Anime-importer anime-importer-web` | same command |
| Demo, no keys | `DEMO=1 uvx --from git+https://github.com/Psmithortiz/Anime-importer anime-importer-web` | `$env:DEMO="1"; uvx --from git+https://github.com/Psmithortiz/Anime-importer anime-importer-web` |

When the terminal shows `Application startup complete`, open <http://127.0.0.1:8000>. Stop it with
`Ctrl+C`. It does not matter which folder you run it from: keys, sessions and caches are stored in
your user folders.

To get the latest version, add `--refresh` after `uvx`.

### From source

**You need:** [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Git](https://git-scm.com/downloads). uv downloads Python 3.13 by itself if you don't have it.

```bash
git clone https://github.com/Psmithortiz/Anime-importer
cd Anime-importer
uv sync
```

Then, from that folder:

| Command | What it does |
| --- | --- |
| `uv run anime-importer-web` | Starts the web app at <http://127.0.0.1:8000>. Stop it with `Ctrl+C`. |
| `uv run anime-importer-app` | Same as the Windows app: picks a free port and opens your browser. |
| `uv run anime-importer` | The [command line](#4-command-line) version. |

For demo mode, put `DEMO=1 ` before the command (bash) or run `$env:DEMO="1"` first (PowerShell).
To update, run `git pull` and `uv sync`.

## 2. Get your API keys

Skip this section for demo mode.

The app needs two free keys. The first time you open it without them, it shows a **Settings** screen
with a field for each key and a link to where you get it.

**Gemini API key** (normalizes your titles):

1. Go to [Google AI Studio → API keys](https://aistudio.google.com/apikey) and sign in with a Google
   account.
2. Click **Create API key** and copy it.

**MyAnimeList client ID** (searches MyAnimeList):

1. Go to [MAL's API page](https://myanimelist.net/apiconfig) while signed in to MyAnimeList, and
   click **Create ID**.
2. Fill in the form. The app only reads public data, so the details barely matter: choose App Type
   **other**, and use any valid address as the redirect URL (for example `http://localhost`).
3. Submit, open the app you created and copy its **Client ID**. The client secret is not needed.

Paste both keys in the Settings screen and click **Save**. The app starts right away.

- The keys are saved in a config file in your user folder (see
  [Where files are stored](#where-files-are-stored)). Afterwards the screen only shows their last 4
  characters.
- To change them later, click **Settings** at the top right of the start screen. A changed key is
  used after you restart the app.
- Alternatively, set the environment variables `GEMINI_API_KEY` and `MAL_CLIENT_ID`. They take
  priority over the config file, and the Settings screen shows them as read-only. A `.env` file is
  **not** read.

## 3. Import your list

### Start

On the start screen, paste your list into the text box, one title per line, or click
**Choose File** and pick a `.txt` file. The counter below the box shows how many titles it found.
Typos, a mix of English, Spanish and romaji, and your own notes such as `S2 ***` or `MANGA?` are
fine: that is what the app is for. Click **Start import**.

### Wait while it prepares

Two progress bars appear:

1. **Normalizing with Gemini…**: Gemini cleans up the titles in groups of 20. A 300-title list takes
   a few minutes, because the free tier allows 5 requests per minute. Titles normalized in an
   earlier run come from the cache and are instant.
2. **Looking up on MAL…**: MyAnimeList is searched for the first titles (one request per second).

The first question appears once a few titles are ready. The rest are looked up in the background
while you answer, so most questions show up instantly. If you see "Looking up the next titles on
MAL…", you have caught up with it; wait a moment.

Titles that match a single MyAnimeList entry with certainty are imported without asking.

### Answer the questions

Each question shows the line from your list as its title, a progress counter (for example
`120 / 317`) and a **Search on Google** link in case you don't remember what the line meant. There
are two kinds:

**Which title should be searched?** Gemini was unsure how to read the line. You get a numbered list
of possible titles; the last one, **✎ Your line**, is your text exactly as you wrote it. Pick one and
confirm.

**Which MyAnimeList entries?** You get cards with poster, type (TV, Movie, OVA…), year, episodes and
tags such as **Best match**, **Airing** or **Not yet aired**.

- Select every entry you want to import: one season or several.
- If the title belongs to a franchise, a **Franchise** column on the right lists its other seasons,
  movies, OVAs and specials. Select any of them as well; this is how one line of your list can
  import a whole series.
- Each selected card has a list status (*Completed*, *Watching*, *Plan to Watch*, *On Hold*,
  *Dropped*). It is suggested from the airing status; change it if needed.
- If the app was sure about the match and only asks because of the franchise, the match is
  already selected.

Then confirm. In both kinds of question:

| Action | Mouse | Keyboard |
| --- | --- | --- |
| Select or unselect an option | Click it | `1`–`9` |
| Confirm | **Confirm selection** | `Enter` |
| Skip this line (it goes to the rejected list) | **Discard** | `X` |
| Go back to the previous answer | **Undo** | `Ctrl+Z` (`Cmd+Z` on macOS) |

Undo has no limit: you can go back as many answers as you want.

### Download and import into MyAnimeList

When there are no questions left, the **Import finished** screen shows how many entries were
imported, how many per list status, and the rejected lines with the reason.

1. Click **Download XML**. You get `anime_import.xml`. (Changed your mind about the last answer?
   **Undo last answer** still works here.)
2. Open [MyAnimeList's import page](https://myanimelist.net/import.php) while signed in.
3. Choose **MyAnimeList Import** and select `anime_import.xml`.
4. Check **Don't overwrite entries already on my list**. Without it, entries you already have are
   replaced with the status and data from the file.
5. Click **Import**.

![Import summary](finished.png)

### Close, resume and retry

- **You can stop at any time**, even in the middle of the questions: every answer is saved as you
  give it. When you open the app again, the session is listed under **Recent sessions** on the start
  screen; click it to continue where you left off.
- **If MyAnimeList fails** (it is down, or the connection drops), the screen says **The import
  failed**. Click **Retry** to continue from your last saved answer.
- **New import** goes back to the start screen. The current session stays in Recent sessions.

## 4. Command line

The command line version runs the same normalization and search in the terminal, with fewer features:
one choice per question, no franchise column, no list status choice (the suggested status is used),
no undo, and sessions are not saved. It is useful for scripts or for a quick run.

From a copy of the source (see [From source](#from-source)):

```bash
uv run anime-importer --input anime_list.txt --output output.xml
```

| Option | Default | What it is |
| --- | --- | --- |
| `--input` | `anime_list.txt` | Your list, one title per line |
| `--output` | `output.xml` | The MyAnimeList XML to import (same steps as in [Download and import](#download-and-import-into-myanimelist)) |
| `--rejected` | `errores.txt` | A report of the discarded and not found lines |

Each question prints numbered options: type a number and press Enter, or type `X` to discard the
line. There is no Settings screen: the keys must already be saved (from the web app) or set as
environment variables. Without them, the command names the missing ones and exits with code 2.

## 5. Reference

### Configuration

Settings are read in this order (highest priority first): environment variables, the config file,
and the defaults.

| Variable | Default | What it does |
| --- | --- | --- |
| `GEMINI_API_KEY`, `MAL_CLIENT_ID` | (none) | API keys (see [Get your API keys](#2-get-your-api-keys)) |
| `DEMO` | `0` | `1` starts demo mode |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model used to normalize |
| `GEMINI_CHUNK_SIZE` | `20` | Titles per Gemini request |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Address of the web server (`anime-importer-web`; the Windows app picks a free port if 8000 is taken) |
| `ALLOWED_HOSTS` | `["127.0.0.1","localhost"]` | Accepted `Host` headers (see [Host header check](#host-header-check)) |
| `NORMALIZATION_CACHE_DIR`, `DETAILS_CACHE_PATH`, `DATABASE_PATH`, `DEMO_DATABASE_PATH`, `ANIME_IMPORTER_CONFIG_FILE` | see below | File locations |

The config file is a JSON object such as `{"gemini_api_key": "...", "mal_client_id": "..."}`. The
Settings screen writes it for you. A missing config file is ignored; an invalid one stops the app
with an error that names it. A `.env` file is not read.

### Where files are stored

Keys, sessions and caches live in per-user folders, never in the folder you run the app from. Folders
are created when something is first written.

| What | Windows | Linux | macOS | Variable to change it |
| --- | --- | --- | --- | --- |
| Config file (your keys) | `%LOCALAPPDATA%\anime-importer\config.json` | `~/.config/anime-importer/config.json` | `~/Library/Application Support/anime-importer/config.json` | `ANIME_IMPORTER_CONFIG_FILE` |
| Sessions (`sessions.db`; `demo.db` in demo mode) | `%LOCALAPPDATA%\anime-importer` | `~/.local/share/anime-importer` | `~/Library/Application Support/anime-importer` | `DATABASE_PATH`, `DEMO_DATABASE_PATH` |
| Normalization cache | `%LOCALAPPDATA%\anime-importer\Cache\normalization` | `~/.cache/anime-importer/normalization` | `~/Library/Caches/anime-importer/normalization` | `NORMALIZATION_CACHE_DIR` |
| MyAnimeList details cache | `mal_details.json` in the same cache folder | same | same | `DETAILS_CACHE_PATH` |

To open the Windows folder, press `Win+R`, type `%LOCALAPPDATA%\anime-importer` and press Enter. In
Docker, these files live in the volumes (see [Docker](#docker)).

The location is fixed on purpose: with `uvx` the app can be started from any folder, and a fixed
location keeps Recent sessions complete wherever you launch it. Deleting the cache folders is safe
(it only costs API quota); deleting the config file or the sessions file loses your keys or sessions.

### The Settings screen

It shows where each key comes from (environment variable or config file) and the last 4 characters
of the saved key, never the full value. A key that comes from the environment cannot be edited there
(it would be overridden anyway): change it where it is defined. If every key comes from the
environment, the screen says so and **Save** is disabled. The **Settings** link is hidden in demo
mode.

If the app started without keys, saving them starts it right away. If it was already configured,
the new keys are saved but the running app keeps the old ones until you restart it: the adapters
(MyAnimeList throttle, caches) are built once per app, and a second set would share neither.

The config file is created with owner-only permissions on Linux and macOS; on Windows it inherits the
permissions of your user folder.

### Host header check

The web server only answers requests whose `Host` header is `127.0.0.1` or `localhost`. This protects
your keys and sessions from DNS rebinding (a web page making your browser talk to the local server
under another name). If you expose the app under another name, add it with `ALLOWED_HOSTS` as a JSON
list, for example `ALLOWED_HOSTS='["127.0.0.1","localhost","anime.lan"]'`.

### Rate limits

- **Gemini 2.5 Flash, free tier**: 5 requests per minute and 20 per day. With the default chunk size
  a request covers 20 titles, so a 317-title list takes 16 requests and the daily quota covers about
  400 titles. If the quota runs out, wait until the next day (or use another key) and start the list
  again: everything already normalized is cached and does not use quota again.
- **MyAnimeList API**: requests are throttled to one per second.

### Upgrading from an earlier version

If you used a `.env` file, it is no longer read: paste your keys in the Settings screen (or use
environment variables).

Caches used to live in `.cache/` inside the folder where the app was run. To keep them (and not
spend Gemini quota again), move the contents of `.cache/normalization` and the file
`.cache/mal_details.json` to the new cache folder (see
[Where files are stored](#where-files-are-stored)). Nothing is migrated automatically.

### Known limitations

- The Windows app (and `anime-importer-app`) only detects an already running copy on port 8000. If
  another program uses 8000, every launch opens a new copy on a free port. SQLite in WAL mode
  prevents corruption, but it is best to use a single window.