"""Comment bot domain entities."""

from src.commentbot.domain.entities.account import Account, AccountStatus
from src.commentbot.domain.entities.comment_task import CommentTask, TaskStatus
from src.commentbot.domain.entities.campaign import Campaign, CampaignStatus
from src.commentbot.domain.entities.channel import Channel, ChannelStatus
from src.commentbot.domain.entities.channel_assignment import ChannelAssignment, AssignmentStatus

__all__ = [
    "Account",
    "AccountStatus",
    "CommentTask",
    "TaskStatus",
    "Campaign",
    "CampaignStatus",
    "Channel",
    "ChannelStatus",
    "ChannelAssignment",
    "AssignmentStatus",
]
