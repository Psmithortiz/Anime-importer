from exporter import read_list, export_xml, write_bad_list
from mal_client import search_anime
from resolver import resolve_title, select_from_results
from retry import intentar

acumulador = []
lista_malos = []
titles = read_list("anime_list.txt")

for title in titles:
    romaji, status = resolve_title(title)
    if status != "ok":
        lista_malos.append((title, status))
        continue
    results, error = intentar(search_anime, romaji)
    if error:
        lista_malos.append((title, f"Error de red al buscar en MAL: {error}"))
        continue
    if not results:
        lista_malos.append((title, f"No encontrado en MAL (Query: {romaji})"))
        continue
    anime_id = select_from_results(results, title, romaji)
    acumulador.append(anime_id)

export_xml(acumulador, "output.xml")
write_bad_list(lista_malos, "errores.txt")
print(acumulador)
