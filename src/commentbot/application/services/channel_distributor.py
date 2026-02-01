"""
Channel Distributor Service.

Handles:
- Distribution of channels across accounts
- Account swapping when blocked/failed
- Load balancing between accounts
- Auto-copy channel profile on swap
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

import structlog

from src.commentbot.domain.entities import (
    Account,
    Channel,
    ChannelAssignment,
    AssignmentStatus,
    ChannelStatus,
)
from src.commentbot.infrastructure.database.repository import (
    AccountRepository,
    ChannelRepository,
    ChannelAssignmentRepository,
    CampaignRepository,
)
from src.commentbot.infrastructure.telegram import CommentBotClient

logger = structlog.get_logger(__name__)


class ChannelDistributor:
    """
    Distributes channels across accounts and handles swapping.

    Logic:
    1. Initial distribution - evenly split channels across available accounts
    2. On failure - try to swap with another account that has working access
    3. Load balancing - distribute to accounts with fewer assignments first
    """

    def __init__(
        self,
        account_repo: AccountRepository,
        channel_repo: ChannelRepository,
        assignment_repo: ChannelAssignmentRepository,
        campaign_repo: Optional[CampaignRepository] = None,
    ):
        self.account_repo = account_repo
        self.channel_repo = channel_repo
        self.assignment_repo = assignment_repo
        self.campaign_repo = campaign_repo

    async def distribute_channels(
        self,
        campaign_id: UUID,
        owner_id: int,
    ) -> dict:
        """
        Distribute unassigned channels across available accounts.

        Args:
            campaign_id: Campaign to distribute channels for
            owner_id: Owner user ID

        Returns:
            Dict with distribution stats
        """
        # Get available accounts
        accounts = await self.account_repo.list_available_for_work(owner_id)
        if not accounts:
            logger.warning("No available accounts for distribution", owner_id=owner_id)
            return {"error": "No available accounts", "assigned": 0}

        # Get unassigned channels
        unassigned = await self.channel_repo.list_unassigned(campaign_id)
        if not unassigned:
            return {"message": "All channels already assigned", "assigned": 0}

        # Get current assignment counts per account
        account_loads = {}
        for account in accounts:
            count = await self.assignment_repo.count_by_account(account.id)
            account_loads[account.id] = count

        assigned_count = 0
        # Track accounts to copy profile for (first channel per account)
        accounts_needing_profile: dict[UUID, UUID] = {}  # account_id -> channel_id

        for channel in unassigned:
            # Find account with least assignments
            best_account_id = min(account_loads.keys(), key=lambda x: account_loads[x])

            # Create assignment
            assignment = ChannelAssignment(
                channel_id=channel.id,
                account_id=best_account_id,
                campaign_id=campaign_id,
                owner_id=owner_id,
            )
            await self.assignment_repo.save(assignment)

            # Track first channel for each account (for profile copy)
            if best_account_id not in accounts_needing_profile:
                accounts_needing_profile[best_account_id] = channel.id

            # Update load count
            account_loads[best_account_id] += 1
            assigned_count += 1

            logger.info(
                "Channel assigned",
                channel_id=str(channel.id),
                account_id=str(best_account_id),
            )

        # Copy profiles for accounts with new assignments
        profiles_copied = 0
        account_map = {a.id: a for a in accounts}
        for account_id, channel_id in accounts_needing_profile.items():
            account = account_map.get(account_id)
            if account:
                success = await self._copy_channel_profile_to_account(
                    account, channel_id, campaign_id
                )
                if success:
                    profiles_copied += 1

        return {
            "assigned": assigned_count,
            "total_channels": len(unassigned),
            "accounts_used": len(accounts),
            "profiles_copied": profiles_copied,
        }

    async def handle_failure(
        self,
        assignment_id: UUID,
        error: str,
    ) -> Optional[ChannelAssignment]:
        """
        Handle assignment failure - record it and swap if needed.

        Args:
            assignment_id: Failed assignment ID
            error: Error message

        Returns:
            Updated assignment (possibly with new account)
        """
        assignment = await self.assignment_repo.get_by_id(assignment_id)
        if not assignment:
            return None

        # Record failure
        should_swap = assignment.record_failure()

        if should_swap:
            # Try to find another account to swap with
            new_assignment = await self._try_swap_account(assignment, error)
            if new_assignment:
                return new_assignment

            # No swap possible - mark as blocked
            assignment.mark_blocked()

        await self.assignment_repo.save(assignment)
        return assignment

    async def handle_success(self, assignment_id: UUID) -> Optional[ChannelAssignment]:
        """
        Handle successful comment - reset failure counter.

        Args:
            assignment_id: Assignment ID

        Returns:
            Updated assignment
        """
        assignment = await self.assignment_repo.get_by_id(assignment_id)
        if not assignment:
            return None

        assignment.record_success()
        await self.assignment_repo.save(assignment)
        return assignment

    async def _try_swap_account(
        self,
        assignment: ChannelAssignment,
        error: str,
    ) -> Optional[ChannelAssignment]:
        """
        Try to swap assignment to a different account.

        Strategy:
        1. Find other accounts with fewer failures on this channel
        2. Look for accounts that work on similar channels successfully
        3. Prefer accounts with less load
        4. Auto-copy channel profile to new account after swap

        Args:
            assignment: Assignment to swap
            error: Error that caused the swap need

        Returns:
            Updated assignment if swap successful, None otherwise
        """
        # Get available accounts (excluding current)
        accounts = await self.account_repo.list_available_for_work(assignment.owner_id)
        accounts = [a for a in accounts if a.id != assignment.account_id]

        if not accounts:
            logger.warning(
                "No other accounts available for swap",
                assignment_id=str(assignment.id),
            )
            return None

        # Get assignment counts for load balancing
        account_loads = {}
        for account in accounts:
            count = await self.assignment_repo.count_by_account(account.id)
            account_loads[account.id] = count

        # Check if this account previously failed on this channel
        # (don't swap back to an account that already failed)
        blocked_accounts = set()
        if assignment.previous_account_id:
            blocked_accounts.add(assignment.previous_account_id)

        # Filter out blocked accounts
        available = [a for a in accounts if a.id not in blocked_accounts]

        if not available:
            logger.warning(
                "All available accounts already tried",
                assignment_id=str(assignment.id),
            )
            return None

        # Pick account with least load
        best_account = min(available, key=lambda a: account_loads.get(a.id, 0))

        # Perform swap
        assignment.swap_account(best_account.id)
        await self.assignment_repo.save(assignment)

        logger.info(
            "Account swapped",
            assignment_id=str(assignment.id),
            old_account_id=str(assignment.previous_account_id),
            new_account_id=str(best_account.id),
            swap_count=assignment.swap_count,
        )

        # Auto-copy channel profile to new account
        await self._copy_channel_profile_to_account(
            account=best_account,
            channel_id=assignment.channel_id,
            campaign_id=assignment.campaign_id,
        )

        return assignment

    async def _copy_channel_profile_to_account(
        self,
        account: Account,
        channel_id: UUID,
        campaign_id: Optional[UUID] = None,
    ) -> bool:
        """
        Copy channel profile (name, photo) to account and send initial message.

        Called automatically after swap or initial assignment.

        Args:
            account: Account to update profile for
            channel_id: Channel to copy profile from
            campaign_id: Campaign ID to get initial message from

        Returns:
            True if profile copied successfully
        """
        if not account.session_data:
            logger.warning(
                "Cannot copy profile - no session data",
                account_id=str(account.id),
            )
            return False

        # Get channel
        channel = await self.channel_repo.get_by_id(channel_id)
        if not channel:
            logger.warning(
                "Cannot copy profile - channel not found",
                channel_id=str(channel_id),
            )
            return False

        channel_link = channel.username or channel.link
        if not channel_link:
            logger.warning(
                "Cannot copy profile - no channel link",
                channel_id=str(channel_id),
            )
            return False

        # Get initial message from campaign
        initial_message = None
        if campaign_id and self.campaign_repo:
            campaign = await self.campaign_repo.get_by_id(campaign_id)
            if campaign and campaign.initial_message:
                initial_message = campaign.initial_message

        try:
            client = CommentBotClient(
                account_id=str(account.id),
                session_data=account.session_data,
            )

            async with client:
                result = await client.copy_channel_profile(
                    channel=channel_link,
                    copy_name=True,
                    copy_photo=True,
                    copy_about=False,
                )

                if result.get("success"):
                    logger.info(
                        "Profile copied after swap",
                        account_id=str(account.id),
                        channel_id=str(channel_id),
                        channel_title=result.get("channel_title"),
                        name_copied=result.get("name_copied"),
                        photo_copied=result.get("photo_copied"),
                    )

                    # Send initial message after profile copy
                    if initial_message:
                        await self._send_initial_message(
                            client=client,
                            channel=channel_link,
                            message=initial_message,
                        )

                    return True
                else:
                    logger.warning(
                        "Profile copy failed after swap",
                        account_id=str(account.id),
                        channel_id=str(channel_id),
                        error=result.get("error"),
                    )
                    return False

        except Exception as e:
            logger.error(
                "Error copying profile after swap",
                account_id=str(account.id),
                channel_id=str(channel_id),
                error=str(e),
            )
            return False

    async def _send_initial_message(
        self,
        client: CommentBotClient,
        channel: str,
        message: str,
    ) -> bool:
        """
        Send initial message to channel's latest post.

        Args:
            client: Connected Telegram client
            channel: Channel username or link
            message: Message to send

        Returns:
            True if message sent successfully
        """
        try:
            # Get latest posts from channel
            posts = await client.get_channel_posts(channel, limit=1)

            if not posts:
                logger.warning(
                    "No posts found for initial message",
                    channel=channel,
                )
                return False

            latest_post = posts[0]
            post_id = latest_post["id"]

            # Post comment under latest post
            comment_id = await client.post_comment(
                channel=channel,
                post_id=post_id,
                text=message,
            )

            if comment_id:
                logger.info(
                    "Initial message sent",
                    channel=channel,
                    post_id=post_id,
                    comment_id=comment_id,
                )
                return True

            return False

        except Exception as e:
            logger.error(
                "Failed to send initial message",
                channel=channel,
                error=str(e),
            )
            return False

    async def perform_cross_swap(
        self,
        campaign_id: UUID,
        owner_id: int,
    ) -> dict:
        """
        Perform cross-swap between accounts.

        When account A is blocked on channel X, and account B is blocked on channel Y,
        swap them: A -> Y, B -> X.

        This can resolve temporary blocks or access issues.

        Args:
            campaign_id: Campaign ID
            owner_id: Owner user ID

        Returns:
            Dict with swap stats
        """
        # Get assignments needing swap
        needing_swap = await self.assignment_repo.list_needing_swap(campaign_id)

        if len(needing_swap) < 2:
            return {"swaps": 0, "message": "Not enough blocked assignments for cross-swap"}

        # Get accounts for profile copying
        accounts = await self.account_repo.list_available_for_work(owner_id)
        account_map = {a.id: a for a in accounts}

        swaps_done = 0

        # Group by account
        by_account: dict[UUID, list[ChannelAssignment]] = {}
        for assignment in needing_swap:
            if assignment.account_id not in by_account:
                by_account[assignment.account_id] = []
            by_account[assignment.account_id].append(assignment)

        # Find pairs to swap
        account_ids = list(by_account.keys())

        for i in range(len(account_ids)):
            for j in range(i + 1, len(account_ids)):
                acc_a = account_ids[i]
                acc_b = account_ids[j]

                assignments_a = by_account[acc_a]
                assignments_b = by_account[acc_b]

                if not assignments_a or not assignments_b:
                    continue

                # Take one assignment from each and swap
                assign_a = assignments_a.pop()
                assign_b = assignments_b.pop()

                # Swap: A gets B's channel, B gets A's channel
                old_account_a = assign_a.account_id
                old_account_b = assign_b.account_id

                assign_a.swap_account(acc_b)
                assign_b.swap_account(acc_a)

                await self.assignment_repo.save(assign_a)
                await self.assignment_repo.save(assign_b)

                swaps_done += 1

                logger.info(
                    "Cross-swap performed",
                    channel_a=str(assign_a.channel_id),
                    channel_b=str(assign_b.channel_id),
                    account_a=str(acc_a),
                    account_b=str(acc_b),
                )

                # Copy profiles to new accounts after cross-swap
                account_a = account_map.get(acc_a)
                account_b = account_map.get(acc_b)

                if account_b:
                    await self._copy_channel_profile_to_account(
                        account=account_b,
                        channel_id=assign_a.channel_id,
                        campaign_id=campaign_id,
                    )
                if account_a:
                    await self._copy_channel_profile_to_account(
                        account=account_a,
                        channel_id=assign_b.channel_id,
                        campaign_id=campaign_id,
                    )

        return {
            "swaps": swaps_done,
            "blocked_assignments": len(needing_swap),
        }

    async def rebalance_load(
        self,
        campaign_id: UUID,
        owner_id: int,
    ) -> dict:
        """
        Rebalance assignments across accounts for even load.

        Moves channels from overloaded accounts to underloaded ones.

        Args:
            campaign_id: Campaign ID
            owner_id: Owner user ID

        Returns:
            Dict with rebalance stats
        """
        accounts = await self.account_repo.list_available_for_work(owner_id)
        if len(accounts) < 2:
            return {"moved": 0, "message": "Not enough accounts"}

        # Create account map for profile copying
        account_map = {a.id: a for a in accounts}

        # Get current loads
        loads = {}
        assignments_by_account = {}

        for account in accounts:
            account_assignments = await self.assignment_repo.list_by_account(account.id)
            loads[account.id] = len(account_assignments)
            assignments_by_account[account.id] = account_assignments

        # Calculate target load (evenly distributed)
        total_assignments = sum(loads.values())
        target_load = total_assignments // len(accounts)
        remainder = total_assignments % len(accounts)

        moved = 0

        # Find overloaded and underloaded accounts
        overloaded = [
            (acc_id, load)
            for acc_id, load in loads.items()
            if load > target_load + 1
        ]
        underloaded = [
            (acc_id, load)
            for acc_id, load in loads.items()
            if load < target_load
        ]

        for over_id, over_load in overloaded:
            excess = over_load - target_load - (1 if remainder > 0 else 0)
            assignments_to_move = assignments_by_account[over_id][:excess]

            for assignment in assignments_to_move:
                # Find underloaded account
                for under_id, under_load in underloaded:
                    if under_load < target_load:
                        # Move assignment
                        assignment.swap_account(under_id)
                        await self.assignment_repo.save(assignment)

                        loads[over_id] -= 1
                        loads[under_id] += 1
                        moved += 1

                        logger.debug(
                            "Assignment moved for balance",
                            assignment_id=str(assignment.id),
                            from_account=str(over_id),
                            to_account=str(under_id),
                        )

                        # Copy profile to new account
                        new_account = account_map.get(under_id)
                        if new_account:
                            await self._copy_channel_profile_to_account(
                                account=new_account,
                                channel_id=assignment.channel_id,
                                campaign_id=campaign_id,
                            )

                        # Update underloaded list
                        underloaded = [
                            (acc_id, loads[acc_id])
                            for acc_id, _ in underloaded
                            if loads[acc_id] < target_load
                        ]
                        break

        return {
            "moved": moved,
            "accounts": len(accounts),
            "target_load": target_load,
        }

    async def get_distribution_stats(
        self,
        campaign_id: UUID,
        owner_id: int,
    ) -> dict:
        """
        Get statistics about channel distribution.

        Args:
            campaign_id: Campaign ID
            owner_id: Owner user ID

        Returns:
            Dict with distribution stats
        """
        accounts = await self.account_repo.list_active(owner_id)
        channels = await self.channel_repo.list_by_campaign(campaign_id)
        assignments = await self.assignment_repo.list_by_campaign(campaign_id)

        # Count by status
        active_assignments = [a for a in assignments if a.status == AssignmentStatus.ACTIVE]
        blocked_assignments = [a for a in assignments if a.status == AssignmentStatus.BLOCKED]

        # Count by account
        per_account = {}
        for account in accounts:
            per_account[str(account.id)[:8]] = {
                "phone": account.phone[:4] + "****" if account.phone else "N/A",
                "assigned": sum(1 for a in active_assignments if a.account_id == account.id),
                "blocked": sum(1 for a in blocked_assignments if a.account_id == account.id),
            }

        return {
            "total_accounts": len(accounts),
            "total_channels": len(channels),
            "assigned": len(active_assignments),
            "blocked": len(blocked_assignments),
            "unassigned": len(channels) - len(assignments),
            "per_account": per_account,
        }
