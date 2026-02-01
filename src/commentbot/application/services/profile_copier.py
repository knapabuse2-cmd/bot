"""
Profile Copier Service.

Copies channel profile (name, photo) to account when assigned.
"""

from typing import Optional
from uuid import UUID

import structlog

from src.commentbot.domain.entities import Account, Channel, ChannelAssignment
from src.commentbot.infrastructure.database.repository import (
    AccountRepository,
    ChannelRepository,
    ChannelAssignmentRepository,
)
from src.commentbot.infrastructure.telegram import CommentBotClient

logger = structlog.get_logger(__name__)


class ProfileCopier:
    """
    Copies channel profile to account.

    When an account is assigned to a channel, copies:
    - Channel title → Account first/last name
    - Channel photo → Account profile photo
    """

    def __init__(
        self,
        account_repo: AccountRepository,
        channel_repo: ChannelRepository,
    ):
        self.account_repo = account_repo
        self.channel_repo = channel_repo

    async def copy_profile_for_assignment(
        self,
        account: Account,
        channel: Channel,
        copy_name: bool = True,
        copy_photo: bool = True,
    ) -> dict:
        """
        Copy channel profile to account.

        Args:
            account: Account to update
            channel: Channel to copy from
            copy_name: Copy channel title as name
            copy_photo: Copy channel avatar

        Returns:
            Dict with results
        """
        if not account.session_data:
            return {"success": False, "error": "No session data"}

        result = {
            "success": False,
            "name_copied": False,
            "photo_copied": False,
            "channel_title": None,
            "error": None,
        }

        try:
            # Create client and connect
            client = CommentBotClient(
                account_id=str(account.id),
                session_data=account.session_data,
            )

            async with client:
                # Get channel link
                channel_link = channel.username or channel.link

                # Copy profile
                copy_result = await client.copy_channel_profile(
                    channel=channel_link,
                    copy_name=copy_name,
                    copy_photo=copy_photo,
                    copy_about=False,  # Don't copy about - might be too long
                )

                result.update(copy_result)

            logger.info(
                "Profile copied for assignment",
                account_id=str(account.id),
                channel_id=str(channel.id),
                name_copied=result["name_copied"],
                photo_copied=result["photo_copied"],
            )

            return result

        except Exception as e:
            result["error"] = str(e)
            logger.error(
                "Failed to copy profile",
                account_id=str(account.id),
                channel_id=str(channel.id),
                error=str(e),
            )
            return result

    async def copy_for_all_assignments(
        self,
        campaign_id: UUID,
        owner_id: int,
        assignment_repo: ChannelAssignmentRepository,
    ) -> dict:
        """
        Copy profiles for all assignments in a campaign.

        Each account gets the profile of its first assigned channel.

        Args:
            campaign_id: Campaign ID
            owner_id: Owner user ID
            assignment_repo: Assignment repository

        Returns:
            Dict with stats
        """
        assignments = await assignment_repo.list_by_campaign(campaign_id)

        # Group by account - each account only needs one profile copy
        account_channels: dict[UUID, Channel] = {}

        for assignment in assignments:
            if assignment.account_id not in account_channels:
                channel = await self.channel_repo.get_by_id(assignment.channel_id)
                if channel:
                    account_channels[assignment.account_id] = channel

        copied = 0
        failed = 0

        for account_id, channel in account_channels.items():
            account = await self.account_repo.get_by_id(account_id)
            if not account:
                continue

            result = await self.copy_profile_for_assignment(account, channel)

            if result["success"]:
                copied += 1
            else:
                failed += 1

        return {
            "total": len(account_channels),
            "copied": copied,
            "failed": failed,
        }
