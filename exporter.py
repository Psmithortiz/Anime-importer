import xml.etree.ElementTree as ET

def read_list(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        datos = f.readlines()
        datos_limpios = [s.strip() for s in datos if s.strip()]
        return datos_limpios

def export_xml(animes, filepath):
    root = ET.Element("myanimelist")
    tree = ET.ElementTree(root)

    myinfo = ET.SubElement(root, "myinfo")
    ET.SubElement(myinfo, "user_id").text = "0"
    ET.SubElement(myinfo, "user_name").text = "importer"
    ET.SubElement(myinfo, "user_export_type").text = "1"
    ET.SubElement(myinfo, "user_total_anime").text = str(len(animes))
    ET.SubElement(myinfo, "user_total_watching").text = "0"
    ET.SubElement(myinfo, "user_total_completed").text = str(len(animes))
    ET.SubElement(myinfo, "user_total_onhold").text = "0"
    ET.SubElement(myinfo, "user_total_dropped").text = "0"
    ET.SubElement(myinfo, "user_total_plantowatch").text = "0"

    for id in animes:
        anime = ET.SubElement(root, "anime")
        ET.SubElement(anime, "series_animedb_id").text = str(id)
        ET.SubElement(anime, "my_status").text = "Completed"
        ET.SubElement(anime, "update_on_import").text = "1"
    ET.indent(tree)
    tree.write(filepath, encoding="utf-8", xml_declaration=True)

def write_bad_list(bad_data, filepath):
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("TITULO | MOTIVO DEL ERROR\n")
        f.write("-" * 30 + "\n")
        for title, reason in bad_data:
            f.write(f"{title} | {reason}\n")
