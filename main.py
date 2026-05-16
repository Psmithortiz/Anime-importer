import sys

from exporter import read_list, export_xml, write_bad_list
from mal_client import search_anime
from normalizer_gemini import normalize_titles
from resolver import resolve_title, select_from_results
from retry import intentar
from tqdm import tqdm
import time

acumulador = []
lista_malos = []

titles = read_list("anime_list.txt")


CHUNK_SIZE = 20
data_total= [] #ACUMULADOR DE LOS CHUNKS
INICIO= 0

# Itera de 0 a len(titles) con saltos de CHUNK_SIZE
for inicio in range(INICIO, len(titles), CHUNK_SIZE):
    fin = inicio + CHUNK_SIZE
    chunk = titles[inicio:fin]
    resultado_chunk, error = intentar(normalize_titles,chunk) #intenta normalizar 20 ES UNA LAVADORA DE 20 KILOS
    if error:
        print(f"Fallo la normalizacion del chunk{inicio}-{fin}: {error}")
        sys.exit(1)

    for item in resultado_chunk:
        item["n"] = item["n"] + inicio # =0 priemr run
    data_total.extend(resultado_chunk)

data_por_n = {item["n"]: item for item in data_total}
for i, title in tqdm(enumerate(titles, start=1), total=len(titles)):
    romaji, status = resolve_title(title, data_por_n[i])
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
    anime_data = select_from_results(results, title, romaji)
    acumulador.append(anime_data)
    time.sleep(3)

export_xml(acumulador, "output.xml")
write_bad_list(lista_malos, "errores.txt")
print(acumulador)
