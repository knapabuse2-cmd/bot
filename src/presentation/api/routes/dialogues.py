"""
Dialogues API routes.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from src.infrastructure.database.repositories import PostgresDialogueRepository
from src.domain.entities import DialogueStatus

from ..dependencies import get_dialogue_repo
from ..schemas import (
    DialogueResponse,
    DialogueDetailResponse,
    DialogueListResponse,
    MessageResponse,
)

router = APIRouter()


@router.get("", response_model=DialogueListResponse)
async def list_dialogues(
    account_id: Optional[UUID] = Query(None, description="Filter by account"),
    campaign_id: Optional[UUID] = Query(None, description="Filter by campaign"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """List dialogues with filters."""
    if account_id:
        dialogues = await repo.list_by_account(account_id, limit=per_page * page)
    elif campaign_id:
        dialogues = await repo.list_by_campaign(campaign_id, limit=per_page * page)
    else:
        dialogues = await repo.list_all(limit=per_page * page)
    
    # Filter by status if specified
    if status:
        try:
            dialogue_status = DialogueStatus(status)
            dialogues = [d for d in dialogues if d.status == dialogue_status]
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
    
    # Pagination
    total = len(dialogues)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = dialogues[start:end]
    
    return DialogueListResponse(
        items=[_dialogue_to_response(d) for d in paginated],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/pending")
async def list_pending_dialogues(
    account_id: Optional[UUID] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """List dialogues pending action."""
    dialogues = await repo.list_pending_actions(
        account_id=account_id,
        limit=limit,
    )
    
    return {
        "items": [_dialogue_to_response(d) for d in dialogues],
        "count": len(dialogues),
    }


@router.get("/{dialogue_id}", response_model=DialogueDetailResponse)
async def get_dialogue(
    dialogue_id: UUID,
    repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """Get dialogue with messages."""
    dialogue = await repo.get_by_id(dialogue_id)
    if not dialogue:
        raise HTTPException(404, "Dialogue not found")
    
    return DialogueDetailResponse(
        **_dialogue_to_response(dialogue).model_dump(),
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role.value,
                content=m.content,
                telegram_message_id=m.telegram_message_id,
                ai_generated=m.ai_generated,
                tokens_used=m.tokens_used,
                created_at=m.timestamp,
            )
            for m in dialogue.messages
        ],
    )


@router.get("/{dialogue_id}/messages")
async def get_dialogue_messages(
    dialogue_id: UUID,
    repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """Get dialogue messages."""
    dialogue = await repo.get_by_id(dialogue_id)
    if not dialogue:
        raise HTTPException(404, "Dialogue not found")
    
    return {
        "dialogue_id": str(dialogue_id),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role.value,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
                "ai_generated": m.ai_generated,
            }
            for m in dialogue.messages
        ],
        "count": len(dialogue.messages),
    }


@router.post("/{dialogue_id}/complete", response_model=DialogueResponse)
async def complete_dialogue(
    dialogue_id: UUID,
    repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """Mark dialogue as completed."""
    dialogue = await repo.get_by_id(dialogue_id)
    if not dialogue:
        raise HTTPException(404, "Dialogue not found")
    
    dialogue.mark_completed()
    await repo.save(dialogue)
    
    return _dialogue_to_response(dialogue)


@router.post("/{dialogue_id}/fail", response_model=DialogueResponse)
async def fail_dialogue(
    dialogue_id: UUID,
    reason: str = Query(..., description="Failure reason"),
    repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """Mark dialogue as failed."""
    dialogue = await repo.get_by_id(dialogue_id)
    if not dialogue:
        raise HTTPException(404, "Dialogue not found")
    
    dialogue.mark_failed(reason)
    await repo.save(dialogue)
    
    return _dialogue_to_response(dialogue)


@router.get("/stats/by-account/{account_id}")
async def get_account_dialogue_stats(
    account_id: UUID,
    repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """Get dialogue statistics for an account."""
    dialogues = await repo.list_by_account(account_id, limit=10000)
    
    by_status = {}
    for d in dialogues:
        status = d.status.value
        by_status[status] = by_status.get(status, 0) + 1
    
    goal_reached = sum(1 for d in dialogues if d.goal_reached)
    total_messages = sum(d.messages_count for d in dialogues)
    
    return {
        "account_id": str(account_id),
        "total_dialogues": len(dialogues),
        "by_status": by_status,
        "goal_reached": goal_reached,
        "goal_rate": round((goal_reached / len(dialogues) * 100), 2) if dialogues else 0,
        "total_messages": total_messages,
        "avg_messages_per_dialogue": round(total_messages / len(dialogues), 2) if dialogues else 0,
    }


@router.get("/stats/by-campaign/{campaign_id}")
async def get_campaign_dialogue_stats(
    campaign_id: UUID,
    repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
):
    """Get dialogue statistics for a campaign."""
    dialogues = await repo.list_by_campaign(campaign_id, limit=10000)
    
    by_status = {}
    for d in dialogues:
        status = d.status.value
        by_status[status] = by_status.get(status, 0) + 1
    
    goal_reached = sum(1 for d in dialogues if d.goal_reached)
    total_messages = sum(d.messages_count for d in dialogues)
    
    # Get unique accounts
    accounts = set(d.account_id for d in dialogues)
    
    return {
        "campaign_id": str(campaign_id),
        "total_dialogues": len(dialogues),
        "unique_accounts": len(accounts),
        "by_status": by_status,
        "goal_reached": goal_reached,
        "goal_rate": round((goal_reached / len(dialogues) * 100), 2) if dialogues else 0,
        "total_messages": total_messages,
        "avg_messages_per_dialogue": round(total_messages / len(dialogues), 2) if dialogues else 0,
    }


def _dialogue_to_response(dialogue) -> DialogueResponse:
    """Convert dialogue entity to response."""
    return DialogueResponse(
        id=dialogue.id,
        account_id=dialogue.account_id,
        campaign_id=dialogue.campaign_id,
        target_id=dialogue.target_id,
        target_telegram_id=dialogue.target_telegram_id,
        target_username=dialogue.target_username,
        status=dialogue.status.value,
        goal_reached=dialogue.goal_reached,
        goal_reached_at=dialogue.goal_reached_at,
        messages_count=dialogue.messages_count,
        last_message_at=dialogue.last_message_at,
        next_action_at=dialogue.next_action_at,
        fail_reason=dialogue.fail_reason,
        created_at=dialogue.created_at,
        updated_at=dialogue.updated_at,
    )
