# Development

Back to the [README](../README.md). Installing and using the app is in [setup.md](setup.md).

## Get the code

**You need:** [uv](https://docs.astral.sh/uv/getting-started/installation/) and
[Git](https://git-scm.com/downloads). uv downloads Python 3.13 by itself if you don't have it.

```bash
git clone https://github.com/Psmithortiz/Anime-importer
cd Anime-importer
uv sync
```

`uv sync` installs the app and the development tools (pytest, ruff). The architecture and the
reasons behind it are in [design-decisions.md](design-decisions.md).

## Tests and lint

```bash
uv run pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

The suite runs without network access, API keys or real waits: adapters accept injected
sessions, clients, clocks and sleep functions.

The session repository is covered by contract tests: the same battery runs against the in-memory
and the SQLite implementations, so both are guaranteed to behave identically. SQLite-only tests
cover reopening a file, schema versions and cascading deletes.

## Continuous integration

- **CI** (`.github/workflows/ci.yml`) runs the three commands above on Ubuntu and Windows for every
  pull request, and builds the Docker image with a demo-mode smoke test.
- **Release** (`.github/workflows/release.yml`) runs when a `v*` tag is pushed. On Windows it checks
  that the tag matches the version in `pyproject.toml`, runs the tests, builds the executable, starts
  it in demo mode as a smoke test, and creates a draft release with the zip and its SHA-256 checksum.

## Build the Windows executable

```bash
uv run --group build pyinstaller packaging/anime-importer.spec --noconfirm
```

The result is in `dist/AnimeImporter/`. PyInstaller lives in a separate `build` dependency group, so
`uv sync` and the CI test job do not install it.

## Publish a release

1. Raise `version` in `pyproject.toml` and run `uv lock`; commit both files together (CI installs
   with `--locked` and fails if they differ).
2. Merge to `main` through a pull request.
3. Tag `main` and push the tag:

   ```bash
   git checkout main
   git pull
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. When the Release workflow finishes, download the zip from the draft release, test it, and click
   **Publish release**.

If the workflow fails, fix it through a pull request, delete the tag (`git push --delete origin
vX.Y.Z` and `git tag -d vX.Y.Z`) and the draft release if one was created, and tag again.

## Re-record the demo

Demo mode replays `src/anime_importer/adapters/demo_data/recording.json`. After changing
`demo_data/list.txt`, record it again with real API keys:

```bash
uv run python scripts/record_demo.py
```