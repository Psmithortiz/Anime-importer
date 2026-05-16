import json
from google import genai
from dotenv import load_dotenv

load_dotenv()
client = genai.Client()


def normalize_title(title):
    prompt = f""" You are an anime title normalizer. Given a title in any language (Spanish, English, romaji, or mixed), return ONLY a JSON object with no extra text, no markdown, no backticks.

    The JSON must have exactly these fields:
    - "romaji": the official romaji title (string or null if ambiguous/not anime)
    - "ambiguous": true if the title could refer to multiple different anime series
    - "is_anime": true if this is a real anime title
    - "options": list of romaji titles if ambiguous, empty list otherwise

    Title to normalize: "{title}" """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"}
    )
    data = json.loads(response.text)
    return data