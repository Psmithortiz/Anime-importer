"""Reading and writing the per-user JSON config file."""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def read_config(path: Path) -> dict[str, Any]:
    """Return the config file as a dict. A missing or empty file is an empty config.

    Raises ValueError (naming the file) if it cannot be read or is not a JSON object.
    """
    if not path.is_file():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content) if content.strip() else {}
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read the config file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"The config file {path} must contain a JSON object.")  # noqa: TRY004
    return data


def save_config(path: Path, updates: Mapping[str, str]) -> None:
    """Merge `updates` into the config file and write it atomically (.tmp + os.replace).

    The parent folder is created if needed. On POSIX the temporary file is created with mode
    0o600 BEFORE anything is written, so the keys are never readable by other users. On Windows
    the mode is ignored; the file inherits the ACL of the user's own folder.
    """
    merged = {**read_config(path), **updates}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)  # a leftover could have looser permissions
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
