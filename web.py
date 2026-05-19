import json
import os

from flask import Flask, redirect, render_template, send_file
from exporter import read_list, export_xml, write_bad_list
from normalizer_gemini import normalize_titles
from retry import intentar
from jikan_client import search_anime
from thefuzz import process
import time

DEV_MODE = False

estado = {
    "titulos_originales": [],
    "datos_gemini": {},
    "indice_actual": 0,
    "fase": None,
    "opciones_actuales": [],
    "romaji_actual": None,
    "acumulador": [],
    "lista_malos": [],
}

app = Flask(__name__)


@app.route("/")
def inicio():
    return render_template("inicio.html")


@app.route("/empezar")
def empezar():
    global estado
    try:
        titles = read_list("anime_list.txt")
        estado["titulos_originales"] = titles
    except Exception as e:
        return f"Error al leer archivo: {e}"

    if DEV_MODE and os.path.exists("gemini_cache.json"):
        with open("gemini_cache.json", "r", encoding="utf-8") as f:
            cache = json.load(f)
        estado["datos_gemini"] = {int(k): v for k, v in cache.items()}
        procesar_hasta_proxima_pregunta()
        return redirect("/preguntar")

    CHUNK_SIZE = 20
    data_total = []

    for inicio_chunk in range(0, len(titles), CHUNK_SIZE):
        fin = inicio_chunk + CHUNK_SIZE
        chunk = titles[inicio_chunk:fin]

        resultado_chunk, error = intentar(normalize_titles, chunk)
        if error:
            return f"Fallo la normalización en el bloque {inicio_chunk}-{fin}: {error}"

        for item in resultado_chunk:
            item["n"] = item["n"] + inicio_chunk

        data_total.extend(resultado_chunk)
        if inicio_chunk + CHUNK_SIZE < len(titles):
            time.sleep(13)

    estado["datos_gemini"] = {item["n"]: item for item in data_total}

    if DEV_MODE:
        with open("gemini_cache.json", "w", encoding="utf-8") as f:
            json.dump(estado["datos_gemini"], f, ensure_ascii=False, indent=2)

    procesar_hasta_proxima_pregunta()
    return redirect("/preguntar")


def buscar_jikan_y_resolver(romaji, original_title):
    global estado
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


def procesar_hasta_proxima_pregunta():
    global estado
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
        if not buscar_jikan_y_resolver(romaji, original_title):
            return

    estado["fase"] = "terminado"
    return


@app.route("/preguntar")
def preguntar():
    global estado

    indice = estado["indice_actual"]
    titulo_original = ""
    if 0 < indice <= len(estado["titulos_originales"]):
        titulo_original = estado["titulos_originales"][indice - 1]

    if estado["fase"] == "gemini":
        return render_template(
            "menu_gemini.html",
            titulo=titulo_original,
            opciones=estado["opciones_actuales"]
        )

    elif estado["fase"] == "jikan":
        return render_template(
            "menu_jikan.html",
            titulo=titulo_original,
            romaji_sugerido=estado["romaji_actual"],
            opciones=estado["opciones_actuales"]
        )

    elif estado["fase"] == "terminado":
        return redirect("/listo")

    else:
        return "Error: fase desconocida o no iniciada"


@app.route("/elegir-gemini/<int:numero>")
def elegir_gemini(numero):
    global estado

    i = estado["indice_actual"]
    original_title = estado["titulos_originales"][i - 1]

    if numero == 0:
        estado["lista_malos"].append((original_title, "Descartado en menú Gemini"))
        procesar_hasta_proxima_pregunta()
        return redirect("/preguntar")

    opciones = estado["opciones_actuales"]
    if numero < 1 or numero > len(opciones):
        return "Opción fuera de rango"

    romaji_elegido = opciones[numero - 1]

    if not buscar_jikan_y_resolver(romaji_elegido, original_title):
        return redirect("/preguntar")

    procesar_hasta_proxima_pregunta()
    return redirect("/preguntar")


@app.route("/elegir-jikan/<int:numero>")
def elegir_jikan(numero):
    global estado

    i = estado["indice_actual"]
    original_title = estado["titulos_originales"][i - 1]

    if numero == 0:
        romaji = estado["romaji_actual"]
        estado["lista_malos"].append(
            (original_title, f"Descartado en menú Jikan (romaji: {romaji})")
        )
        procesar_hasta_proxima_pregunta()
        return redirect("/preguntar")

    opciones = estado["opciones_actuales"]
    if numero < 1 or numero > len(opciones):
        return "Opción fuera de rango"

    elegido = opciones[numero - 1]
    estado["acumulador"].append((elegido["id"], elegido["title"]))

    procesar_hasta_proxima_pregunta()
    return redirect("/preguntar")


@app.route("/listo")
def listo():
    global estado

    estado["lista_malos"].sort(key=lambda x: x[1])
    export_xml(estado["acumulador"], "output.xml")
    write_bad_list(estado["lista_malos"], "errores.txt")

    return render_template(
        "listo.html",
        total_ok=len(estado["acumulador"]),
        total_malos=len(estado["lista_malos"]),
        malos=estado["lista_malos"]
    )


@app.route("/descargar")
def descargar():
    return send_file("output.xml", as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)
