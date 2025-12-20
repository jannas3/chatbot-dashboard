from __future__ import annotations

import logging
import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, HttpUrl, ValidationError, field_validator

load_dotenv()


class Settings(BaseModel):
    telegram_token: str
    gemini_api_key: str | None = None
    bot_shared_secret: str = "dev_secret"
    backend_url: HttpUrl = "http://localhost:4000/api/screenings"  # type: ignore[assignment]

    @field_validator("telegram_token")
    @classmethod
    def token_required(cls, value: str) -> str:
        if not value:
            raise ValueError("TELEGRAM_TOKEN obrigatório.")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        # Aceita tanto BACKEND_URL quanto API_URL (para compatibilidade)
        backend_url = os.getenv("BACKEND_URL") or os.getenv("API_URL") or "http://localhost:4000/api/screenings"
        
        return Settings(
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            bot_shared_secret=os.getenv("BOT_SHARED_SECRET", "dev_secret"),
            backend_url=backend_url,
        )
    except ValidationError as exc:
        logging.getLogger(__name__).error("config validation error: %s", exc)
        raise


