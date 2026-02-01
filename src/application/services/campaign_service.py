"""
Campaign service.

Handles business logic for campaign management.
"""

from typing import Optional
from uuid import UUID

import structlog

from src.application.interfaces.repository import (
    AccountRepository,
    CampaignRepository,
    UserTargetRepository,
)
from src.domain.entities import (
    AccountStatus,
    Campaign,
    CampaignGoal,
    CampaignPrompt,
    CampaignStatus,
    TargetStatus,
    UserTarget,
)
from src.domain.exceptions import (
    CampaignInvalidStateError,
    CampaignNotConfiguredError,
    CampaignNotFoundError,
)

logger = structlog.get_logger(__name__)


class CampaignService:
    """
    Service for campaign management.
    
    Handles:
    - Campaign creation and configuration
    - Target user management
    - Account assignment
    - Campaign lifecycle
    """
    
    def __init__(
        self,
        campaign_repo: CampaignRepository,
        account_repo: AccountRepository,
        target_repo: UserTargetRepository,
    ):
        self.campaign_repo = campaign_repo
        # Backward compatible aliases (used in API/admin)
        self._campaign_repo = campaign_repo

        self.account_repo = account_repo
        self._account_repo = account_repo

        self.target_repo = target_repo
        self._target_repo = target_repo
    
    async def create_campaign(
        self,
        name: str,
        owner_telegram_id: int,
        description: str = "",
    ) -> Campaign:
        """
        Create a new campaign.
        
        Args:
            name: Campaign name
            owner_telegram_id: Admin Telegram ID
            description: Campaign description
            
        Returns:
            Created campaign
        """
        campaign = Campaign(
            name=name,
            description=description,
            owner_telegram_id=owner_telegram_id,
            status=CampaignStatus.DRAFT,
        )
        
        saved = await self.campaign_repo.save(campaign)
        
        logger.info(
            "Campaign created",
            campaign_id=str(saved.id),
            name=name,
        )
        
        return saved
    
    async def get_campaign(self, campaign_id: UUID) -> Campaign:
        """Get campaign by ID."""
        campaign = await self.campaign_repo.get_by_id(campaign_id)
        if not campaign:
            raise CampaignNotFoundError(str(campaign_id))
        return campaign
    
    async def configure_goal(
        self,
        campaign_id: UUID,
        target_message: str,
        target_url: str = "",
        target_action: str = "",
        min_messages_before_goal: int = 3,
        max_messages_before_goal: int = 10,
    ) -> Campaign:
        """
        Configure campaign goal.
        
        Args:
            campaign_id: Campaign UUID
            target_message: Message to deliver
            target_url: URL to promote
            target_action: Action name
            min_messages_before_goal: Min messages before goal
            max_messages_before_goal: Max messages before goal
            
        Returns:
            Updated campaign
        """
        campaign = await self.get_campaign(campaign_id)
        
        campaign.goal = CampaignGoal(
            target_message=target_message,
            target_url=target_url,
            target_action=target_action,
            min_messages_before_goal=min_messages_before_goal,
            max_messages_before_goal=max_messages_before_goal,
        )
        
        saved = await self.campaign_repo.save(campaign)
        
        logger.info(
            "Campaign goal configured",
            campaign_id=str(campaign_id),
        )
        
        return saved
    
    async def configure_prompt(
        self,
        campaign_id: UUID,
        system_prompt: str,
        first_message_template: str = "",
        goal_transition_hints: Optional[list[str]] = None,
        forbidden_topics: Optional[list[str]] = None,
        language: str = "ru",
        tone: str = "friendly",
    ) -> Campaign:
        """
        Configure campaign LLM prompt.
        
        Args:
            campaign_id: Campaign UUID
            system_prompt: Main system prompt
            first_message_template: Template for first message
            goal_transition_hints: Hints for goal transition
            forbidden_topics: Topics to avoid
            language: Response language
            tone: Conversation tone
            
        Returns:
            Updated campaign
        """
        campaign = await self.get_campaign(campaign_id)
        
        campaign.prompt = CampaignPrompt(
            system_prompt=system_prompt,
            first_message_template=first_message_template,
            goal_transition_hints=goal_transition_hints or [],
            forbidden_topics=forbidden_topics or [],
            language=language,
            tone=tone,
        )
        
        saved = await self.campaign_repo.save(campaign)
        
        logger.info(
            "Campaign prompt configured",
            campaign_id=str(campaign_id),
        )
        
        return saved
    
    async def configure_ai_settings(
        self,
        campaign_id: UUID,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Campaign:
        """Configure AI model settings."""
        campaign = await self.get_campaign(campaign_id)
        
        campaign.ai_model = model
        campaign.ai_temperature = temperature
        campaign.ai_max_tokens = max_tokens
        
        saved = await self.campaign_repo.save(campaign)
        return saved
    
    async def add_account_to_campaign(
        self,
        campaign_id: UUID,
        account_id: UUID,
    ) -> Campaign:
        """Add an account to the campaign."""
        campaign = await self.get_campaign(campaign_id)
        
        # Update account's campaign_id
        account = await self.account_repo.get_by_id(account_id)
        if account:
            account.campaign_id = campaign_id
            await self.account_repo.save(account)
        
        campaign.add_account(account_id)
        saved = await self.campaign_repo.save(campaign)
        
        logger.info(
            "Account added to campaign",
            campaign_id=str(campaign_id),
            account_id=str(account_id),
        )
        
        return saved
    
    async def remove_account_from_campaign(
        self,
        campaign_id: UUID,
        account_id: UUID,
    ) -> Campaign:
        """Remove an account from the campaign."""
        campaign = await self.get_campaign(campaign_id)
        
        # Clear account's campaign_id
        account = await self.account_repo.get_by_id(account_id)
        if account:
            account.campaign_id = None
            await self.account_repo.save(account)
        
        campaign.remove_account(account_id)
        saved = await self.campaign_repo.save(campaign)
        
        return saved
    
    async def add_targets(
        self,
        campaign_id: UUID,
        targets: list[dict],
        source: str = "",
    ) -> int:
        """
        Add target users to campaign.
        
        Args:
            campaign_id: Campaign UUID
            targets: List of target dicts with telegram_id/username/phone
            source: Source identifier
            
        Returns:
            Number of targets added
        """
        campaign = await self.get_campaign(campaign_id)
        
        user_targets = []
        for target in targets:
            try:
                user_target = UserTarget(
                    campaign_id=campaign_id,
                    telegram_id=target.get("telegram_id"),
                    username=target.get("username"),
                    phone=target.get("phone"),
                    first_name=target.get("first_name", ""),
                    last_name=target.get("last_name", ""),
                    source=source,
                    priority=target.get("priority", 0),
                    tags=target.get("tags", []),
                )
                user_targets.append(user_target)
            except ValueError:
                # Skip invalid targets (no identifier)
                continue
        
        count = await self.target_repo.bulk_create(user_targets)
        
        # Update campaign stats
        campaign.stats.total_targets += count
        await self.campaign_repo.save(campaign)
        
        logger.info(
            "Targets added to campaign",
            campaign_id=str(campaign_id),
            count=count,
        )
        
        return count
    
    async def activate_campaign(self, campaign_id: UUID) -> Campaign:
        """
        Activate a campaign.

        Args:
            campaign_id: Campaign UUID

        Returns:
            Activated campaign

        Raises:
            CampaignNotConfiguredError: If not fully configured
        """
        campaign = await self.get_campaign(campaign_id)

        if not campaign.prompt.system_prompt:
            raise CampaignNotConfiguredError(str(campaign_id), "system_prompt")

        if not campaign.account_ids:
            raise CampaignNotConfiguredError(str(campaign_id), "accounts")

        # Check target count
        target_count = await self.target_repo.count_by_campaign(campaign_id)
        if target_count == 0:
            raise CampaignNotConfiguredError(str(campaign_id), "targets")

        # Activate all accounts assigned to this campaign
        accounts = await self._account_repo.list_by_campaign(campaign_id)
        activated_count = 0
        for account in accounts:
            if account.status not in (AccountStatus.BANNED, AccountStatus.ACTIVE):
                try:
                    account.activate()
                    await self._account_repo.save(account)
                    activated_count += 1
                except ValueError:
                    # Skip banned accounts
                    pass

        campaign.activate()
        saved = await self.campaign_repo.save(campaign)

        logger.info(
            "Campaign activated",
            campaign_id=str(campaign_id),
            accounts_activated=activated_count,
        )

        return saved
    
    async def pause_campaign(self, campaign_id: UUID) -> Campaign:
        """Pause a campaign."""
        campaign = await self.get_campaign(campaign_id)
        campaign.pause()
        saved = await self.campaign_repo.save(campaign)
        
        logger.info("Campaign paused", campaign_id=str(campaign_id))
        return saved
    
    async def complete_campaign(self, campaign_id: UUID) -> Campaign:
        """Complete a campaign."""
        campaign = await self.get_campaign(campaign_id)
        campaign.complete()
        saved = await self.campaign_repo.save(campaign)
        
        logger.info("Campaign completed", campaign_id=str(campaign_id))
        return saved
    
    async def cancel_campaign(self, campaign_id: UUID) -> Campaign:
        """Cancel a campaign."""
        campaign = await self.get_campaign(campaign_id)
        campaign.cancel()
        saved = await self.campaign_repo.save(campaign)
        
        logger.info("Campaign cancelled", campaign_id=str(campaign_id))
        return saved
    
    async def list_active_campaigns(self) -> list[Campaign]:
        """List all active campaigns."""
        return await self.campaign_repo.list_active()
    
    async def list_campaigns_by_owner(
        self,
        owner_telegram_id: int,
    ) -> list[Campaign]:
        """List campaigns owned by a user."""
        return await self.campaign_repo.list_by_owner(owner_telegram_id)
    
    async def get_campaign_stats(self, campaign_id: UUID) -> dict:
        """Get detailed campaign statistics."""
        campaign = await self.get_campaign(campaign_id)
        
        # Get fresh target counts
        total = await self.target_repo.count_by_campaign(campaign_id)
        pending = await self.target_repo.count_by_campaign(
            campaign_id, TargetStatus.PENDING
        )
        contacted = await self.target_repo.count_by_campaign(
            campaign_id, TargetStatus.CONTACTED
        )
        in_progress = await self.target_repo.count_by_campaign(
            campaign_id, TargetStatus.IN_PROGRESS
        )
        converted = await self.target_repo.count_by_campaign(
            campaign_id, TargetStatus.CONVERTED
        )
        failed = await self.target_repo.count_by_campaign(
            campaign_id, TargetStatus.FAILED
        )
        
        return {
            "campaign_id": str(campaign_id),
            "name": campaign.name,
            "status": campaign.status.value,
            "targets": {
                "total": total,
                "pending": pending,
                "contacted": contacted,
                "in_progress": in_progress,
                "converted": converted,
                "failed": failed,
            },
            "stats": {
                "response_rate": campaign.stats.response_rate,
                "conversion_rate": campaign.stats.conversion_rate,
                "total_messages": campaign.stats.total_messages_sent,
                "total_tokens": campaign.stats.total_tokens_used,
            },
            "accounts": len(campaign.account_ids),
        }
