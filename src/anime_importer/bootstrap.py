from collections.abc import Sequence

from google import genai

from anime_importer.adapters.gemini import GeminiNormalizer
from anime_importer.adapters.mal import MalSearcher
from anime_importer.config import Settings
from anime_importer.services.import_session import ImportSession


def build_session(settings: Settings, titles: Sequence[str]) -> ImportSession:
    """Raíz de composición: el único lugar que decide qué adaptadores concretos se usan."""
    client = genai.Client(api_key=settings.gemini_api_key)
    normalizer = GeminiNormalizer(client=client, model=settings.gemini_model)
    return ImportSession(
        titles, normalizer=normalizer, searcher=MalSearcher(client_id=settings.mal_client_id)
    )
