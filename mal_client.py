# Fallback search backend - currently inactive.
# Switch in main.py by commenting `from jikan_client...` and uncommenting `from mal_client...`
# Use when Jikan is down or returns inconsistent results.

import requests
import os
from dotenv import load_dotenv
import re

load_dotenv()
llave = os.getenv("MAL_CLIENT_ID")
headers = {"X-MAL-CLIENT-ID": llave}

def search_anime(query):
    lista = []
    query = re.sub(r"[^a-zA-Z0-9 ]", "", query)
    query = query[:64]
    url = "https://api.myanimelist.net/v2/anime?"
    params = {"q": query, "limit": 90}
    timeout = (10, 120)
    r = requests.get(url, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
        #GUARDAR EN LISTA
    for i in data["data"]:
        id = (i["node"]["id"])
        title = (i["node"]["title"])
        main_pic = i["node"].get("main_picture", {})
        imagen = main_pic.get("large", None)
        anime = {"id": id, "title": title, "imagen": imagen}
        lista.append(anime)
    return lista