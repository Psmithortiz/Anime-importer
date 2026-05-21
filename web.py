import json
import os
from flask import Flask, redirect, render_template, send_file
from exporter import read_list, export_xml, write_bad_list
from flow import procesar_hasta_proxima_pregunta, buscar_jikan_y_resolver
from processing import normalizar_lista_completa

from state import estado_inicial

DEV_MODE = False
estado = estado_inicial()
app = Flask(__name__)


@app.route("/")
def inicio():
    return render_template("inicio.html")


@app.route("/empezar")
def empezar():
    try:
        titles = read_list("anime_list.txt")
        estado["titulos_originales"] = titles
    except Exception as e:
        return f"Error al leer archivo: {e}"
    if DEV_MODE and os.path.exists("gemini_cache.json"):
        with open("gemini_cache.json", "r", encoding="utf-8") as f:
            cache = json.load(f)
        estado["datos_gemini"] = {int(k): v for k, v in cache.items()}
        procesar_hasta_proxima_pregunta(estado)
        return redirect("/preguntar")
    data_por_n, error = normalizar_lista_completa(titles)
    if error:
        return error
    estado["datos_gemini"] = data_por_n
    if DEV_MODE:
        with open("gemini_cache.json", "w", encoding="utf-8") as f:
            json.dump(estado["datos_gemini"], f, ensure_ascii=False, indent=2)
    procesar_hasta_proxima_pregunta(estado)
    return redirect("/preguntar")


@app.route("/preguntar")
def preguntar():
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
    i = estado["indice_actual"]
    original_title = estado["titulos_originales"][i - 1]
    if numero == 0:
        estado["lista_malos"].append((original_title, "Descartado en menú Gemini"))
        procesar_hasta_proxima_pregunta(estado)
        return redirect("/preguntar")
    opciones = estado["opciones_actuales"]
    if numero < 1 or numero > len(opciones):
        return "Opción fuera de rango"
    romaji_elegido = opciones[numero - 1]
    if not buscar_jikan_y_resolver(estado, romaji_elegido, original_title):
        return redirect("/preguntar")
    procesar_hasta_proxima_pregunta(estado)
    return redirect("/preguntar")


@app.route("/elegir-jikan/<int:numero>")
def elegir_jikan(numero):
    i = estado["indice_actual"]
    original_title = estado["titulos_originales"][i - 1]
    if numero == 0:
        romaji = estado["romaji_actual"]
        estado["lista_malos"].append(
            (original_title, f"Descartado en menú Jikan (romaji: {romaji})")
        )
        procesar_hasta_proxima_pregunta(estado)
        return redirect("/preguntar")
    opciones = estado["opciones_actuales"]
    if numero < 1 or numero > len(opciones):
        return "Opción fuera de rango"
    elegido = opciones[numero - 1]
    estado["acumulador"].append((elegido["id"], elegido["title"]))
    procesar_hasta_proxima_pregunta(estado)
    return redirect("/preguntar")


@app.route("/listo")
def listo():
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


@app.route("/reset")
def reset():
    global estado
    estado = estado_inicial()
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)
