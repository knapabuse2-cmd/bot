"""
Statistics API routes.
"""

from fastapi import APIRouter, Depends

from src.application.services import AccountService, CampaignService
from src.infrastructure.database.repositories import (
    PostgresProxyRepository,
    PostgresDialogueRepository,
)
from src.workers import get_worker_manager

from ..dependencies import (
    get_account_service,
    get_campaign_service,
    get_proxy_repo,
    get_dialogue_repo,
)
from ..schemas import SystemStatsResponse, AccountStatsResponse

router = APIRouter()


@router.get("", response_model=SystemStatsResponse)
async def get_system_stats(
    account_service: AccountService = Depends(get_account_service),
    campaign_service: CampaignService = Depends(get_campaign_service),
    proxy_repo: PostgresProxyRepository = Depends(get_proxy_repo),
    dialogue_repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """Get system-wide statistics."""
    # Account stats
    account_stats = await account_service.get_account_stats()
    
    # Campaign stats
    active_campaigns = await campaign_service.list_active_campaigns()
    all_campaigns = await campaign_service._campaign_repo.list_all(limit=1000)
    
    campaign_stats = {
        "total": len(all_campaigns),
        "active": len(active_campaigns),
        "draft": sum(1 for c in all_campaigns if c.status.value == "draft"),
        "paused": sum(1 for c in all_campaigns if c.status.value == "paused"),
        "completed": sum(1 for c in all_campaigns if c.status.value == "completed"),
    }
    
    # Aggregate campaign metrics
    total_targets = sum(c.stats.total_targets for c in all_campaigns)
    total_contacted = sum(c.stats.contacted for c in all_campaigns)
    total_converted = sum(c.stats.goals_reached for c in all_campaigns)
    
    campaign_stats["total_targets"] = total_targets
    campaign_stats["total_contacted"] = total_contacted
    campaign_stats["total_converted"] = total_converted
    
    if total_contacted > 0:
        campaign_stats["overall_conversion_rate"] = round(
            (total_converted / total_contacted) * 100, 2
        )
    else:
        campaign_stats["overall_conversion_rate"] = 0.0
    
    # Proxy stats
    all_proxies = await proxy_repo.list_all(limit=1000)
    available_proxies = await proxy_repo.count_available()
    
    proxy_stats = {
        "total": len(all_proxies),
        "available": available_proxies,
        "assigned": sum(1 for p in all_proxies if p.assigned_account_id),
    }
    
    # Dialogue stats
    all_dialogues = await dialogue_repo.list_all(limit=10000)
    
    dialogue_stats = {
        "total": len(all_dialogues),
        "active": sum(1 for d in all_dialogues if d.status.value == "active"),
        "goal_reached": sum(1 for d in all_dialogues if d.goal_reached),
        "completed": sum(1 for d in all_dialogues if d.status.value == "completed"),
        "failed": sum(1 for d in all_dialogues if d.status.value == "failed"),
    }
    
    # Worker stats
    try:
        manager = get_worker_manager()
        worker_stats = manager.get_stats()
    except Exception:
        worker_stats = {"running": False, "total_workers": 0, "active_workers": 0}
    
    return SystemStatsResponse(
        accounts=account_stats,
        campaigns=campaign_stats,
        proxies=proxy_stats,
        dialogues=dialogue_stats,
        workers=worker_stats,
    )


@router.get("/accounts", response_model=AccountStatsResponse)
async def get_account_stats(
    service: AccountService = Depends(get_account_service),
):
    """Get account statistics."""
    stats = await service.get_account_stats()
    return AccountStatsResponse(**stats)


@router.get("/campaigns")
async def get_campaign_stats(
    service: CampaignService = Depends(get_campaign_service),
):
    """Get campaign statistics."""
    active = await service.list_active_campaigns()
    all_campaigns = await service._campaign_repo.list_all(limit=100)
    
    campaigns = []
    for c in all_campaigns:
        stats = await service.get_campaign_stats(c.id)
        campaigns.append({
            "id": str(c.id),
            "name": c.name,
            "status": c.status.value,
            "targets": stats["targets"],
            "accounts": stats["accounts"],
            "response_rate": stats["stats"]["response_rate"],
            "conversion_rate": stats["stats"]["conversion_rate"],
        })
    
    return {
        "total": len(all_campaigns),
        "active": len(active),
        "campaigns": campaigns,
    }


@router.get("/workers")
async def get_worker_stats():
    """Get worker statistics."""
    try:
        manager = get_worker_manager()
        return manager.get_stats()
    except Exception as e:
        return {
            "running": False,
            "error": str(e),
        }
