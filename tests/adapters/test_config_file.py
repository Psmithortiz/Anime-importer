import json
import os
import sys

import pytest

from anime_importer.adapters import config_file
from anime_importer.adapters.config_file import read_config, save_config


def test_read_missing_file_is_empty(tmp_path):
    assert read_config(tmp_path / "nope.json") == {}


def test_save_creates_parent_folder_and_merges(tmp_path):
    path = tmp_path / "a" / "b" / "config.json"

    save_config(path, {"gemini_api_key": "g"})
    save_config(path, {"mal_client_id": "m"})
    save_config(path, {"gemini_api_key": "g2"})

    assert json.loads(path.read_text()) == {"gemini_api_key": "g2", "mal_client_id": "m"}
    assert not path.with_name("config.json.tmp").exists()


def test_save_keeps_the_original_when_the_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"mal_client_id": "old"}')

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(config_file.os, "replace", boom)

    with pytest.raises(OSError):
        save_config(path, {"mal_client_id": "new"})

    assert json.loads(path.read_text()) == {"mal_client_id": "old"}
    assert not path.with_name("config.json.tmp").exists()


def test_save_rejects_an_invalid_existing_file_without_touching_it(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1]")

    with pytest.raises(ValueError, match="config.json"):
        save_config(path, {"a": "b"})

    assert path.read_text() == "[1]"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_saved_file_is_private(tmp_path):
    path = tmp_path / "config.json"

    save_config(path, {"gemini_api_key": "secret"})

    assert os.stat(path).st_mode & 0o777 == 0o600
