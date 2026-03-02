"""
Configuration module using Pydantic Settings.
Loads and validates environment variables with type safety.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    All sensitive values are validated and typed.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===================
    # Server Configuration
    # ===================
    app_name: str = Field(default="agente-ia", description="Application name")
    app_env: str = Field(default="development", description="Environment: development, staging, production")
    debug: bool = Field(default=False, description="Enable debug mode")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    host: str = Field(default="0.0.0.0", description="Server host")
    workers: int = Field(default=1, ge=1, description="Number of workers")

    # ===================
    # Google AI (Gemini)
    # ===================
    google_api_key: str = Field(..., description="Google AI API key for Gemini")
    gemini_model: str = Field(default="gemini-2.5-flash", description="Gemini model to use")
    gemini_temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Model temperature")
    gemini_max_tokens: int = Field(default=4096, ge=1, description="Max output tokens")

    # ===================
    # Supabase Database
    # ===================
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_service_key: str = Field(..., description="Supabase service role key")

    # ===================
    # Redis Cache/Queue
    # ===================
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    redis_prefix: str = Field(default="agente-ia:", description="Redis key prefix")
    cache_ttl: int = Field(default=3600, ge=0, description="Default cache TTL in seconds")

    # ===================
    # WhatsApp (UAZAPI)
    # ===================
    uazapi_base_url: str = Field(..., description="UAZAPI base URL")
    uazapi_api_key: str = Field(..., description="UAZAPI API key")

    # ===================
    # Message Processing
    # ===================
    message_buffer_delay_ms: int = Field(
        default=9000, ge=0, le=60000, description="Message buffer delay in milliseconds"
    )
    max_conversation_history: int = Field(
        default=50, ge=1, le=200, description="Max messages in conversation context"
    )

    # ===================
    # Logging
    # ===================
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or console")

    # ===================
    # Optional Services
    # ===================
    asaas_api_key: Optional[str] = Field(default=None, description="Asaas API key for payments")
    asaas_api_url: str = Field(
        default="https://api.asaas.com/v3", description="Asaas API URL"
    )
    asaas_webhook_token: Optional[str] = Field(
        default=None, description="Asaas webhook access token for validation"
    )

    google_calendar_credentials: Optional[str] = Field(
        default=None, description="Google Calendar service account JSON"
    )

    # ===================
    # JWT Authentication (compatível com agnes-agent)
    # ===================
    jwt_secret: Optional[str] = Field(
        default=None, description="JWT secret (mesmo do agnes-agent para compatibilidade)"
    )

    # ===================
    # Google OAuth2 (para Calendar via refresh_token)
    # ===================
    google_client_id: Optional[str] = Field(
        default=None, description="Google OAuth Client ID"
    )
    google_client_secret: Optional[str] = Field(
        default=None, description="Google OAuth Client Secret"
    )

    # ===================
    # URLs
    # ===================
    api_base_url: Optional[str] = Field(
        default=None, description="Base URL deste backend (para OAuth callback)"
    )
    frontend_url: Optional[str] = Field(
        default=None, description="URL do frontend (para redirect apos OAuth)"
    )

    # ===================
    # Validators
    # ===================
    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v.lower() not in allowed:
            raise ValueError(f"app_env must be one of: {allowed}")
        return v.lower()

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of: {allowed}")
        return v.upper()

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        allowed = {"json", "console"}
        if v.lower() not in allowed:
            raise ValueError(f"log_format must be one of: {allowed}")
        return v.lower()

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.app_env == "development"


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to ensure settings are loaded only once.
    """
    return Settings()


# Export settings instance for convenience
settings = get_settings()
