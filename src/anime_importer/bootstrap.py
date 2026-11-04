from collections.abc import Sequence

from google import genai

from anime_importer.adapters.gemini import GeminiNormalizer, cache_version
from anime_importer.adapters.mal import MalSearcher
from anime_importer.adapters.normalization_cache import CachingNormalizer, JsonCacheStore
from anime_importer.config import Settings
from anime_importer.services.import_session import ImportSession


def build_session(settings: Settings, titles: Sequence[str]) -> ImportSession:
    """Raíz de composición: el único lugar que decide qué adaptadores concretos se usan."""
    client = genai.Client(api_key=settings.gemini_api_key)
    gemini = GeminiNormalizer(
        client=client, model=settings.gemini_model, chunk_size=settings.gemini_chunk_size
    )
    store = JsonCacheStore(
        settings.normalization_cache_dir / f"{cache_version(settings.gemini_model)}.json"
    )
    normalizer = CachingNormalizer(inner=gemini, store=store)
    return ImportSession(
        titles, normalizer=normalizer, searcher=MalSearcher(client_id=settings.mal_client_id)
    )
