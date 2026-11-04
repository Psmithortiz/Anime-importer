import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

from anime_importer.domain.models import ImportedAnime


def render_mal_xml(entries: Sequence[ImportedAnime]) -> bytes:
    root = ET.Element("myanimelist")
    myinfo = ET.SubElement(root, "myinfo")
    ET.SubElement(myinfo, "user_id").text = "0"
    ET.SubElement(myinfo, "user_name").text = "importer"
    ET.SubElement(myinfo, "user_export_type").text = "1"
    ET.SubElement(myinfo, "user_total_anime").text = str(len(entries))
    ET.SubElement(myinfo, "user_total_watching").text = "0"
    ET.SubElement(myinfo, "user_total_completed").text = str(len(entries))
    ET.SubElement(myinfo, "user_total_onhold").text = "0"
    ET.SubElement(myinfo, "user_total_dropped").text = "0"
    ET.SubElement(myinfo, "user_total_plantowatch").text = "0"
    for entry in entries:
        anime = ET.SubElement(root, "anime")
        ET.SubElement(anime, "series_animedb_id").text = str(entry.mal_id)
        ET.SubElement(anime, "series_title").text = entry.title
        ET.SubElement(anime, "my_status").text = "Completed"
        ET.SubElement(anime, "update_on_import").text = "1"
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def write_mal_xml(entries: Sequence[ImportedAnime], path: Path) -> None:
    path.write_bytes(render_mal_xml(entries))
