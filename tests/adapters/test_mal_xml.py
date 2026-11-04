import xml.etree.ElementTree as ET

from anime_importer.adapters.mal_xml import render_mal_xml, write_mal_xml
from anime_importer.domain.models import ImportedAnime, ListStatus


def test_render_two_entries():
    entries = [ImportedAnime(1, "Cowboy Bebop"), ImportedAnime(20, "Naruto")]
    root = ET.fromstring(render_mal_xml(entries))

    assert root.findtext("myinfo/user_total_anime") == "2"
    assert root.findtext("myinfo/user_total_completed") == "2"
    animes = root.findall("anime")
    assert [a.findtext("series_animedb_id") for a in animes] == ["1", "20"]
    assert [a.findtext("series_title") for a in animes] == ["Cowboy Bebop", "Naruto"]
    assert all(a.findtext("my_status") == "Completed" for a in animes)
    assert all(a.findtext("update_on_import") == "1" for a in animes)


def test_render_empty():
    root = ET.fromstring(render_mal_xml([]))

    assert root.findtext("myinfo/user_total_anime") == "0"
    assert root.findtext("myinfo/user_total_completed") == "0"
    assert root.findall("anime") == []


def test_render_escapes_special_characters():
    title = "Re:Zero & <Kara>"
    root = ET.fromstring(render_mal_xml([ImportedAnime(1, title)]))

    assert root.findtext("anime/series_title") == title


def test_render_declares_utf8():
    assert render_mal_xml([]).startswith(b"<?xml version='1.0' encoding='utf-8'?>")


def test_write_mal_xml(tmp_path):
    path = tmp_path / "output.xml"
    entries = [ImportedAnime(1, "Cowboy Bebop")]
    write_mal_xml(entries, path)

    assert path.read_bytes() == render_mal_xml(entries)


def test_render_statuses_and_totals():
    entries = [
        ImportedAnime(1, "A", ListStatus.COMPLETED),
        ImportedAnime(2, "B", ListStatus.WATCHING),
        ImportedAnime(3, "C", ListStatus.PLAN_TO_WATCH),
        ImportedAnime(4, "D", ListStatus.ON_HOLD),
        ImportedAnime(5, "E", ListStatus.DROPPED),
        ImportedAnime(6, "F", ListStatus.WATCHING),
    ]
    root = ET.fromstring(render_mal_xml(entries))

    statuses = [a.findtext("my_status") for a in root.findall("anime")]
    assert statuses == [
        "Completed",
        "Watching",
        "Plan to Watch",
        "On-Hold",
        "Dropped",
        "Watching",
    ]
    assert root.findtext("myinfo/user_total_anime") == "6"
    assert root.findtext("myinfo/user_total_completed") == "1"
    assert root.findtext("myinfo/user_total_watching") == "2"
    assert root.findtext("myinfo/user_total_plantowatch") == "1"
    assert root.findtext("myinfo/user_total_onhold") == "1"
    assert root.findtext("myinfo/user_total_dropped") == "1"


def test_update_on_import_is_always_one():
    # MAL ignores entries with 0; protecting the list is MAL's own checkbox.
    root = ET.fromstring(render_mal_xml([ImportedAnime(1, "A"), ImportedAnime(2, "B")]))

    assert [a.findtext("update_on_import") for a in root.findall("anime")] == ["1", "1"]
