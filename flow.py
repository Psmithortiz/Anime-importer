from jikan_client import search_anime
from retry import intentar
from thefuzz import process


def buscar_jikan_y_resolver(estado, romaji: str, original_title: str) -> bool:
    results, error = intentar(search_anime, romaji)
    if error:
        estado["lista_malos"].append((original_title, f"Error de red Jikan: {error}"))
        return True
    if not results:
        estado["lista_malos"].append((original_title, f"No encontrado en Jikan (query: {romaji})"))
        return True
    match = process.extractOne(romaji, [a["title"] for a in results])
    if match[1] >= 95:
        matched_anime = next(a for a in results if a["title"] == match[0])
        estado["acumulador"].append((matched_anime["id"], matched_anime["title"]))
        return True
    top_5_matches = process.extract(romaji, [a["title"] for a in results], limit=5)
    top_5_animes = [next(a for a in results if a["title"] == titulo)
                    for titulo, score in top_5_matches]
    estado["fase"] = "jikan"
    estado["opciones_actuales"] = top_5_animes
    estado["romaji_actual"] = romaji
    return False


def procesar_hasta_proxima_pregunta(estado) -> None:
    while estado["indice_actual"] < len(estado["titulos_originales"]):
        estado["indice_actual"] += 1
        i = estado["indice_actual"]
        original_title = estado["titulos_originales"][i - 1]
        data = estado["datos_gemini"].get(i)
        if not data:
            estado["lista_malos"].append((original_title, "No hay datos de Gemini"))
            continue
        if not data.get("is_anime", True):
            estado["lista_malos"].append((original_title, "No es un anime (según Gemini)"))
            continue
        if data.get("ambiguous"):
            estado["fase"] = "gemini"
            estado["opciones_actuales"] = data.get("options", [])
            return
        romaji = data.get("romaji")
        estado["romaji_actual"] = romaji
        if not buscar_jikan_y_resolver(estado, romaji, original_title):
            return
    estado["fase"] = "terminado"
    return
