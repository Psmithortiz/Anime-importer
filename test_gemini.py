import os
from google import genai
from dotenv import load_dotenv


load_dotenv()
print("KEY que estoy usando:", os.getenv("GEMINI_API_KEY")[:20], "...")

client = genai.Client()

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Say hello in Spanish in one word."
)

print(response.text)
