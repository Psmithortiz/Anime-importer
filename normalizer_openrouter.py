import json
import requests
import os
from dotenv import load_dotenv
from normalizer_gemini import BatchValidationError

load_dotenv()
llave = os.getenv("OPENROUTER_API_KEY")


def normalize_titles(titles: list[str]) -> list[dict]:
    titulos_numerados = "\n".join(f"{i}. {titulo}" for i, titulo in enumerate(titles, start=1))

    prompt = f"""You are an anime title normalizer. You will receive a numbered list of anime titles written with typos, in Spanish, English, or romaji. Normalize each one to its official romaji title.

For each input title, return a JSON object with these fields:
- "n": input number (integer, must match the number in the input)
- "romaji": official romaji title (string), or null if not an anime or unrecognized
- "is_anime": true if it's an anime, false if it's manga/non-anime film/unrecognized
- "ambiguous": true if the title could refer to multiple distinct anime (e.g. "Naruto" could be the original series or Shippuden)
- "options": array of romaji candidate titles if ambiguous=true, empty array otherwise

STRICT RULES:
1. Return a JSON array with EXACTLY one object per input.
2. Each object's "n" field must match the input number.
3. Do not add comments, explanations, or any text outside the JSON array.
4. If you don't recognize a title, still include its object with romaji=null and is_anime=false.

EXAMPLE:

Input:
1. narrutto
2. cowboy bebop
3. xyzqwerty random

Output:
[
  {{"n": 1, "romaji": "Naruto", "is_anime": true, "ambiguous": true, "options": ["Naruto", "Naruto: Shippuden"]}},
  {{"n": 2, "romaji": "Cowboy Bebop", "is_anime": true, "ambiguous": false, "options": []}},
  {{"n": 3, "romaji": null, "is_anime": false, "ambiguous": false, "options": []}}
]

Now normalize these titles:

{titulos_numerados}
"""

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {llave}"},
        json={
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        },
        timeout=120
    )
    response.raise_for_status()
    datos = response.json()
    respuesta = datos["choices"][0]["message"]["content"]
    data = json.loads(respuesta)

    if not isinstance(data, list):
        raise BatchValidationError("No es una lista")

    if len(data) != len(titles):
        raise BatchValidationError(f"Lista incompleta, esperados: {len(titles)}, recibidos: {len(data)}")

    esperados = set(range(1, len(titles) + 1))
    recibidos = {item["n"] for item in data}

    if esperados != recibidos:
        raise BatchValidationError(f"Faltan: {esperados - recibidos}, sobran:{recibidos - esperados}")

    return data