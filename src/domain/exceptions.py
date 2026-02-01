"""
Domain-level exceptions.

These exceptions represent business logic errors that can occur
within the domain layer. They should be caught and handled
appropriately by the application layer.
"""


class DomainException(Exception):
    """Base exception for all domain errors."""
    
    def __init__(self, message: str, code: str = "DOMAIN_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


# Account exceptions

class AccountException(DomainException):
    """Base exception for account-related errors."""
    pass


class AccountNotFoundError(AccountException):
    """Raised when an account cannot be found."""
    
    def __init__(self, identifier: str):
        super().__init__(
            f"Account not found: {identifier}",
            code="ACCOUNT_NOT_FOUND"
        )


class AccountAlreadyExistsError(AccountException):
    """Raised when trying to create a duplicate account."""
    
    def __init__(self, phone: str):
        super().__init__(
            f"Account with phone {phone} already exists",
            code="ACCOUNT_EXISTS"
        )


class AccountBannedError(AccountException):
    """Raised when account is banned."""
    
    def __init__(self, account_id: str):
        super().__init__(
            f"Account {account_id} is banned",
            code="ACCOUNT_BANNED"
        )


class AccountLimitExceededError(AccountException):
    """Raised when account has exceeded its limits."""
    
    def __init__(self, account_id: str, limit_type: str):
        super().__init__(
            f"Account {account_id} exceeded {limit_type} limit",
            code="ACCOUNT_LIMIT_EXCEEDED"
        )


class AccountNotConfiguredError(AccountException):
    """Raised when account is not fully configured."""
    
    def __init__(self, account_id: str, missing: str):
        super().__init__(
            f"Account {account_id} missing configuration: {missing}",
            code="ACCOUNT_NOT_CONFIGURED"
        )


# Campaign exceptions

class CampaignException(DomainException):
    """Base exception for campaign-related errors."""
    pass


class CampaignNotFoundError(CampaignException):
    """Raised when a campaign cannot be found."""
    
    def __init__(self, identifier: str):
        super().__init__(
            f"Campaign not found: {identifier}",
            code="CAMPAIGN_NOT_FOUND"
        )


class CampaignInvalidStateError(CampaignException):
    """Raised when campaign is in invalid state for operation."""
    
    def __init__(self, campaign_id: str, current_state: str, required_state: str):
        super().__init__(
            f"Campaign {campaign_id} is in {current_state} state, "
            f"required: {required_state}",
            code="CAMPAIGN_INVALID_STATE"
        )


class CampaignNotConfiguredError(CampaignException):
    """Raised when campaign is not fully configured."""
    
    def __init__(self, campaign_id: str, missing: str):
        super().__init__(
            f"Campaign {campaign_id} missing configuration: {missing}",
            code="CAMPAIGN_NOT_CONFIGURED"
        )


# Dialogue exceptions

class DialogueException(DomainException):
    """Base exception for dialogue-related errors."""
    pass


class DialogueNotFoundError(DialogueException):
    """Raised when a dialogue cannot be found."""
    
    def __init__(self, identifier: str):
        super().__init__(
            f"Dialogue not found: {identifier}",
            code="DIALOGUE_NOT_FOUND"
        )


class DialogueAlreadyExistsError(DialogueException):
    """Raised when dialogue already exists for user."""
    
    def __init__(self, account_id: str, user_id: str):
        super().__init__(
            f"Dialogue already exists between account {account_id} and user {user_id}",
            code="DIALOGUE_EXISTS"
        )


# Proxy exceptions

class ProxyException(DomainException):
    """Base exception for proxy-related errors."""
    pass


class ProxyNotFoundError(ProxyException):
    """Raised when a proxy cannot be found."""
    
    def __init__(self, identifier: str):
        super().__init__(
            f"Proxy not found: {identifier}",
            code="PROXY_NOT_FOUND"
        )


class ProxyNotAvailableError(ProxyException):
    """Raised when no proxy is available."""

    def __init__(self, reason: str = ""):
        message = "No available proxy"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(message, code="PROXY_NOT_AVAILABLE")


class ProxyRequiredError(ProxyException):
    """Raised when proxy is required but not configured.

    This is a security measure to prevent direct connections
    that would expose the real IP address to Telegram.
    """

    def __init__(self, account_id: str = "", context: str = ""):
        message = "Proxy is required for Telegram connections"
        if account_id:
            message = f"{message} (account: {account_id})"
        if context:
            message = f"{message} - {context}"
        super().__init__(message, code="PROXY_REQUIRED")


class ProxyConnectionError(ProxyException):
    """Raised when proxy connection fails."""
    
    def __init__(self, proxy_id: str, error: str):
        super().__init__(
            f"Proxy {proxy_id} connection failed: {error}",
            code="PROXY_CONNECTION_ERROR"
        )


# Target exceptions

class TargetException(DomainException):
    """Base exception for target user errors."""
    pass


class TargetNotFoundError(TargetException):
    """Raised when target user cannot be found."""
    
    def __init__(self, identifier: str):
        super().__init__(
            f"Target user not found: {identifier}",
            code="TARGET_NOT_FOUND"
        )


class TargetAlreadyContactedError(TargetException):
    """Raised when target has already been contacted."""
    
    def __init__(self, target_id: str):
        super().__init__(
            f"Target {target_id} has already been contacted",
            code="TARGET_ALREADY_CONTACTED"
        )


# AI/LLM exceptions

class AIException(DomainException):
    """Base exception for AI-related errors."""
    pass


class AIProviderError(AIException):
    """Raised when AI provider returns an error."""
    
    def __init__(self, provider: str, error: str):
        super().__init__(
            f"AI provider {provider} error: {error}",
            code="AI_PROVIDER_ERROR"
        )


class AIRateLimitError(AIException):
    """Raised when AI provider rate limit is hit."""
    
    def __init__(self, provider: str, retry_after: int = 0):
        message = f"AI provider {provider} rate limit exceeded"
        if retry_after:
            message = f"{message}, retry after {retry_after}s"
        super().__init__(message, code="AI_RATE_LIMIT")
        self.retry_after = retry_after


class AIContextTooLongError(AIException):
    """Raised when context exceeds token limit."""
    
    def __init__(self, tokens: int, max_tokens: int):
        super().__init__(
            f"Context too long: {tokens} tokens (max: {max_tokens})",
            code="AI_CONTEXT_TOO_LONG"
        )


# Telegram exceptions

class TelegramException(DomainException):
    """Base exception for Telegram-related errors."""
    pass


class TelegramAuthError(TelegramException):
    """Raised when Telegram authentication fails."""
    
    def __init__(self, reason: str):
        super().__init__(
            f"Telegram authentication failed: {reason}",
            code="TELEGRAM_AUTH_ERROR"
        )


class TelegramFloodError(TelegramException):
    """Raised when Telegram rate limits us."""
    
    def __init__(self, wait_seconds: int):
        super().__init__(
            f"Telegram flood wait: {wait_seconds} seconds",
            code="TELEGRAM_FLOOD"
        )
        self.wait_seconds = wait_seconds


class TelegramUserNotFoundError(TelegramException):
    """Raised when Telegram user cannot be found."""
    
    def __init__(self, identifier: str):
        super().__init__(
            f"Telegram user not found: {identifier}",
            code="TELEGRAM_USER_NOT_FOUND"
        )


class TelegramPrivacyError(TelegramException):
    """Raised when user privacy settings prevent contact."""
    
    def __init__(self, user_id: str):
        super().__init__(
            f"Cannot contact user {user_id} due to privacy settings",
            code="TELEGRAM_PRIVACY"
        )
