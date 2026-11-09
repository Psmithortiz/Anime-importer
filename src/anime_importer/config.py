from pathlib import Path
from typing import Self

from platformdirs import user_cache_path, user_data_path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _data_dir() -> Path:
    """Per-user data folder. Computing the path does not create it."""
    return user_data_path("anime-importer", appauthor=False)


def _cache_dir() -> Path:
    """Per-user cache folder. Computing the path does not create it."""
    return user_cache_path("anime-importer", appauthor=False)


class Settings(BaseSettings):
    """Configuration read from environment variables and the .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_chunk_size: int = 20
    mal_client_id: str | None = None
    input_path: Path = Path("anime_list.txt")
    output_xml_path: Path = Path("output.xml")
    rejected_report_path: Path = Path("errores.txt")
    normalization_cache_dir: Path = Field(default_factory=lambda: _cache_dir() / "normalization")
    details_cache_path: Path = Field(default_factory=lambda: _cache_dir() / "mal_details.json")
    details_cache_ttl_days: float = 7
    franchise_max_nodes: int = 40
    resolution_buffer: int = 20
    host: str = "127.0.0.1"
    port: int = 8000
    demo: bool = False
    demo_delay_seconds: float = 0.3
    demo_data_dir: Path = Path(__file__).parent / "adapters" / "demo_data"
    database_path: Path = Field(default_factory=lambda: _data_dir() / "sessions.db")
    demo_database_path: Path = Field(default_factory=lambda: _data_dir() / "demo.db")

    @model_validator(mode="after")
    def _require_keys_unless_demo(self) -> Self:
        if self.demo:
            return self
        missing = [
            name
            for name, value in (
                ("GEMINI_API_KEY", self.gemini_api_key),
                ("MAL_CLIENT_ID", self.mal_client_id),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"Missing required settings: {', '.join(missing)}. "
                "Set them in the environment or .env, or use DEMO=1 to try the app without keys."
            )
        return self
