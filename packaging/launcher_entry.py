"""PyInstaller entry point. Kept separate so launcher.py is not imported twice (as __main__ too)."""

from anime_importer.launcher import run_frozen_safe

if __name__ == "__main__":
    run_frozen_safe()
