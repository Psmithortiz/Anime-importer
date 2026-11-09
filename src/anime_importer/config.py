import json
import os
from pathlib import Path
from typing import Self

from platformdirs import user_cache_path, user_config_path, user_data_path
from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def _data_dir() -> Path:
    """Per-user data folder. Computing the path does not create it."""
    return user_data_path("anime-importer", appauthor=False)


def _cache_dir() -> Path:
    """Per-user cache folder. Computing the path does not create it."""
    return user_cache_path("anime-importer", appauthor=False)


def config_file_path() -> Path:
    """Path of the per-user config file. Computing the path does not create anything."""
    override = os.environ.get("ANIME_IMPORTER_CONFIG_FILE")
    if override:
        return Path(override)
    return user_config_path("anime-importer", appauthor=False) / "config.json"


def _check_config_file(path: Path) -> None:
    """Fail with a message naming the file if it exists but is not a JSON object."""
    if not path.is_file():
        return
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content) if content.strip() else {}
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read the config file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"The config file {path} must contain a JSON object.")  # noqa: TRY004


class Settings(BaseSettings):
    """Configuration from init values, environment, .env and the per-user config file."""

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

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        path = config_file_path()
        _check_config_file(path)
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            JsonConfigSettingsSource(settings_cls, json_file=path),
            file_secret_settings,
        )

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
                "Set them in the environment, in .env or in the config file, or use DEMO=1 to try the app without keys."
            )
        return self
