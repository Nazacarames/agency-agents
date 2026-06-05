"""
Config — settings tipados con pydantic-settings.
Lee de variables de entorno + .env (si existe).
"""
from functools import lru_cache
from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── MiniMax-M3 ──
    # Decisión 2026-06-04: usar M3 (NO M2.7 como en OpenClaw) como modelo
    # principal de los agentes. M3 es el modelo más reciente de MiniMax.
    # Fallbacks: M2.5 (estable) y M2.5-highspeed (cuando necesitamos más velocidad).
    minimax_base_url: str = "https://api.minimax.io/anthropic"
    minimax_api_key: str = Field(default="", description="API key de MiniMax")
    minimax_model_primary: str = "MiniMax-M3"
    minimax_model_fallbacks: str = "MiniMax-M2.5,MiniMax-M2.5-highspeed"
    minimax_max_tokens: int = 8192
    minimax_timeout_seconds: int = 120

    # ── Discord ──
    discord_webhook_url: str = ""
    discord_default_username: str = "Automiq Agents"
    discord_avatar_url: str = ""

    # ── Scheduler ──
    scheduler_timezone: str = "America/Buenos_Aires"
    scheduler_enabled: bool = True
    global_pause: bool = False

    # ── Web ──
    port: int = 8000
    host: str = "0.0.0.0"
    log_level: str = "INFO"
    webhook_secret: str = ""

    # ── Render (auto-injected) ──
    render_service_id: str = ""
    render_external_url: str = ""

    @field_validator("minimax_api_key", "discord_webhook_url", "webhook_secret", mode="before")
    @classmethod
    def _empty_string_to_default(cls, v):
        """Si las vars tienen placeholders de .env.example, tratarlas como vacías."""
        if v in (None, "", "***", "REEMPLAZAR", "REEMPL...n"):
            return ""
        return v

    @property
    def minimax_fallbacks_list(self) -> List[str]:
        return [m.strip() for m in self.minimax_model_fallbacks.split(",") if m.strip()]

    @property
    def is_production(self) -> bool:
        return bool(self.render_service_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
