"""
OpenAI AI provider implementation.

Handles all LLM interactions using OpenAI API with automatic
fallback to alternative OpenAI models on failure.

FIXED:
- Thread-safe singleton initialization with asyncio.Lock
- Better error handling
- Request tracking
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog
from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.config import get_settings
from src.domain.exceptions import AIProviderError, AIRateLimitError

logger = structlog.get_logger(__name__)


@dataclass
class AIResponse:
    """
    Response from AI provider.
    
    Attributes:
        content: Generated text content
        model: Model that generated the response
        prompt_tokens: Tokens used for prompt
        completion_tokens: Tokens used for completion
        total_tokens: Total tokens used
        finish_reason: Why generation stopped
    """
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"


class OpenAIProvider:
    """
    OpenAI-based AI provider.
    
    Provides text generation capabilities using OpenAI API.
    Supports automatic fallback to alternative OpenAI models.
    
    Attributes:
        client: Async OpenAI client
        default_model: Primary model to use
        fallback_model: Model to use if primary fails
        default_temperature: Default temperature setting
        default_max_tokens: Default max tokens per response
    """
    
    # Available OpenAI models in fallback order
    FALLBACK_MODELS = [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    ]
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        default_temperature: float = 0.7,
        default_max_tokens: int = 500,
        timeout: float = 30.0,
    ):
        """
        Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key (uses settings if not provided)
            default_model: Primary model to use
            fallback_model: Fallback model
            default_temperature: Default temperature
            default_max_tokens: Default max tokens
            timeout: Request timeout in seconds
        """
        settings = get_settings()
        
        self.api_key = api_key or settings.openai.api_key.get_secret_value()
        self.default_model = default_model or settings.openai.default_model
        self.fallback_model = fallback_model or settings.openai.fallback_model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.timeout = timeout
        
        # Route OpenAI requests through proxy if configured to prevent IP leak
        proxy_url = settings.security.http_proxy_url
        http_client = None
        if proxy_url:
            http_client = httpx.AsyncClient(proxy=proxy_url)
            logger.info("OpenAI client using proxy", proxy=proxy_url.split("@")[-1])

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.timeout,
            http_client=http_client,
        )
        
        self._request_count = 0
        self._token_count = 0
        self._error_count = 0
        self._lock = asyncio.Lock()
    
    async def generate(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        use_fallback: bool = True,
    ) -> AIResponse:
        """
        Generate a response from OpenAI.
        
        Args:
            messages: Conversation history in OpenAI format
            system_prompt: Optional system prompt to prepend
            model: Model to use (defaults to default_model)
            temperature: Temperature setting
            max_tokens: Maximum tokens to generate
            use_fallback: Whether to try fallback model on failure
            
        Returns:
            AIResponse with generated content
            
        Raises:
            AIProviderError: If generation fails
            AIRateLimitError: If rate limited
        """
        model = model or self.default_model
        temperature = temperature if temperature is not None else self.default_temperature
        max_tokens = max_tokens or self.default_max_tokens
        
        # Prepare messages
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)
        
        try:
            return await self._call_api(
                messages=full_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except (APIError, APIConnectionError) as e:
            logger.warning(
                "Primary model failed, trying fallback",
                model=model,
                error=str(e),
            )
            
            if use_fallback and model != self.fallback_model:
                return await self._call_with_fallback(
                    messages=full_messages,
                    failed_model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            
            self._error_count += 1
            raise AIProviderError("openai", str(e))
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((APIConnectionError,)),
        reraise=True,
    )
    async def _call_api(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        """
        Make actual API call to OpenAI.
        
        Uses tenacity for automatic retries on connection errors.
        """
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            
            self._request_count += 1
            
            choice = response.choices[0]
            usage = response.usage
            
            if usage:
                self._token_count += usage.total_tokens
            
            logger.debug(
                "OpenAI response generated",
                model=model,
                tokens=usage.total_tokens if usage else 0,
                finish_reason=choice.finish_reason,
            )
            
            return AIResponse(
                content=choice.message.content or "",
                model=response.model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                finish_reason=choice.finish_reason or "stop",
            )
            
        except RateLimitError as e:
            # Extract retry-after if available
            retry_after = 60  # Default
            if hasattr(e, 'response') and e.response:
                retry_after = int(e.response.headers.get('retry-after', 60))
            
            logger.warning(
                "OpenAI rate limit hit",
                model=model,
                retry_after=retry_after,
            )
            raise AIRateLimitError("openai", retry_after)
    
    async def _call_with_fallback(
        self,
        messages: list[dict],
        failed_model: str,
        temperature: float,
        max_tokens: int,
    ) -> AIResponse:
        """
        Try fallback models in order until one succeeds.
        """
        # Build fallback list
        models_to_try = [self.fallback_model]
        
        # Add other models from FALLBACK_MODELS
        for model in self.FALLBACK_MODELS:
            if model not in (failed_model, self.fallback_model):
                models_to_try.append(model)
        
        last_error = None
        
        for model in models_to_try:
            try:
                logger.info("Trying fallback model", model=model)
                return await self._call_api(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except (APIError, APIConnectionError) as e:
                logger.warning("Fallback model failed", model=model, error=str(e))
                last_error = e
                continue
            except AIRateLimitError:
                # Don't retry on rate limit
                raise
        
        self._error_count += 1
        raise AIProviderError("openai", f"All models failed. Last error: {last_error}")
    
    async def generate_dialogue_response(
        self,
        conversation_history: list[dict],
        system_prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AIResponse:
        """
        Generate a response for a dialogue.
        
        Convenience method that formats the conversation
        and generates an appropriate response.
        
        Args:
            conversation_history: List of messages in OpenAI format
            system_prompt: System prompt defining AI behavior
            model: Model to use
            temperature: Temperature setting
            max_tokens: Max tokens
            
        Returns:
            AIResponse with generated reply
        """
        return await self.generate(
            messages=conversation_history,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    
    async def check_health(self) -> bool:
        """
        Check if OpenAI API is accessible.
        
        Returns:
            True if API is healthy
        """
        try:
            response = await self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            return bool(response.choices)
        except Exception as e:
            logger.error("OpenAI health check failed", error=str(e))
            return False
    
    def get_stats(self) -> dict:
        """
        Get provider statistics.
        
        Returns:
            Dict with request and token counts
        """
        return {
            "request_count": self._request_count,
            "token_count": self._token_count,
            "error_count": self._error_count,
            "default_model": self.default_model,
            "fallback_model": self.fallback_model,
        }
    
    async def close(self) -> None:
        """Close the client connection."""
        await self.client.close()


# Thread-safe singleton implementation
_provider: Optional[OpenAIProvider] = None
_provider_lock = asyncio.Lock()


async def get_ai_provider_async() -> OpenAIProvider:
    """
    Get or create the AI provider singleton (async version).
    
    Thread-safe initialization using asyncio.Lock.
    
    Returns:
        OpenAIProvider instance
    """
    global _provider
    
    if _provider is None:
        async with _provider_lock:
            # Double-check after acquiring lock
            if _provider is None:
                _provider = OpenAIProvider()
    
    return _provider


def get_ai_provider() -> OpenAIProvider:
    """
    Get or create the AI provider singleton (sync version).
    
    Note: This is NOT thread-safe for initial creation.
    Use get_ai_provider_async() in async contexts for safety.
    
    Returns:
        OpenAIProvider instance
    """
    global _provider
    
    if _provider is None:
        _provider = OpenAIProvider()
    
    return _provider


async def close_ai_provider() -> None:
    """Close the AI provider."""
    global _provider
    
    async with _provider_lock:
        if _provider is not None:
            await _provider.close()
            _provider = None
