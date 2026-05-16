import requests
import os
from dotenv import load_dotenv

load_dotenv()
llave = os.getenv("MAL_CLIENT_ID")
headers = {"X-MAL-CLIENT-ID": llave}

def search_anime(query):
    lista = []
    url = "https://api.myanimelist.net/v2/anime?"
    params = {"q": query,
              "limit": 30}
    timeout = (10, 120)
    r = requests.get(url, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    for i in data["data"]:
        id = i["node"]["id"]
        title = i["node"]["title"]
        imagen = i["node"]["main_picture"]["large"]
        anime = {"id": id, "title":title, "imagen":imagen}
        lista.append(anime)
    return lista

