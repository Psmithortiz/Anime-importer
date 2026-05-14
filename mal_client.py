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
              "limit": 5}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()

    for i in data["data"]:
        id = i["node"]["id"]
        title = i["node"]["title"]
        imagen = i["node"]["main_picture"]["large"]
        anime = {"id": id, "title":title, "imagen":imagen}
        lista.append(anime)
    return lista

#Testing
if __name__ == "__main__":
    query = "naruto"
    lista =search_anime(query)
    print(lista)