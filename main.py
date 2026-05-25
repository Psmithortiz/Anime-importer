import sys
import time
from exporter import read_list, export_xml, write_bad_list
from processing import normalizar_lista_completa
from resolver import resolve_title, select_from_results
from retry import intentar
from tqdm import tqdm

# anime clients
from jikan_client import search_anime

# from mal_client import search_anime    # fallback - swap if Jikan fails

acumulador: list[tuple[int, str]] = []
lista_malos: list[tuple[str, str]] = []
titles = read_list("anime_list.txt")

data_por_n, error = normalizar_lista_completa(titles)
if error:
    print(error)
    sys.exit(1)

# RESOLVER
for i, title in tqdm(enumerate(titles, start=1), total=len(titles)):
    romaji, status = resolve_title(title, data_por_n[i])
    if status != "ok":
        lista_malos.append((title, status))
        continue
    if not romaji:
        lista_malos.append((title, f"No estuvo entre opciones de LLM"))
        continue

    # SEARCH + ERRORES
    results, error = intentar(search_anime, romaji)
    if error:
        lista_malos.append((title, f"Error de red al buscar en MAL: {error}"))
        continue
    if not results:
        lista_malos.append((title, f"No encontrado en MAL (Query: {romaji})"))
        continue

    # SELECCIONANDO
    anime_data = select_from_results(results, title, romaji)
    if not anime_data:
        lista_malos.append((title, f"No estuvo entre 5 opciones de MAL, LLM output: {romaji}"))
        continue
    acumulador.append(anime_data)
    time.sleep(0.6)

# EXPORTANDO
export_xml(acumulador, "output.xml")
lista_malos.sort(key=lambda x: x[1])
write_bad_list(lista_malos, "errores.txt")
print(acumulador)
