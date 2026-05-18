import sys
import time
from exporter import read_list, export_xml, write_bad_list
from resolver import resolve_title, select_from_results
from retry import intentar
from tqdm import tqdm
from normalizer_gemini import normalize_titles


from jikan_client import search_anime

# from mal_client import search_anime    # fallback - swap if Jikan fails

acumulador = []
lista_malos = []
titles = read_list("anime_list.txt")

CHUNK_SIZE = 20
data_total = []  # ACUMULADOR DE LOS CHUNKS

total_chunks = (len(titles) + CHUNK_SIZE - 1) // CHUNK_SIZE  # techo para la barra

# Itera de 0 a len(titles) con saltos de CHUNK_SIZE
for inicio in tqdm(range(0, len(titles), CHUNK_SIZE), total=total_chunks, desc="Normalizando"):
    fin = inicio + CHUNK_SIZE
    chunk = titles[inicio:fin]
    resultado_chunk, error = intentar(normalize_titles, chunk)
    if error:
        print(f"Fallo la normalizacion del chunk{inicio}-{fin}: {error}")
        sys.exit(1)
    for item in resultado_chunk:
        item["n"] = item["n"] + inicio
    data_total.extend(resultado_chunk)
    time.sleep(13)
data_por_n = {item["n"]: item for item in data_total}

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
