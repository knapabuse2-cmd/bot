"""Mappers between domain entities and database models.

The domain layer uses enums and dataclasses.
The persistence layer stores primitive values.

This module is the single translation point between them.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from typing import Optional, Type, TypeVar
from uuid import UUID

from src.domain.entities import (
    Account,
    AccountLimits,
    AccountSchedule,
    AccountSource,
    AccountStatus,
    Campaign,
    CampaignGoal,
    CampaignPrompt,
    CampaignSendingSettings,
    CampaignStats,
    CampaignStatus,
    Dialogue,
    DialogueStatus,
    Message,
    MessageRole,
    Proxy,
    ProxyStatus,
    ProxyType,
    TargetStatus,
    UserTarget,
    TelegramApp,
    # Warmup entities
    WarmupStatus,
    ActivityPattern,
    WarmupStage,
    WarmupProfile,
    AccountWarmup,
    AccountPersona,
    InterestCategory,
    WarmupChannel,
    WarmupGroup,
    AccountGroup,
    ProxyGroup,
    WarmupActivityLog,
)

from .models import (
    AccountModel,
    CampaignModel,
    DialogueModel,
    MessageModel,
    ProxyModel,
    UserTargetModel,
    TelegramAppModel,
    # Warmup models
    WarmupProfileModel,
    AccountWarmupModel,
    AccountPersonaModel,
    InterestCategoryModel,
    WarmupChannelModel,
    WarmupGroupModel,
    AccountGroupModel,
    ProxyGroupModel,
    WarmupActivityLogModel,
)

E = TypeVar("E", bound=Enum)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enum(enum_cls: Type[E], value, default: E) -> E:
    """Convert `value` to an Enum member with a safe default."""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _time_to_str(value: time | str) -> str:
    if isinstance(value, str):
        return value
    return value.strftime("%H:%M")


def _str_to_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    try:
        return datetime.strptime(value, "%H:%M").time()
    except Exception:
        # Safe fallback
        return time(9, 0)


# ============================================================
# Account
# ============================================================


def account_model_to_entity(model: AccountModel) -> Account:
    schedule = AccountSchedule(
        start_time=_str_to_time(model.schedule_start_time),
        end_time=_str_to_time(model.schedule_end_time),
        active_days=list(model.schedule_active_days or [0, 1, 2, 3, 4, 5, 6]),
        timezone=model.schedule_timezone or "UTC",
    )

    limits_data = model.limits or {}
    limits = AccountLimits(
        max_new_conversations_per_day=int(limits_data.get("max_new_conversations_per_day", 20)),
        max_messages_per_hour=int(limits_data.get("max_messages_per_hour", 30)),
        max_responses_per_hour=int(limits_data.get("max_responses_per_hour", 300)),
        min_delay_between_messages=int(limits_data.get("min_delay_between_messages", 30)),
        max_delay_between_messages=int(limits_data.get("max_delay_between_messages", 120)),
        max_active_dialogues=int(limits_data.get("max_active_dialogues", 50)),
    )

    return Account(
        id=model.id,
        phone=model.phone,
        session_data=model.session_data,
        proxy_id=model.proxy_id,
        telegram_app_id=getattr(model, "telegram_app_id", None),
        source=_enum(AccountSource, getattr(model, "source", "phone"), AccountSource.PHONE),
        status=_enum(AccountStatus, model.status, AccountStatus.INACTIVE),
        schedule=schedule,
        limits=limits,
        campaign_id=model.campaign_id,
        group_id=getattr(model, "group_id", None),
        telegram_id=model.telegram_id,
        username=model.username,
        first_name=model.first_name or "",
        last_name=model.last_name or "",
        bio=getattr(model, "bio", "") or "",
        is_premium=getattr(model, "is_premium", False) or False,
        daily_conversations_count=model.daily_conversations_count,
        hourly_messages_count=model.hourly_messages_count,
        hourly_responses_count=getattr(model, "hourly_responses_count", 0) or 0,
        total_messages_sent=getattr(model, "total_messages_sent", 0) or 0,
        total_conversations_started=getattr(model, "total_conversations_started", 0) or 0,
        last_daily_reset=model.last_daily_reset or datetime.utcnow(),
        last_hourly_reset=model.last_hourly_reset or datetime.utcnow(),
        last_activity=model.last_activity,
        error_message=model.error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=getattr(model, "version", 0),
    )


def account_entity_to_model(entity: Account, model: Optional[AccountModel] = None) -> AccountModel:
    if model is None:
        model = AccountModel()

    model.id = entity.id
    model.phone = entity.phone
    model.session_data = entity.session_data
    model.proxy_id = entity.proxy_id
    model.telegram_app_id = getattr(entity, "telegram_app_id", None)
    model.source = entity.source.value if isinstance(entity.source, Enum) else str(entity.source)
    model.status = entity.status.value if isinstance(entity.status, Enum) else str(entity.status)

    model.campaign_id = entity.campaign_id
    model.group_id = getattr(entity, "group_id", None)

    model.telegram_id = entity.telegram_id
    model.username = entity.username
    model.first_name = entity.first_name
    model.last_name = entity.last_name
    if hasattr(model, "bio"):
        model.bio = entity.bio
    if hasattr(model, "is_premium"):
        model.is_premium = entity.is_premium

    # Schedule
    model.schedule_start_time = _time_to_str(entity.schedule.start_time)
    model.schedule_end_time = _time_to_str(entity.schedule.end_time)
    model.schedule_active_days = list(entity.schedule.active_days)
    model.schedule_timezone = entity.schedule.timezone

    # Limits
    model.limits = {
        "max_new_conversations_per_day": entity.limits.max_new_conversations_per_day,
        "max_messages_per_hour": entity.limits.max_messages_per_hour,
        "max_responses_per_hour": entity.limits.max_responses_per_hour,
        "min_delay_between_messages": entity.limits.min_delay_between_messages,
        "max_delay_between_messages": entity.limits.max_delay_between_messages,
        "max_active_dialogues": entity.limits.max_active_dialogues,
    }

    model.hourly_messages_count = entity.hourly_messages_count
    model.hourly_responses_count = getattr(entity, "hourly_responses_count", 0)
    model.daily_conversations_count = entity.daily_conversations_count
    model.total_messages_sent = getattr(entity, "total_messages_sent", 0)
    model.total_conversations_started = getattr(entity, "total_conversations_started", 0)

    model.last_activity = entity.last_activity
    model.last_hourly_reset = entity.last_hourly_reset
    model.last_daily_reset = entity.last_daily_reset

    model.error_message = entity.error_message

    model.created_at = entity.created_at
    model.updated_at = entity.updated_at
    model.version = getattr(entity, "version", 0)

    return model


# ============================================================
# Campaign
# ============================================================


def campaign_model_to_entity(model: CampaignModel) -> Campaign:
    goal = CampaignGoal(
        target_message=model.goal_target_message or None,
        target_action=getattr(model, "goal_target_action", None) or None,
        target_url=model.goal_target_url or None,
        min_messages_before_goal=model.goal_min_messages_before_goal,
        max_messages_before_goal=model.goal_max_messages_before_goal,
    )

    prompt = CampaignPrompt(
        system_prompt=model.prompt_system_prompt or "",
        first_message_template=model.prompt_first_message_template or "",
        goal_transition_hints=list(model.prompt_goal_hints or []),
        forbidden_topics=list(model.prompt_forbidden_topics or []),
        language=model.prompt_language or "ru",
        tone=model.prompt_tone or "friendly",
    )

    stats_data = model.stats or {}
    stats = CampaignStats(
        total_targets=int(stats_data.get("total_targets", 0)),
        contacted=int(stats_data.get("contacted", 0)),
        responded=int(stats_data.get("responded", 0)),
        goals_reached=int(stats_data.get("goals_reached", 0)),
        completed=int(stats_data.get("completed", 0)),
        failed=int(stats_data.get("failed", 0)),
        total_messages_sent=int(stats_data.get("total_messages_sent", 0)),
        total_tokens_used=int(stats_data.get("total_tokens_used", 0)),
    )

    sending = CampaignSendingSettings(
        send_interval_hours=getattr(model, "sending_interval_hours", None) or 13.0,
        messages_per_batch=getattr(model, "sending_messages_per_batch", None) or 10,
        message_delay_min=getattr(model, "sending_delay_min", None) or 17,
        message_delay_max=getattr(model, "sending_delay_max", None) or 23,
        last_batch_at=getattr(model, "sending_last_batch_at", None),
        targets_file_path=getattr(model, "sending_targets_file_path", None),
        follow_up_enabled=getattr(model, "sending_follow_up_enabled", True),
    )

    account_ids: list[UUID] = []
    if "accounts" in model.__dict__ and model.__dict__["accounts"] is not None:
        account_ids = [acc.id for acc in model.__dict__["accounts"]]
    else:
        for v in model.account_ids or []:
            try:
                account_ids.append(UUID(str(v)))
            except Exception:
                continue

    return Campaign(
        id=model.id,
        name=model.name,
        description=model.description or "",
        status=_enum(CampaignStatus, model.status, CampaignStatus.DRAFT),
        goal=goal,
        prompt=prompt,
        stats=stats,
        sending=sending,
        account_ids=account_ids,
        start_date=model.started_at,
        end_date=model.completed_at,
        owner_telegram_id=model.owner_telegram_id or 0,
        ai_model=model.ai_model or "gpt-4o-mini",
        ai_temperature=model.ai_temperature if model.ai_temperature is not None else 0.7,
        ai_max_tokens=model.ai_max_tokens if model.ai_max_tokens is not None else 500,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=getattr(model, "version", 0),
    )


def campaign_entity_to_model(entity: Campaign, model: Optional[CampaignModel] = None) -> CampaignModel:
    if model is None:
        model = CampaignModel()

    model.id = entity.id
    model.name = entity.name
    model.description = entity.description
    model.status = entity.status.value if isinstance(entity.status, Enum) else str(entity.status)

    model.owner_telegram_id = entity.owner_telegram_id

    model.goal_target_message = entity.goal.target_message
    if hasattr(model, "goal_target_action"):
        model.goal_target_action = entity.goal.target_action
    model.goal_target_url = entity.goal.target_url
    model.goal_min_messages_before_goal = entity.goal.min_messages_before_goal
    model.goal_max_messages_before_goal = entity.goal.max_messages_before_goal

    model.prompt_system_prompt = entity.prompt.system_prompt
    model.prompt_first_message_template = entity.prompt.first_message_template
    model.prompt_goal_hints = list(entity.prompt.goal_transition_hints)
    model.prompt_forbidden_topics = list(entity.prompt.forbidden_topics)
    model.prompt_language = entity.prompt.language
    model.prompt_tone = entity.prompt.tone

    model.stats = {
        "total_targets": entity.stats.total_targets,
        "contacted": entity.stats.contacted,
        "responded": entity.stats.responded,
        "goals_reached": entity.stats.goals_reached,
        "completed": entity.stats.completed,
        "failed": entity.stats.failed,
        "total_messages_sent": entity.stats.total_messages_sent,
        "total_tokens_used": entity.stats.total_tokens_used,
    }

    model.account_ids = [str(aid) for aid in (entity.account_ids or [])]

    model.ai_model = entity.ai_model
    model.ai_temperature = entity.ai_temperature
    model.ai_max_tokens = entity.ai_max_tokens

    # Sending settings
    if hasattr(model, "sending_interval_hours"):
        model.sending_interval_hours = entity.sending.send_interval_hours
    if hasattr(model, "sending_messages_per_batch"):
        model.sending_messages_per_batch = entity.sending.messages_per_batch
    if hasattr(model, "sending_delay_min"):
        model.sending_delay_min = entity.sending.message_delay_min
    if hasattr(model, "sending_delay_max"):
        model.sending_delay_max = entity.sending.message_delay_max
    if hasattr(model, "sending_last_batch_at"):
        model.sending_last_batch_at = entity.sending.last_batch_at
    if hasattr(model, "sending_targets_file_path"):
        model.sending_targets_file_path = entity.sending.targets_file_path
    if hasattr(model, "sending_follow_up_enabled"):
        model.sending_follow_up_enabled = entity.sending.follow_up_enabled

    model.started_at = entity.start_date
    model.completed_at = entity.end_date

    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    model.version = getattr(entity, "version", 0)
    return model


# ============================================================
# Proxy
# ============================================================


def proxy_model_to_entity(model: ProxyModel) -> Proxy:
    return Proxy(
        id=model.id,
        host=model.host,
        port=model.port,
        proxy_type=_enum(ProxyType, model.proxy_type, ProxyType.SOCKS5),
        username=model.username,
        password=model.password,
        status=_enum(ProxyStatus, model.status, ProxyStatus.UNKNOWN),
        assigned_account_id=model.assigned_account_id,
        last_check=model.last_check_at,
        last_check_latency_ms=model.last_check_latency_ms,
        failure_count=model.fail_count,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=getattr(model, "version", 0),
    )


def proxy_entity_to_model(entity: Proxy, model: Optional[ProxyModel] = None) -> ProxyModel:
    if model is None:
        model = ProxyModel()

    model.id = entity.id
    model.host = entity.host
    model.port = entity.port
    model.proxy_type = entity.proxy_type.value if isinstance(entity.proxy_type, Enum) else str(entity.proxy_type)
    model.username = entity.username
    model.password = entity.password
    model.status = entity.status.value if isinstance(entity.status, Enum) else str(entity.status)
    model.assigned_account_id = entity.assigned_account_id

    model.last_check_at = entity.last_check
    model.last_check_latency_ms = entity.last_check_latency_ms
    model.fail_count = entity.failure_count

    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    model.version = getattr(entity, "version", 0)
    return model


# ============================================================
# TelegramApp
# ============================================================


def telegram_app_model_to_entity(model: TelegramAppModel) -> TelegramApp:
    return TelegramApp(
        id=model.id,
        api_id=model.api_id,
        api_hash=model.api_hash,
        name=model.name,
        description=model.description or "",
        max_accounts=model.max_accounts,
        current_account_count=model.current_account_count,
        is_active=model.is_active,
        notes=model.notes or "",
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=getattr(model, "version", 0),
    )


def telegram_app_entity_to_model(
    entity: TelegramApp, model: Optional[TelegramAppModel] = None
) -> TelegramAppModel:
    if model is None:
        model = TelegramAppModel()

    model.id = entity.id
    model.api_id = entity.api_id
    model.api_hash = entity.api_hash
    model.name = entity.name
    model.description = entity.description
    model.max_accounts = entity.max_accounts
    model.current_account_count = entity.current_account_count
    model.is_active = entity.is_active
    model.notes = entity.notes
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at
    model.version = getattr(entity, "version", 0)

    return model


# ============================================================
# UserTarget
# ============================================================


def user_target_model_to_entity(model: UserTargetModel) -> UserTarget:
    return UserTarget(
        id=model.id,
        campaign_id=model.campaign_id,
        telegram_id=model.telegram_id,
        username=model.username,
        phone=model.phone,
        first_name=model.first_name or "",
        last_name=model.last_name or "",
        status=_enum(TargetStatus, model.status, TargetStatus.PENDING),
        assigned_account_id=model.assigned_account_id,
        dialogue_id=model.dialogue_id,
        priority=model.priority,
        source=model.source,
        tags=list(model.tags or []),
        notes=model.notes or "",
        contact_attempts=model.contact_attempts,
        last_contact_attempt=model.last_contact_attempt,
        scheduled_contact_at=model.scheduled_contact_at,
        fail_reason=model.fail_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=getattr(model, "version", 0),
    )


def user_target_entity_to_model(entity: UserTarget, model: Optional[UserTargetModel] = None) -> UserTargetModel:
    if model is None:
        model = UserTargetModel()

    model.id = entity.id
    model.campaign_id = entity.campaign_id

    model.telegram_id = entity.telegram_id
    model.username = entity.username
    model.phone = entity.phone

    model.first_name = entity.first_name
    model.last_name = entity.last_name

    model.status = entity.status.value if isinstance(entity.status, Enum) else str(entity.status)
    model.assigned_account_id = entity.assigned_account_id
    model.dialogue_id = entity.dialogue_id

    model.priority = entity.priority
    model.source = entity.source
    model.tags = list(entity.tags)
    model.notes = entity.notes

    model.contact_attempts = entity.contact_attempts
    model.last_contact_attempt = entity.last_contact_attempt
    model.scheduled_contact_at = entity.scheduled_contact_at

    model.fail_reason = entity.fail_reason

    model.version = getattr(entity, "version", 0)
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    return model


# ============================================================
# Dialogue + Message
# ============================================================


def message_model_to_entity(model: MessageModel) -> Message:
    return Message(
        id=model.id,
        role=_enum(MessageRole, model.role, MessageRole.USER),
        content=model.content,
        timestamp=model.timestamp,
        telegram_message_id=model.telegram_message_id,
        ai_generated=model.ai_generated,
        tokens_used=model.tokens_used or 0,
        is_follow_up=model.is_follow_up,
    )


def message_entity_to_model(
    entity: Message,
    dialogue_id: UUID,
    model: Optional[MessageModel] = None,
) -> MessageModel:
    if model is None:
        model = MessageModel()

    model.id = entity.id
    model.dialogue_id = dialogue_id
    model.role = entity.role.value if isinstance(entity.role, Enum) else str(entity.role)
    model.content = entity.content
    model.timestamp = entity.timestamp
    model.telegram_message_id = entity.telegram_message_id
    model.ai_generated = entity.ai_generated
    model.tokens_used = entity.tokens_used
    model.is_follow_up = entity.is_follow_up

    return model


def dialogue_model_to_entity(model: DialogueModel) -> Dialogue:
    messages: list[Message] = []
    if "messages" in model.__dict__ and model.__dict__["messages"] is not None:
        messages = [message_model_to_entity(m) for m in model.__dict__["messages"]]

    dialogue = Dialogue(
        id=model.id,
        account_id=model.account_id,
        campaign_id=model.campaign_id,
        target_user_id=model.target_user_id or UUID(int=0),
        telegram_user_id=model.telegram_user_id or 0,
        telegram_username=model.telegram_username,
        status=_enum(DialogueStatus, model.status, DialogueStatus.PENDING),
        messages=messages,
        goal_message_sent=model.goal_message_sent,
        goal_message_sent_at=model.goal_message_sent_at,
        next_action_at=model.next_action_at,
        retry_count=model.retry_count,
        max_retries=model.max_retries,
        last_user_response_at=model.last_user_response_at,
        sentiment_score=model.sentiment_score,
        interest_score=model.interest_score,
        link_sent_count=model.link_sent_count,
        notes=model.notes or "",
        created_at=model.created_at,
        updated_at=model.updated_at,
    )

    # Optional fields for natural dialogue / API compatibility
    if hasattr(model, "needs_review"):
        setattr(dialogue, "needs_review", model.needs_review)
    if hasattr(model, "creative_sent"):
        setattr(dialogue, "creative_sent", model.creative_sent)
    if getattr(model, "fail_reason", None) is not None:
        setattr(dialogue, "fail_reason", model.fail_reason)

    return dialogue


def dialogue_entity_to_model(entity: Dialogue, model: Optional[DialogueModel] = None) -> DialogueModel:
    if model is None:
        model = DialogueModel()

    model.id = entity.id
    model.account_id = entity.account_id
    model.campaign_id = entity.campaign_id
    model.target_user_id = entity.target_user_id

    # Store unknown telegram_id as NULL (not 0)
    tid = getattr(entity, "telegram_user_id", 0)
    model.telegram_user_id = None if not tid or int(tid) == 0 else int(tid)
    model.telegram_username = entity.telegram_username

    model.status = entity.status.value if isinstance(entity.status, Enum) else str(entity.status)

    model.goal_message_sent = entity.goal_message_sent
    model.goal_message_sent_at = entity.goal_message_sent_at

    model.next_action_at = entity.next_action_at

    model.retry_count = entity.retry_count
    model.max_retries = entity.max_retries
    model.last_user_response_at = entity.last_user_response_at

    model.sentiment_score = entity.sentiment_score if entity.sentiment_score is not None else 0.0
    model.interest_score = entity.interest_score
    model.link_sent_count = entity.link_sent_count

    model.notes = entity.notes

    if hasattr(model, "needs_review"):
        model.needs_review = bool(getattr(entity, "needs_review", False))
    if hasattr(model, "creative_sent"):
        model.creative_sent = bool(getattr(entity, "creative_sent", False))

    # Persist fail_reason separately from notes when present
    if hasattr(model, "fail_reason"):
        model.fail_reason = getattr(entity, "fail_reason", None)

    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    model.version = getattr(entity, "version", 0)
    return model


# ============================================================
# Warmup System Mappers
# ============================================================


def warmup_profile_model_to_entity(model: WarmupProfileModel) -> WarmupProfile:
    """Convert WarmupProfileModel to WarmupProfile entity."""
    stages = []
    for stage_data in (model.stages or []):
        stages.append(WarmupStage(
            stage=stage_data.get("stage", 1),
            days=stage_data.get("days", 3),
            daily_messages=stage_data.get("daily_messages", 0),
            join_channels=stage_data.get("join_channels", 0),
            join_groups=stage_data.get("join_groups", 0),
            reactions_per_day=stage_data.get("reactions_per_day", 0),
            can_outreach=stage_data.get("can_outreach", False),
        ))

    return WarmupProfile(
        id=model.id,
        name=model.name,
        description=model.description,
        total_days=model.total_days,
        stages=stages,
        min_session_duration_minutes=model.min_session_duration_minutes,
        max_session_duration_minutes=model.max_session_duration_minutes,
        typing_speed_cpm=model.typing_speed_cpm,
        reaction_probability=model.reaction_probability,
        is_default=model.is_default,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def warmup_profile_entity_to_model(
    entity: WarmupProfile, model: Optional[WarmupProfileModel] = None
) -> WarmupProfileModel:
    """Convert WarmupProfile entity to WarmupProfileModel."""
    if model is None:
        model = WarmupProfileModel()

    model.id = entity.id
    model.name = entity.name
    model.description = entity.description
    model.total_days = entity.total_days
    model.stages = [
        {
            "stage": s.stage,
            "days": s.days,
            "daily_messages": s.daily_messages,
            "join_channels": s.join_channels,
            "join_groups": s.join_groups,
            "reactions_per_day": s.reactions_per_day,
            "can_outreach": s.can_outreach,
        }
        for s in entity.stages
    ]
    model.min_session_duration_minutes = entity.min_session_duration_minutes
    model.max_session_duration_minutes = entity.max_session_duration_minutes
    model.typing_speed_cpm = entity.typing_speed_cpm
    model.reaction_probability = entity.reaction_probability
    model.is_default = entity.is_default
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    return model


def account_warmup_model_to_entity(model: AccountWarmupModel) -> AccountWarmup:
    """Convert AccountWarmupModel to AccountWarmup entity."""
    return AccountWarmup(
        id=model.id,
        account_id=model.account_id,
        profile_id=model.profile_id,
        stage=model.stage,
        status=_enum(WarmupStatus, model.status, WarmupStatus.PENDING),
        started_at=model.started_at,
        stage_started_at=model.stage_started_at,
        completed_at=model.completed_at,
        last_activity_at=model.last_activity_at,
        channels_joined=model.channels_joined,
        groups_joined=model.groups_joined,
        reactions_sent=model.reactions_sent,
        messages_sent=model.messages_sent,
        total_session_minutes=model.total_session_minutes,
        daily_reactions=model.daily_reactions,
        daily_messages=model.daily_messages,
        daily_joins=model.daily_joins,
        last_daily_reset=model.last_daily_reset,
        current_daily_message_limit=model.current_daily_message_limit,
        error_message=model.error_message,
        flood_wait_until=model.flood_wait_until,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def account_warmup_entity_to_model(
    entity: AccountWarmup, model: Optional[AccountWarmupModel] = None
) -> AccountWarmupModel:
    """Convert AccountWarmup entity to AccountWarmupModel."""
    if model is None:
        model = AccountWarmupModel()

    model.id = entity.id
    model.account_id = entity.account_id
    model.profile_id = entity.profile_id
    model.stage = entity.stage
    model.status = entity.status.value if isinstance(entity.status, Enum) else str(entity.status)
    model.started_at = entity.started_at
    model.stage_started_at = entity.stage_started_at
    model.completed_at = entity.completed_at
    model.last_activity_at = entity.last_activity_at
    model.channels_joined = entity.channels_joined
    model.groups_joined = entity.groups_joined
    model.reactions_sent = entity.reactions_sent
    model.messages_sent = entity.messages_sent
    model.total_session_minutes = entity.total_session_minutes
    model.daily_reactions = entity.daily_reactions
    model.daily_messages = entity.daily_messages
    model.daily_joins = entity.daily_joins
    model.last_daily_reset = entity.last_daily_reset
    model.current_daily_message_limit = entity.current_daily_message_limit
    model.error_message = entity.error_message
    model.flood_wait_until = entity.flood_wait_until
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    return model


def account_persona_model_to_entity(model: AccountPersonaModel) -> AccountPersona:
    """Convert AccountPersonaModel to AccountPersona entity."""
    active_hours = model.active_hours or {"start": 9, "end": 22}
    return AccountPersona(
        id=model.id,
        account_id=model.account_id,
        interests=list(model.interests or []),
        activity_pattern=_enum(ActivityPattern, model.activity_pattern, ActivityPattern.OFFICE_HOURS),
        timezone=model.timezone,
        language=model.language,
        typing_speed=model.typing_speed,
        reaction_probability=model.reaction_probability,
        min_response_delay=model.min_response_delay,
        max_response_delay=model.max_response_delay,
        active_hours_start=active_hours.get("start", 9),
        active_hours_end=active_hours.get("end", 22),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def account_persona_entity_to_model(
    entity: AccountPersona, model: Optional[AccountPersonaModel] = None
) -> AccountPersonaModel:
    """Convert AccountPersona entity to AccountPersonaModel."""
    if model is None:
        model = AccountPersonaModel()

    model.id = entity.id
    model.account_id = entity.account_id
    model.interests = list(entity.interests)
    model.activity_pattern = (
        entity.activity_pattern.value
        if isinstance(entity.activity_pattern, Enum)
        else str(entity.activity_pattern)
    )
    model.timezone = entity.timezone
    model.language = entity.language
    model.typing_speed = entity.typing_speed
    model.reaction_probability = entity.reaction_probability
    model.min_response_delay = entity.min_response_delay
    model.max_response_delay = entity.max_response_delay
    model.active_hours = {
        "start": entity.active_hours_start,
        "end": entity.active_hours_end,
    }
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    return model


def interest_category_model_to_entity(model: InterestCategoryModel) -> InterestCategory:
    """Convert InterestCategoryModel to InterestCategory entity."""
    return InterestCategory(
        id=model.id,
        name=model.name,
        description=model.description,
        keywords=list(model.keywords or []),
        created_at=model.created_at,
    )


def interest_category_entity_to_model(
    entity: InterestCategory, model: Optional[InterestCategoryModel] = None
) -> InterestCategoryModel:
    """Convert InterestCategory entity to InterestCategoryModel."""
    if model is None:
        model = InterestCategoryModel()

    model.id = entity.id
    model.name = entity.name
    model.description = entity.description
    model.keywords = list(entity.keywords)
    model.created_at = entity.created_at

    return model


def warmup_channel_model_to_entity(model: WarmupChannelModel) -> WarmupChannel:
    """Convert WarmupChannelModel to WarmupChannel entity."""
    return WarmupChannel(
        id=model.id,
        username=model.username,
        title=model.title,
        category_id=model.category_id,
        language=model.language,
        subscriber_count=model.subscriber_count,
        last_post_at=model.last_post_at,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def warmup_channel_entity_to_model(
    entity: WarmupChannel, model: Optional[WarmupChannelModel] = None
) -> WarmupChannelModel:
    """Convert WarmupChannel entity to WarmupChannelModel."""
    if model is None:
        model = WarmupChannelModel()

    model.id = entity.id
    model.username = entity.username
    model.title = entity.title
    model.category_id = entity.category_id
    model.language = entity.language
    model.subscriber_count = entity.subscriber_count
    model.last_post_at = entity.last_post_at
    model.is_active = entity.is_active
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    return model


def warmup_group_model_to_entity(model: WarmupGroupModel) -> WarmupGroup:
    """Convert WarmupGroupModel to WarmupGroup entity."""
    return WarmupGroup(
        id=model.id,
        username=model.username,
        title=model.title,
        category_id=model.category_id,
        language=model.language,
        can_write=model.can_write,
        member_count=model.member_count,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def warmup_group_entity_to_model(
    entity: WarmupGroup, model: Optional[WarmupGroupModel] = None
) -> WarmupGroupModel:
    """Convert WarmupGroup entity to WarmupGroupModel."""
    if model is None:
        model = WarmupGroupModel()

    model.id = entity.id
    model.username = entity.username
    model.title = entity.title
    model.category_id = entity.category_id
    model.language = entity.language
    model.can_write = entity.can_write
    model.member_count = entity.member_count
    model.is_active = entity.is_active
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    return model


def account_group_model_to_entity(model: AccountGroupModel) -> AccountGroup:
    """Convert AccountGroupModel to AccountGroup entity."""
    from sqlalchemy import inspect

    # Get account_ids from direct_accounts relationship only if already loaded
    # This avoids triggering lazy load in async context
    account_ids = []
    insp = inspect(model)
    if "direct_accounts" in insp.dict:
        # Relationship is already loaded, safe to access
        if model.direct_accounts:
            account_ids = [acc.id for acc in model.direct_accounts]

    return AccountGroup(
        id=model.id,
        name=model.name,
        description=model.description,
        account_ids=account_ids,
        default_warmup_profile_id=model.default_warmup_profile_id,
        default_proxy_group_id=model.default_proxy_group_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        version=getattr(model, "version", 0),
    )


def account_group_entity_to_model(
    entity: AccountGroup, model: Optional[AccountGroupModel] = None
) -> AccountGroupModel:
    """Convert AccountGroup entity to AccountGroupModel."""
    if model is None:
        model = AccountGroupModel()

    model.id = entity.id
    model.name = entity.name
    model.description = entity.description
    model.default_warmup_profile_id = entity.default_warmup_profile_id
    model.default_proxy_group_id = entity.default_proxy_group_id
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at
    model.version = getattr(entity, "version", 0)

    return model


def proxy_group_model_to_entity(model: ProxyGroupModel) -> ProxyGroup:
    """Convert ProxyGroupModel to ProxyGroup entity."""
    return ProxyGroup(
        id=model.id,
        name=model.name,
        description=model.description,
        country_code=model.country_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def proxy_group_entity_to_model(
    entity: ProxyGroup, model: Optional[ProxyGroupModel] = None
) -> ProxyGroupModel:
    """Convert ProxyGroup entity to ProxyGroupModel."""
    if model is None:
        model = ProxyGroupModel()

    model.id = entity.id
    model.name = entity.name
    model.description = entity.description
    model.country_code = entity.country_code
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at

    return model


def warmup_activity_log_model_to_entity(model: WarmupActivityLogModel) -> WarmupActivityLog:
    """Convert WarmupActivityLogModel to WarmupActivityLog."""
    return WarmupActivityLog(
        id=model.id,
        account_id=model.account_id,
        activity_type=model.activity_type,
        target=model.target,
        details=model.details,
        success=model.success,
        error=model.error,
        created_at=model.created_at,
    )


def warmup_activity_log_entity_to_model(
    entity: WarmupActivityLog, model: Optional[WarmupActivityLogModel] = None
) -> WarmupActivityLogModel:
    """Convert WarmupActivityLog to WarmupActivityLogModel."""
    if model is None:
        model = WarmupActivityLogModel()

    model.id = entity.id
    model.account_id = entity.account_id
    model.activity_type = entity.activity_type
    model.target = entity.target
    model.details = entity.details
    model.success = entity.success
    model.error = entity.error
    model.created_at = entity.created_at

    return model
