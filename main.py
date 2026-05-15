from exporter import read_list, export_xml
from mal_client import search_anime
from resolver import resolve_title, select_from_results

acumulador = []
titles = read_list("anime_list.txt")

for title in titles:
    romaji = resolve_title(title)
    results = search_anime(romaji)
    acumulador.append(select_from_results(results, title, romaji))
export_xml(acumulador, "output.xml")
print(acumulador)
