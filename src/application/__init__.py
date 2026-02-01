"""
Application layer.

Contains business logic, prompts, and services.
"""

from .prompts import (
    CRYPTO_TRADER_PROMPT,
    FIRST_MESSAGE_PROMPT,
    DEFAULT_PROMPT,
    get_crypto_trader_prompt,
    get_first_message_prompt,
    build_custom_prompt,
    CampaignPromptConfig,
)

__all__ = [
    # Prompts
    "CRYPTO_TRADER_PROMPT",
    "FIRST_MESSAGE_PROMPT", 
    "DEFAULT_PROMPT",
    "get_crypto_trader_prompt",
    "get_first_message_prompt",
    "build_custom_prompt",
    "CampaignPromptConfig",
]
