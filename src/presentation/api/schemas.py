"""
API schemas.

Pydantic models for request/response validation.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# Base schemas
# =============================================================================

class BaseResponse(BaseModel):
    """Base response with common fields."""
    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseModel):
    """Paginated list response."""
    items: List
    total: int
    page: int
    per_page: int
    pages: int


class ErrorResponse(BaseModel):
    """Error response."""
    detail: str
    code: Optional[str] = None


# =============================================================================
# Account schemas
# =============================================================================

class AccountBase(BaseModel):
    """Base account fields."""
    phone: str = Field(..., min_length=10, max_length=20)


class AccountCreate(AccountBase):
    """Create account request."""
    session_data: Optional[bytes] = None
    proxy_id: Optional[UUID] = None


class AccountUpdate(BaseModel):
    """Update account request."""
    proxy_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    status: Optional[str] = None


class AccountScheduleUpdate(BaseModel):
    """Update account schedule."""
    start_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    active_days: Optional[List[int]] = Field(None, min_length=1, max_length=7)
    timezone: Optional[str] = None


class AccountLimitsUpdate(BaseModel):
    """Update account limits."""
    max_messages_per_hour: Optional[int] = Field(None, ge=1, le=100)
    max_new_conversations_per_day: Optional[int] = Field(None, ge=1, le=100)
    min_delay_between_messages: Optional[int] = Field(None, ge=1)
    max_delay_between_messages: Optional[int] = Field(None, ge=1)


class AccountResponse(BaseResponse):
    """Account response."""
    id: UUID
    phone: str
    telegram_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_premium: bool = False
    status: str
    error_message: Optional[str] = None
    proxy_id: Optional[UUID] = None
    campaign_id: Optional[UUID] = None
    hourly_messages_count: int = 0
    daily_conversations_count: int = 0
    total_messages_sent: int = 0
    total_conversations_started: int = 0
    last_activity: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AccountListResponse(PaginatedResponse):
    """Paginated account list."""
    items: List[AccountResponse]


# =============================================================================
# Campaign schemas
# =============================================================================

class CampaignGoal(BaseModel):
    """Campaign goal configuration."""
    target_message: Optional[str] = None
    target_url: Optional[str] = None
    min_messages_before_goal: int = Field(default=3, ge=1)
    max_messages_before_goal: int = Field(default=10, ge=1)


class CampaignPrompt(BaseModel):
    """Campaign prompt configuration."""
    system_prompt: Optional[str] = None
    first_message_template: Optional[str] = None
    goal_hints: Optional[List[str]] = None
    forbidden_topics: Optional[List[str]] = None
    language: str = "ru"
    tone: str = "friendly"


class CampaignCreate(BaseModel):
    """Create campaign request."""
    name: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    owner_telegram_id: Optional[int] = None


class CampaignUpdate(BaseModel):
    """Update campaign request."""
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = None
    goal: Optional[CampaignGoal] = None
    prompt: Optional[CampaignPrompt] = None
    ai_model: Optional[str] = None
    ai_temperature: Optional[float] = Field(None, ge=0, le=2)
    ai_max_tokens: Optional[int] = Field(None, ge=100, le=4096)


class CampaignStatsResponse(BaseModel):
    """Campaign statistics."""
    total_targets: int = 0
    contacted: int = 0
    responded: int = 0
    goals_reached: int = 0
    completed: int = 0
    failed: int = 0
    messages_sent: int = 0
    tokens_used: int = 0
    response_rate: float = 0.0
    conversion_rate: float = 0.0


class CampaignResponse(BaseResponse):
    """Campaign response."""
    id: UUID
    name: str
    description: Optional[str] = None
    owner_telegram_id: Optional[int] = None
    status: str
    goal: dict = {}
    prompt: dict = {}
    stats: CampaignStatsResponse = CampaignStatsResponse()
    account_ids: List[UUID] = []
    ai_model: Optional[str] = None
    ai_temperature: Optional[float] = None
    ai_max_tokens: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CampaignListResponse(PaginatedResponse):
    """Paginated campaign list."""
    items: List[CampaignResponse]


# =============================================================================
# Target schemas
# =============================================================================

class TargetCreate(BaseModel):
    """Create target request."""
    telegram_id: Optional[int] = None
    telegram_username: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    priority: int = Field(default=0, ge=-10, le=10)
    tags: List[str] = []


class TargetBulkCreate(BaseModel):
    """Bulk create targets request."""
    targets: List[TargetCreate]
    source: Optional[str] = None


class TargetResponse(BaseResponse):
    """Target response."""
    id: UUID
    campaign_id: UUID
    telegram_id: Optional[int] = None
    telegram_username: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    status: str
    priority: int = 0
    source: Optional[str] = None
    tags: List[str] = []
    assigned_account_id: Optional[UUID] = None
    assigned_at: Optional[datetime] = None
    contacted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    fail_reason: Optional[str] = None
    created_at: datetime


# =============================================================================
# Proxy schemas
# =============================================================================

class ProxyCreate(BaseModel):
    """Create proxy request."""
    host: str
    port: int = Field(..., ge=1, le=65535)
    proxy_type: str = Field(default="socks5", pattern=r"^(socks5|socks4|http|https)$")
    username: Optional[str] = None
    password: Optional[str] = None


class ProxyBulkCreate(BaseModel):
    """Bulk create proxies request."""
    proxies: List[ProxyCreate]


class ProxyResponse(BaseResponse):
    """Proxy response."""
    id: UUID
    host: str
    port: int
    proxy_type: str
    username: Optional[str] = None
    status: str
    assigned_account_id: Optional[UUID] = None
    last_check_at: Optional[datetime] = None
    last_check_latency_ms: Optional[int] = None
    fail_count: int = 0
    created_at: datetime


class ProxyListResponse(PaginatedResponse):
    """Paginated proxy list."""
    items: List[ProxyResponse]


# =============================================================================
# Dialogue schemas
# =============================================================================

class MessageResponse(BaseModel):
    """Message response."""
    id: UUID
    role: str
    content: str
    telegram_message_id: Optional[int] = None
    ai_generated: bool = False
    tokens_used: Optional[int] = None
    created_at: datetime


class DialogueResponse(BaseResponse):
    """Dialogue response."""
    id: UUID
    account_id: UUID
    campaign_id: UUID
    target_id: Optional[UUID] = None
    target_telegram_id: int
    target_username: Optional[str] = None
    status: str
    goal_reached: bool = False
    goal_reached_at: Optional[datetime] = None
    messages_count: int = 0
    last_message_at: Optional[datetime] = None
    next_action_at: Optional[datetime] = None
    fail_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DialogueDetailResponse(DialogueResponse):
    """Dialogue with messages."""
    messages: List[MessageResponse] = []


class DialogueListResponse(PaginatedResponse):
    """Paginated dialogue list."""
    items: List[DialogueResponse]


# =============================================================================
# Stats schemas
# =============================================================================

class SystemStatsResponse(BaseModel):
    """System-wide statistics."""
    accounts: dict
    campaigns: dict
    proxies: dict
    dialogues: dict
    workers: dict


class AccountStatsResponse(BaseModel):
    """Account statistics."""
    total: int = 0
    active: int = 0
    ready: int = 0
    paused: int = 0
    error: int = 0
    banned: int = 0


class CampaignDetailStatsResponse(BaseModel):
    """Detailed campaign statistics."""
    campaign_id: UUID
    name: str
    status: str
    targets: dict
    accounts: int
    stats: CampaignStatsResponse
