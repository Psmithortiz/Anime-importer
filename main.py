from exporter import read_list, export_xml
from mal_client import search_anime
from resolver import resolve_title, select_from_results

acumulador = []
titles = read_list("anime_list.txt")
for title in titles:
    acumulador.append(select_from_results(search_anime(resolve_title(title)), title))
export_xml(acumulador, "output.xml")
print(acumulador)
