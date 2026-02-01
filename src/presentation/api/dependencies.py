"""
API dependencies.

FastAPI dependency injection for services and repositories.
"""

from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database import get_session
from src.infrastructure.database.repositories import (
    PostgresAccountRepository,
    PostgresCampaignRepository,
    PostgresDialogueRepository,
    PostgresProxyRepository,
    PostgresUserTargetRepository,
)
from src.infrastructure.ai import get_ai_provider
from src.application.services import (
    AccountService,
    CampaignService,
    DialogueService,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency."""
    async with get_session() as session:
        yield session


# Repository dependencies

async def get_account_repo(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresAccountRepository:
    """Get account repository."""
    return PostgresAccountRepository(session)


async def get_campaign_repo(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresCampaignRepository:
    """Get campaign repository."""
    return PostgresCampaignRepository(session)


async def get_dialogue_repo(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresDialogueRepository:
    """Get dialogue repository."""
    return PostgresDialogueRepository(session)


async def get_proxy_repo(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresProxyRepository:
    """Get proxy repository."""
    return PostgresProxyRepository(session)


async def get_target_repo(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresUserTargetRepository:
    """Get target repository."""
    return PostgresUserTargetRepository(session)


# Service dependencies

async def get_account_service(
    account_repo: PostgresAccountRepository = Depends(get_account_repo),
    proxy_repo: PostgresProxyRepository = Depends(get_proxy_repo),
) -> AccountService:
    """Get account service."""
    return AccountService(account_repo, proxy_repo)


async def get_campaign_service(
    campaign_repo: PostgresCampaignRepository = Depends(get_campaign_repo),
    account_repo: PostgresAccountRepository = Depends(get_account_repo),
    target_repo: PostgresUserTargetRepository = Depends(get_target_repo),
) -> CampaignService:
    """Get campaign service."""
    return CampaignService(campaign_repo, account_repo, target_repo)


async def get_dialogue_service(
    dialogue_repo: PostgresDialogueRepository = Depends(get_dialogue_repo),
    campaign_repo: PostgresCampaignRepository = Depends(get_campaign_repo),
    target_repo: PostgresUserTargetRepository = Depends(get_target_repo),
) -> DialogueService:
    """Get dialogue service."""
    return DialogueService(
        dialogue_repo=dialogue_repo,
        campaign_repo=campaign_repo,
        target_repo=target_repo,
        ai_provider=get_ai_provider(),
    )
