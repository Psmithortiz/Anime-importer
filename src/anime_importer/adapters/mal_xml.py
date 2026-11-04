import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from anime_importer.domain.models import ImportedAnime, ListStatus

_MY_STATUS = {
    ListStatus.COMPLETED: "Completed",
    ListStatus.WATCHING: "Watching",
    ListStatus.PLAN_TO_WATCH: "Plan to Watch",
    ListStatus.ON_HOLD: "On-Hold",
    ListStatus.DROPPED: "Dropped",
}


def render_mal_xml(entries: Sequence[ImportedAnime]) -> bytes:
    """Render the import file. MAL ignores entries with update_on_import=0, so it is always 1;
    keeping the current list untouched is done with the "Don't overwrite entries already on my
    list" checkbox on MAL's import page."""
    totals = Counter(entry.list_status for entry in entries)
    root = ET.Element("myanimelist")
    myinfo = ET.SubElement(root, "myinfo")
    ET.SubElement(myinfo, "user_id").text = "0"
    ET.SubElement(myinfo, "user_name").text = "importer"
    ET.SubElement(myinfo, "user_export_type").text = "1"
    ET.SubElement(myinfo, "user_total_anime").text = str(len(entries))
    ET.SubElement(myinfo, "user_total_watching").text = str(totals[ListStatus.WATCHING])
    ET.SubElement(myinfo, "user_total_completed").text = str(totals[ListStatus.COMPLETED])
    ET.SubElement(myinfo, "user_total_onhold").text = str(totals[ListStatus.ON_HOLD])
    ET.SubElement(myinfo, "user_total_dropped").text = str(totals[ListStatus.DROPPED])
    ET.SubElement(myinfo, "user_total_plantowatch").text = str(totals[ListStatus.PLAN_TO_WATCH])
    for entry in entries:
        anime = ET.SubElement(root, "anime")
        ET.SubElement(anime, "series_animedb_id").text = str(entry.mal_id)
        ET.SubElement(anime, "series_title").text = entry.title
        ET.SubElement(anime, "my_status").text = _MY_STATUS[entry.list_status]
        ET.SubElement(anime, "update_on_import").text = "1"
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_mal_xml(entries: Sequence[ImportedAnime], path: Path) -> None:
    path.write_bytes(render_mal_xml(entries))
