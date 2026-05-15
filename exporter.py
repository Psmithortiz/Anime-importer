import xml.etree.ElementTree as ET

def read_list(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        datos = f.readlines()
        datos_limpios = [s.strip() for s in datos]
        return datos_limpios



def export_xml(ids, filepath):
    root = ET.Element("myanimelist")
    tree = ET.ElementTree(root)
    for id in ids:
        anime = ET.SubElement(root, "anime")           # crea <anime>
        ET.SubElement(anime, "series_animedb_id").text = str(id)  # crea <series_animedb_id>1735</series_animedb_id>
        ET.SubElement(anime, "my_status").text = "Completed"
        ET.SubElement(anime, "update_on_import").text = "1"
    ET.indent(tree)
    tree.write(filepath, encoding="utf-8", xml_declaration=True)
#Testing
if __name__ == "__main__":
    print (read_list("anime_list.txt"))
    export_xml([1735, 5114], "output.xml")