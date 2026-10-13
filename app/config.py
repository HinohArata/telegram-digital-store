import os
from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram Bot
    BOT_TOKEN: str = "YOUR_BOT_TOKEN"
    ADMIN_IDS: Union[List[int], str] = []

    # Database: Supabase/Railway Postgres (or fallback to local sqlite for dev)
    DATABASE_URL: str = "sqlite+aiosqlite:///local_store.db"

    # Security: AES/Fernet encryption key for credentials at rest
    ENCRYPTION_KEY: str = ""

    # Mayar.id Payment Gateway
    MAYAR_API_KEY: str = ""
    MAYAR_WEBHOOK_TOKEN: str = ""
    MAYAR_BASE_URL: str = "https://pubapi.mayar.id"

    # Deployment
    PORT: int = int(os.getenv("PORT", 8080))
    BASE_WEBHOOK_URL: str = ""
    DEBUG: bool = False

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: Union[str, List[int], int]) -> List[int]:
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip().isdigit()]
        if isinstance(v, list):
            return [int(x) for x in v]
        return []

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        # Otomatis sesuaikan URL dari Railway atau provider lain untuk driver asyncpg
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v



settings = Settings()
