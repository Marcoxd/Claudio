"""Configuración de la aplicación (leída de variables de entorno o .env)."""
from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Marca (personalizable por cliente) ---
    app_name: str = "Kuri"
    app_tagline: str = "Tus finanzas, en un chat"
    owner_name: str = ""          # nombre del cliente, para saludarlo

    # --- Telegram ---
    telegram_token: str = ""
    telegram_webhook_secret: str = "cambia-esto"
    # IDs de Telegram autorizados a usar el bot. Vacío = nadie (el primer /start
    # muestra tu id para que lo agregues).
    allowed_user_ids: str = ""

    # --- Google AI Studio (Gemini) ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # --- Base de datos ---
    database_url: str = "sqlite+aiosqlite:///./data/gastos.db"

    # --- Web ---
    base_url: str = "http://localhost:8000"
    dashboard_token: str = "cambia-esto"

    # --- Localización ---
    currency: str = "USD"
    currency_symbol: str = "$"
    timezone: str = "America/Guayaquil"
    locale_decimal_comma: bool = False

    # --- Colchón (dinero que no es mío) ---
    buffer_name: str = "Colchón"
    buffer_initial: float = 0.0

    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Acepta la URL que dan Neon/Render/Railway y la vuelve async."""
        if v.startswith("postgres://"):
            v = "postgresql+asyncpg://" + v[len("postgres://") :]
        elif v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://") :]
        elif v.startswith("sqlite:///"):
            v = "sqlite+aiosqlite:///" + v[len("sqlite:///") :]
        # asyncpg no entiende ?sslmode=... ni ?channel_binding=...
        if "+asyncpg" in v and ("sslmode=" in v or "channel_binding=" in v):
            base, _, query = v.partition("?")
            drop = {"sslmode", "channel_binding"}
            keep = [p for p in query.split("&") if p.split("=")[0] not in drop]
            v = base + ("?" + "&".join(keep) if keep else "")
        return v

    @property
    def allowed_ids(self) -> set[int]:
        out: set[int] = set()
        for chunk in self.allowed_user_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk.lstrip("-").isdigit():
                out.add(int(chunk))
        return out

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except Exception:
            return ZoneInfo("UTC")

    @property
    def ai_enabled(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
