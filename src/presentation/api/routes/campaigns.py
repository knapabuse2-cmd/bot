"""
Campaigns API routes.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

import structlog

from src.application.services import CampaignService
from src.domain.entities import CampaignStatus
from src.domain.exceptions import CampaignNotFoundError, DomainException

logger = structlog.get_logger(__name__)

from ..dependencies import get_campaign_service, get_target_repo
from ..schemas import (
    CampaignCreate,
    CampaignUpdate,
    CampaignResponse,
    CampaignListResponse,
    CampaignStatsResponse,
    CampaignDetailStatsResponse,
    TargetCreate,
    TargetBulkCreate,
    TargetResponse,
)

router = APIRouter()


@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: CampaignService = Depends(get_campaign_service),
):
    """List all campaigns."""
    repo = service._campaign_repo
    
    if status:
        try:
            campaign_status = CampaignStatus(status)
            campaigns = await repo.list_by_status(campaign_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
    else:
        campaigns = await repo.list_all(limit=per_page * page)
    
    # Pagination
    total = len(campaigns)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = campaigns[start:end]
    
    return CampaignListResponse(
        items=[_campaign_to_response(c) for c in paginated],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/active", response_model=List[CampaignResponse])
async def list_active_campaigns(
    service: CampaignService = Depends(get_campaign_service),
):
    """List active campaigns."""
    campaigns = await service.list_active_campaigns()
    return [_campaign_to_response(c) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """Get campaign by ID."""
    try:
        campaign = await service.get_campaign(campaign_id)
        return _campaign_to_response(campaign)
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")


@router.post("", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    data: CampaignCreate,
    service: CampaignService = Depends(get_campaign_service),
):
    """Create a new campaign."""
    try:
        campaign = await service.create_campaign(
            name=data.name,
            description=data.description,
            owner_telegram_id=data.owner_telegram_id,
        )
        return _campaign_to_response(campaign)
    except DomainException as e:
        raise HTTPException(400, e.code)
    except Exception as e:
        logger.error("Campaign operation error", error=str(e))
        raise HTTPException(400, "Operation failed")


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: UUID,
    data: CampaignUpdate,
    service: CampaignService = Depends(get_campaign_service),
):
    """Update campaign."""
    try:
        campaign = await service.get_campaign(campaign_id)
        
        # Update goal
        if data.goal:
            fields = getattr(data.goal, "model_fields_set", set())
            target_message = data.goal.target_message if "target_message" in fields else campaign.goal.target_message
            target_url = data.goal.target_url if "target_url" in fields else campaign.goal.target_url
            min_messages = data.goal.min_messages_before_goal if "min_messages_before_goal" in fields else campaign.goal.min_messages_before_goal
            max_messages = data.goal.max_messages_before_goal if "max_messages_before_goal" in fields else campaign.goal.max_messages_before_goal

            await service.configure_goal(
                campaign_id=campaign_id,
                target_message=target_message or "",
                target_url=target_url or "",
                target_action=campaign.goal.target_action,
                min_messages_before_goal=min_messages,
                max_messages_before_goal=max_messages,
            )
        
        # Update prompt
        if data.prompt:
            fields = getattr(data.prompt, "model_fields_set", set())
            system_prompt = data.prompt.system_prompt if "system_prompt" in fields else campaign.prompt.system_prompt
            first_message_template = data.prompt.first_message_template if "first_message_template" in fields else campaign.prompt.first_message_template
            forbidden_topics = data.prompt.forbidden_topics if "forbidden_topics" in fields else campaign.prompt.forbidden_topics
            goal_hints = data.prompt.goal_hints if "goal_hints" in fields else campaign.prompt.goal_transition_hints
            language = data.prompt.language if "language" in fields else campaign.prompt.language
            tone = data.prompt.tone if "tone" in fields else campaign.prompt.tone

            await service.configure_prompt(
                campaign_id=campaign_id,
                system_prompt=system_prompt or "",
                first_message_template=first_message_template or "",
                goal_transition_hints=goal_hints or [],
                forbidden_topics=forbidden_topics or [],
                language=language or "ru",
                tone=tone or "friendly",
            )
        
        # Update AI settings
        if any([data.ai_model, data.ai_temperature, data.ai_max_tokens]):
            await service.configure_ai_settings(
                campaign_id=campaign_id,
                model=data.ai_model,
                temperature=data.ai_temperature,
                max_tokens=data.ai_max_tokens,
            )
        
        return _campaign_to_response(await service.get_campaign(campaign_id))
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")
    except DomainException as e:
        raise HTTPException(400, e.code)
    except Exception as e:
        logger.error("Campaign operation error", error=str(e))
        raise HTTPException(400, "Operation failed")


@router.post("/{campaign_id}/activate", response_model=CampaignResponse)
async def activate_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """Activate a campaign."""
    try:
        campaign = await service.activate_campaign(campaign_id)
        return _campaign_to_response(campaign)
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")
    except DomainException as e:
        raise HTTPException(400, e.code)
    except Exception as e:
        logger.error("Campaign operation error", error=str(e))
        raise HTTPException(400, "Operation failed")


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """Pause a campaign."""
    try:
        campaign = await service.pause_campaign(campaign_id)
        return _campaign_to_response(campaign)
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")


@router.post("/{campaign_id}/complete", response_model=CampaignResponse)
async def complete_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """Mark campaign as completed."""
    try:
        campaign = await service.complete_campaign(campaign_id)
        return _campaign_to_response(campaign)
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """Delete a campaign."""
    deleted = await service._campaign_repo.delete(campaign_id)
    if not deleted:
        raise HTTPException(404, "Campaign not found")


# =============================================================================
# Campaign Statistics
# =============================================================================

@router.get("/{campaign_id}/stats", response_model=CampaignDetailStatsResponse)
async def get_campaign_stats(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """Get detailed campaign statistics."""
    try:
        campaign = await service.get_campaign(campaign_id)
        stats = await service.get_campaign_stats(campaign_id)
        
        return CampaignDetailStatsResponse(
            campaign_id=campaign.id,
            name=campaign.name,
            status=campaign.status.value,
            targets=stats["targets"],
            accounts=stats["accounts"],
            stats=CampaignStatsResponse(**stats["stats"]),
        )
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")


# =============================================================================
# Campaign Targets
# =============================================================================

@router.get("/{campaign_id}/targets")
async def list_campaign_targets(
    campaign_id: UUID,
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: CampaignService = Depends(get_campaign_service),
):
    """List campaign targets."""
    try:
        await service.get_campaign(campaign_id)
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")
    
    repo = service._target_repo
    targets = await repo.list_by_campaign(campaign_id, limit=per_page * page)
    
    # Pagination
    total = len(targets)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = targets[start:end]
    
    return {
        "items": [TargetResponse.model_validate(t) for t in paginated],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.post("/{campaign_id}/targets", status_code=201)
async def add_campaign_targets(
    campaign_id: UUID,
    data: TargetBulkCreate,
    service: CampaignService = Depends(get_campaign_service),
):
    """Add targets to campaign."""
    try:
        targets = [
            {
                "telegram_id": t.telegram_id,
                "username": t.telegram_username,
                "phone": t.phone,
                "first_name": t.first_name,
                "last_name": t.last_name,
                "priority": t.priority,
                "tags": t.tags,
            }
            for t in data.targets
        ]
        
        count = await service.add_targets(
            campaign_id=campaign_id,
            targets=targets,
            source=data.source,
        )
        
        return {"added": count}
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")
    except DomainException as e:
        raise HTTPException(400, e.code)
    except Exception as e:
        logger.error("Campaign operation error", error=str(e))
        raise HTTPException(400, "Operation failed")


# =============================================================================
# Campaign Accounts
# =============================================================================

@router.get("/{campaign_id}/accounts")
async def list_campaign_accounts(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """List accounts assigned to campaign."""
    try:
        campaign = await service.get_campaign(campaign_id)
        accounts = await service._account_repo.list_by_campaign(campaign_id)
        
        return {
            "campaign_id": str(campaign_id),
            "account_ids": [str(a.id) for a in accounts],
            "count": len(accounts),
        }
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")


@router.post("/{campaign_id}/accounts/{account_id}", status_code=201)
async def add_account_to_campaign(
    campaign_id: UUID,
    account_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """Add account to campaign."""
    try:
        await service.add_account_to_campaign(campaign_id, account_id)
        return {"status": "added"}
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")
    except DomainException as e:
        raise HTTPException(400, e.code)
    except Exception as e:
        logger.error("Campaign operation error", error=str(e))
        raise HTTPException(400, "Operation failed")


@router.delete("/{campaign_id}/accounts/{account_id}", status_code=204)
async def remove_account_from_campaign(
    campaign_id: UUID,
    account_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
):
    """Remove account from campaign."""
    try:
        await service.remove_account_from_campaign(campaign_id, account_id)
    except CampaignNotFoundError:
        raise HTTPException(404, "Campaign not found")


def _campaign_to_response(campaign) -> CampaignResponse:
    """Convert campaign entity to response."""
    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        description=campaign.description,
        owner_telegram_id=campaign.owner_telegram_id,
        status=campaign.status.value,
        goal=campaign.goal.__dict__ if campaign.goal else {},
        prompt=campaign.prompt.__dict__ if campaign.prompt else {},
        stats=CampaignStatsResponse(
            total_targets=campaign.stats.total_targets,
            contacted=campaign.stats.contacted,
            responded=campaign.stats.responded,
            goals_reached=campaign.stats.goals_reached,
            completed=campaign.stats.completed,
            failed=campaign.stats.failed,
            messages_sent=campaign.stats.messages_sent,
            tokens_used=campaign.stats.tokens_used,
            response_rate=campaign.stats.response_rate,
            conversion_rate=campaign.stats.conversion_rate,
        ),
        account_ids=campaign.account_ids or [],
        ai_model=campaign.ai_model,
        ai_temperature=campaign.ai_temperature,
        ai_max_tokens=campaign.ai_max_tokens,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )
