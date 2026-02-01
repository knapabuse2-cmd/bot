"""Dialogue repository implementation.

Historically this repo only persisted dialogue *headers* and had an auxiliary
`add_message` method. The application layer (DialogueService) however appends
messages directly to the Dialogue entity and then calls `save()`.

To make this consistent (and to make dialogues usable in the API/admin), this
implementation synchronizes message rows on every save.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from src.application.interfaces.repository import DialogueRepository
from src.domain.entities import Dialogue, DialogueStatus, Message
from src.infrastructure.database.mappers import (
    dialogue_entity_to_model,
    dialogue_model_to_entity,
    message_entity_to_model,
    message_model_to_entity,
)
from src.infrastructure.database.models import DialogueModel, MessageModel

from .base import BaseRepository


class PostgresDialogueRepository(BaseRepository[DialogueModel, Dialogue], DialogueRepository):
    """PostgreSQL implementation of DialogueRepository."""

    model_class = DialogueModel

    def _to_entity(self, model: DialogueModel) -> Dialogue:
        return dialogue_model_to_entity(model)

    def _to_model(self, entity: Dialogue, model: Optional[DialogueModel] = None) -> DialogueModel:
        return dialogue_entity_to_model(entity, model)

    async def get_by_id(self, entity_id: UUID) -> Optional[Dialogue]:
        stmt = (
            select(DialogueModel)
            .options(selectinload(DialogueModel.messages))
            .where(DialogueModel.id == entity_id)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_account_and_user(
        self,
        account_id: UUID,
        telegram_user_id: int,
        telegram_username: Optional[str] = None,
    ) -> Optional[Dialogue]:
        """Get active-ish dialogue for an account and a user.

        Matches by telegram_user_id and/or telegram_username.
        """

        filters = [
            DialogueModel.account_id == account_id,
            DialogueModel.status.notin_([DialogueStatus.COMPLETED.value, DialogueStatus.FAILED.value]),
        ]

        user_filters = [DialogueModel.telegram_user_id == telegram_user_id]
        if telegram_username:
            user_filters.append(DialogueModel.telegram_username == telegram_username)

        stmt = (
            select(DialogueModel)
            .options(selectinload(DialogueModel.messages))
            .where(and_(*filters, or_(*user_filters)))
            .order_by(DialogueModel.updated_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_target(self, target_id: UUID) -> Optional[Dialogue]:
        stmt = (
            select(DialogueModel)
            .options(selectinload(DialogueModel.messages))
            .where(DialogueModel.target_user_id == target_id)
            .order_by(DialogueModel.updated_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_account(
        self,
        account_id: UUID,
        status: Optional[DialogueStatus] = None,
        limit: int = 100,
    ) -> list[Dialogue]:
        stmt = select(DialogueModel).where(DialogueModel.account_id == account_id)
        if status:
            stmt = stmt.where(DialogueModel.status == status.value)
        stmt = stmt.order_by(DialogueModel.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_by_campaign(
        self,
        campaign_id: UUID,
        status: Optional[DialogueStatus] = None,
        limit: int = 100,
    ) -> list[Dialogue]:
        stmt = select(DialogueModel).where(DialogueModel.campaign_id == campaign_id)
        if status:
            stmt = stmt.where(DialogueModel.status == status.value)
        stmt = stmt.order_by(DialogueModel.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def list_pending_actions(
        self,
        account_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> list[Dialogue]:
        now = datetime.utcnow()
        stmt = select(DialogueModel).where(
            and_(
                DialogueModel.next_action_at.isnot(None),
                DialogueModel.next_action_at <= now,
                DialogueModel.status.in_(
                    [
                        DialogueStatus.INITIATED.value,
                        DialogueStatus.ACTIVE.value,
                        DialogueStatus.GOAL_REACHED.value,
                    ]
                ),
            )
        )
        if account_id:
            stmt = stmt.where(DialogueModel.account_id == account_id)

        stmt = stmt.order_by(DialogueModel.next_action_at.asc()).limit(limit)
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        return [self._to_entity(m) for m in models]

    async def add_message(self, dialogue_id: UUID, message: Message) -> Dialogue:
        """Persist a new message and return the refreshed dialogue."""
        # Upsert message row
        existing = await self.session.get(MessageModel, message.id)
        if existing is None:
            model = message_entity_to_model(message, dialogue_id)
            self.session.add(model)
        else:
            existing.role = message.role.value
            existing.content = message.content
            existing.timestamp = message.timestamp
            existing.telegram_message_id = message.telegram_message_id
            existing.ai_generated = message.ai_generated
            existing.tokens_used = message.tokens_used
            existing.is_follow_up = message.is_follow_up

        await self.session.flush()
        dialogue = await self.get_by_id(dialogue_id)
        if dialogue is None:
            raise ValueError("Dialogue not found")
        return dialogue

    async def count_active_by_account(self, account_id: UUID) -> int:
        stmt = select(func.count(DialogueModel.id)).where(
            and_(
                DialogueModel.account_id == account_id,
                DialogueModel.status.in_([
                    DialogueStatus.INITIATED.value,
                    DialogueStatus.ACTIVE.value,
                    DialogueStatus.GOAL_REACHED.value,
                ]),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    # ------------------------------------------------------------------
    # Message synchronization
    # ------------------------------------------------------------------

    async def save(self, entity: Dialogue, check_version: bool = False) -> Dialogue:
        """Save dialogue and synchronize messages.

        Note: check_version is disabled by default for dialogues because
        concurrent access is managed via application-level locks in AccountWorker.
        """
        await super().save(entity, check_version=check_version)
        await self._sync_messages(entity)
        # Return a fully loaded dialogue
        refreshed = await self.get_by_id(entity.id)
        return refreshed or entity


    async def update_status(
        self,
        dialogue_id: UUID,
        status: DialogueStatus,
        fail_reason: Optional[str] = None,
    ) -> None:
        # Atomic status update for backward compatibility.
        values: dict[str, object] = {
            "status": status.value,
            "updated_at": datetime.utcnow(),
        }
        if fail_reason:
            values["fail_reason"] = fail_reason
        # Once finished, no further actions should be scheduled.
        if status in (DialogueStatus.COMPLETED, DialogueStatus.FAILED):
            values["next_action_at"] = None

        await self.session.execute(
            update(DialogueModel).where(DialogueModel.id == dialogue_id).values(**values)
        )

    async def _sync_messages(self, entity: Dialogue) -> None:
        """Upsert all messages from the entity into the messages table."""
        if not getattr(entity, "messages", None):
            return

        stmt = select(MessageModel).where(MessageModel.dialogue_id == entity.id)
        result = await self.session.execute(stmt)
        existing_models = {m.id: m for m in result.scalars().all()}

        for msg in entity.messages:
            existing = existing_models.get(msg.id)
            if existing is None:
                self.session.add(message_entity_to_model(msg, entity.id))
            else:
                # Only update mutable fields; keep as upsert to support telegram_message_id updates
                existing.role = msg.role.value
                existing.content = msg.content
                existing.timestamp = msg.timestamp
                existing.telegram_message_id = msg.telegram_message_id
                existing.ai_generated = msg.ai_generated
                existing.tokens_used = msg.tokens_used
                existing.is_follow_up = msg.is_follow_up

        await self.session.flush()
