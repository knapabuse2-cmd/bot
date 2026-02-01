"""CommentBot configuration."""

from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# Path to commentbot directory
COMMENTBOT_DIR = Path(__file__).parent
ENV_FILE = COMMENTBOT_DIR / ".env"


class CommentBotConfig(BaseSettings):
    """CommentBot settings - independent from main bot."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    db_use_sqlite: bool = True
    db_sqlite_path: str = "src/commentbot/data/commentbot.db"

    # Telegram API
    telegram_api_id: int = Field(..., validation_alias="TELEGRAM_API_ID")
    telegram_api_hash: SecretStr = Field(..., validation_alias="TELEGRAM_API_HASH")

    # Bot token
    commentbot_bot_token: SecretStr = Field(..., validation_alias="COMMENTBOT_BOT_TOKEN")

    # Security
    security_session_encryption_key: SecretStr = Field(
        ..., validation_alias="SECURITY_SESSION_ENCRYPTION_KEY"
    )

    # Limits
    daily_comment_limit: int = 50
    min_delay_between_comments: int = 30
    max_delay_between_comments: int = 120

    # Logging
    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        """Get async database URL."""
        if self.db_use_sqlite:
            return f"sqlite+aiosqlite:///{self.db_sqlite_path}"
        raise ValueError("Only SQLite supported for CommentBot")


_config: Optional[CommentBotConfig] = None
_encryption: Optional[Fernet] = None


def get_config() -> CommentBotConfig:
    """Get CommentBot config."""
    global _config
    if _config is None:
        _config = CommentBotConfig()
    return _config


def get_session_encryption() -> Fernet:
    """Get Fernet encryption for sessions."""
    global _encryption
    if _encryption is None:
        config = get_config()
        key = config.security_session_encryption_key.get_secret_value()
        _encryption = Fernet(key.encode())
    return _encryption
