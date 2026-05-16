import json
import requests
import os
from dotenv import load_dotenv

load_dotenv()
llave = os.getenv("OPENROUTER_API_KEY")

def normalize_title(title):
    prompt = f""" You are an anime title normalizer. Given a title in any language (Spanish, English, romaji, or mixed), return ONLY a JSON object with no extra text, no markdown, no backticks.
    
    The JSON must have exactly these fields:
    - "romaji": the official romaji title (string or null if ambiguous/not anime)
    - "ambiguous": true if the title could refer to multiple different anime series
    - "is_anime": true if this is a real anime title
    - "options": list of romaji titles if ambiguous, empty list otherwise
    
    Title to normalize: "{title}" """

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {llave}"},
        json={
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=120
    )
    response.raise_for_status()
    datos = response.json()
    respuesta = datos["choices"][0]["message"]["content"]
    data = json.loads(respuesta)
    return data
