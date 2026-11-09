# PyInstaller spec (onedir). Build: uv run --group build pyinstaller packaging/anime-importer.spec
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is provided by PyInstaller)

a = Analysis(  # noqa: F821
    [str(root / "packaging" / "launcher_entry.py")],
    pathex=[str(root / "src")],
    # static/ and demo_data/ keep their relative paths: the code locates them with __file__.
    datas=collect_data_files("anime_importer"),
    hiddenimports=collect_submodules("uvicorn"),
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="AnimeImporter",
    console=True,
    upx=False,
    icon=str(root / "packaging" / "app.ico"),
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="AnimeImporter",
    upx=False,
)
# The demo launcher goes next to the .exe (not into _internal/), in local builds and in releases.
shutil.copy2(root / "packaging" / "AnimeImporter Demo.bat", Path(DISTPATH) / "AnimeImporter")  # noqa: F821
