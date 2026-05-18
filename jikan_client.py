import requests
import time
import re

URL_BASE = "https://api.jikan.moe/v4/anime"


def search_anime(query):
    lista = []
    query = re.sub(r"[^a-zA-Z0-9 ]", "", query)
    query = query[:64]

    params = {
        "q": query,
        "limit": 25
    }

    try:
        response = requests.get(URL_BASE, params=params, timeout=(10, 120))

        if response.status_code == 429:
            print("Rate limit de Jikan (429). Reintentando...")
            time.sleep(2)
            return search_anime(query)

        response.raise_for_status()
        data = response.json()

        for item in data.get("data", []):
            #PROTECCION NO IMAGEN
            images_data = item.get("images", {})
            img_formats = images_data.get("webp") or images_data.get("jpg") or {}
            imagen = img_formats.get("large_image_url") or img_formats.get("image_url")

            lista.append({
                "id": item["mal_id"],
                "title": item["title"],
                "imagen": imagen
            })

    except Exception as e:
        print(f"Error en Jikan para '{query}': {e}")

    return lista