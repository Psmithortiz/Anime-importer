import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from dotenv import dotenv_values
from platformdirs import user_cache_path, user_config_path, user_data_path
from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from anime_importer.adapters.config_file import read_config


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
        read_config(path)  # fail early with a clear message
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            JsonConfigSettingsSource(settings_cls, json_file=path),
            file_secret_settings,
        )

    def missing_keys(self) -> list[str]:
        """Names of the required API keys that are not set. Always empty in demo mode."""
        if self.demo:
            return []
        return [name for name, value in self._keys() if not value]

    def _keys(self) -> tuple[tuple[str, str | None], ...]:
        return (
            ("GEMINI_API_KEY", self.gemini_api_key),
            ("MAL_CLIENT_ID", self.mal_client_id),
        )


class KeySource(StrEnum):
    ENVIRONMENT = "environment"
    DOTENV = "dotenv"
    CONFIG_FILE = "config_file"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class KeyStatus:
    name: str
    source: KeySource
    masked: str | None


def mask_key(value: str) -> str:
    """Hide a key, showing at most its last 4 characters (nothing if it has 8 or fewer)."""
    return "••••" + (value[-4:] if len(value) > 8 else "")


def key_status(
    settings: Settings,
    env_file: str | Path = ".env",
    config_path: Path | None = None,
) -> list[KeyStatus]:
    """Where each API key comes from, in priority order: environment, .env, config file.

    Never returns a full key.
    """
    dotenv = dotenv_values(env_file)
    try:
        in_file = read_config(config_path or config_file_path())
    except ValueError:
        in_file = {}
    result = []
    for name, value in settings._keys():
        if not value:
            result.append(KeyStatus(name, KeySource.MISSING, None))
        elif os.environ.get(name):
            result.append(KeyStatus(name, KeySource.ENVIRONMENT, mask_key(value)))
        elif dotenv.get(name):
            result.append(KeyStatus(name, KeySource.DOTENV, mask_key(value)))
        elif in_file.get(name.lower()):
            result.append(KeyStatus(name, KeySource.CONFIG_FILE, mask_key(value)))
        else:
            # Passed in code (e.g. Settings(gemini_api_key=...)): treat it as not editable.
            result.append(KeyStatus(name, KeySource.ENVIRONMENT, mask_key(value)))
    return result
