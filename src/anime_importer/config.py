from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración leída de variables de entorno y del archivo .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    gemini_chunk_size: int = 20
    mal_client_id: str
    input_path: Path = Path("anime_list.txt")
    output_xml_path: Path = Path("output.xml")
    rejected_report_path: Path = Path("errores.txt")
    normalization_cache_dir: Path = Path(".cache/normalization")
