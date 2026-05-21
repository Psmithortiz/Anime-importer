import json
from google import genai
from dotenv import load_dotenv
import re

load_dotenv()
client = genai.Client()


class BatchValidationError(Exception):
    pass


def normalize_titles(titles: list[str]) -> list[dict]:
    titulos_numerados = "\n".join(f"{i}. {titulo}" for i, titulo in enumerate(titles, start=1))

    prompt = f"""You are an expert anime title normalizer.
    
    CRITICAL CONTEXT: The user has personally watched every title in this list. 
    THEREFORE, EVERY ITEM IS A CONFIRMED ANIME. Your task is ONLY to normalize the spelling to the official japanese Romaji title used in MyAnimeList.

    For each input title, return a JSON object:
    - "n": input number (integer).
    - "romaji": official romaji title (string).
    - "is_anime": ALWAYS true (since all inputs are confirmed by the user).
    - "ambiguous": true ONLY if the input could refer to different seasons or separate entries (e.g., "Naruto" vs "Naruto Shippuden").
    - "options": array of romaji/title candidates if ambiguous=true.

    STRICT RULES:
    1. NEVER return "is_anime": false.
    2. If a title has notes like "MANGA?", "S1 S2", or "Novela", ignore the note and normalize the main title.
    3. Use Google Search to find the exact japanese Romaji/Title string for titles you don't recognize.
    4. Output raw JSON array only.
    Now normalize these titles:

{titulos_numerados}
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={
            "tools": [{"google_search": {}}],
            "temperature": 0.1
        }
    )
    text = response.text.strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    data = json.loads(text)
    if not isinstance(data, list):
        raise BatchValidationError("No es una lista")
    if len(data) != len(titles):
        raise BatchValidationError(f"Lista incompleta, esperados: {len(titles)}, recibidos: {len(data)}")
    esperados = set(range(1, len(titles) + 1))
    recibidos = {item["n"] for item in data}
    if esperados != recibidos:
        raise BatchValidationError(f"Faltan: {esperados - recibidos}, sobran:{recibidos - esperados}")
    return data
