"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables and/or YAML files.
Sensitive data (API keys, passwords) should only come from environment.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """PostgreSQL database configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_")

    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: SecretStr = SecretStr("postgres")
    database: str = "outreach"
    pool_size: int = 20
    pool_max_overflow: int = 80
    echo: bool = False

    @property
    def async_url(self) -> str:
        """Get async database URL for SQLAlchemy."""
        pwd = self.password.get_secret_value()
        return f"postgresql+asyncpg://{self.user}:{pwd}@{self.host}:{self.port}/{self.database}"

    @property
    def sync_url(self) -> str:
        """Get sync database URL (for migrations)."""
        pwd = self.password.get_secret_value()
        return f"postgresql://{self.user}:{pwd}@{self.host}:{self.port}/{self.database}"


class RedisSettings(BaseSettings):
    """Redis configuration."""
    
    model_config = SettingsConfigDict(env_prefix="REDIS_")
    
    host: str = "localhost"
    port: int = 6379
    password: Optional[SecretStr] = None
    db: int = 0
    queue_db: int = 1
    
    @property
    def url(self) -> str:
        """Get Redis URL."""
        auth = ""
        if self.password:
            auth = f":{self.password.get_secret_value()}@"
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"
    
    @property
    def queue_url(self) -> str:
        """Get Redis URL for task queue."""
        auth = ""
        if self.password:
            auth = f":{self.password.get_secret_value()}@"
        return f"redis://{auth}{self.host}:{self.port}/{self.queue_db}"


class TelegramSettings(BaseSettings):
    """Telegram API configuration."""
    
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")
    
    api_id: int = Field(..., description="Telegram API ID from my.telegram.org")
    api_hash: SecretStr = Field(..., description="Telegram API Hash from my.telegram.org")
    admin_bot_token: SecretStr = Field(..., description="Admin bot token from @BotFather")
    admin_user_ids_raw: str = Field(
        default="",
        validation_alias="TELEGRAM_ADMIN_USER_IDS",
        description="Comma-separated list of Telegram user IDs allowed to use admin bot"
    )
    
    session_dir: Path = Path("sessions")
    
    # Safety settings
    flood_sleep_threshold: int = 60  # Max seconds to wait on flood
    request_retries: int = 3
    
    @property
    def admin_user_ids(self) -> list[int]:
        """Get admin user IDs as list."""
        if not self.admin_user_ids_raw:
            return []
        
        ids = []
        for part in self.admin_user_ids_raw.split(","):
            part = part.strip()
            if part.isdigit():
                ids.append(int(part))
        
        return ids


class OpenAISettings(BaseSettings):
    """OpenAI API configuration."""
    
    model_config = SettingsConfigDict(env_prefix="OPENAI_")
    
    api_key: SecretStr = Field(..., description="OpenAI API key")
    default_model: str = "gpt-4o-mini"
    fallback_model: str = "gpt-4o-mini"
    default_temperature: float = 0.7
    default_max_tokens: int = 500
    timeout: float = 30.0


class SecuritySettings(BaseSettings):
    """Security configuration."""

    model_config = SettingsConfigDict(env_prefix="SECURITY_")

    session_encryption_key: SecretStr = Field(
        ...,
        description="Fernet key for session encryption"
    )
    api_key: Optional[SecretStr] = Field(
        default=None,
        description="API key for REST API authentication"
    )
    http_proxy_url: Optional[str] = Field(
        default=None,
        description="SOCKS5/HTTP proxy for outbound HTTP requests (OpenAI, Stripe). "
                    "Format: socks5://user:pass@host:port"
    )
    cors_allowed_origins: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins. "
                    "Use '*' only in development."
    )


class WorkerSettings(BaseSettings):
    """Worker configuration."""

    model_config = SettingsConfigDict(env_prefix="WORKER_")

    max_concurrent_accounts: int = 50
    message_check_interval: float = 5.0
    health_check_interval: float = 60.0
    target_distribution_interval: float = 30.0
    hourly_reset_interval: int = 3600
    daily_reset_interval: int = 86400


class CommentBotSettings(BaseSettings):
    """Comment bot configuration."""

    model_config = SettingsConfigDict(env_prefix="COMMENTBOT_")

    bot_token: SecretStr = Field(
        default=SecretStr(""),
        description="Comment bot token from @BotFather"
    )
    daily_comment_limit: int = 50
    min_delay_between_comments: int = 30  # seconds
    max_delay_between_comments: int = 120  # seconds


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "telegram-outreach-system"
    debug: bool = False
    environment: str = "development"

    # API
    api_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for API (used for payment form links)"
    )

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "console"
    
    # Nested settings
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    commentbot: CommentBotSettings = Field(default_factory=CommentBotSettings)


# Cached settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Get application settings.
    
    Uses caching to avoid re-reading environment on every call.
    
    Returns:
        Settings instance
    """
    global _settings
    
    if _settings is None:
        _settings = Settings()
    
    return _settings


def clear_settings_cache() -> None:
    """Clear settings cache (useful for testing)."""
    global _settings
    _settings = None
