"""
Base repository implementation.

Provides common CRUD operations for all repositories
with optimistic locking support.
"""

from typing import Generic, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

import structlog

from src.domain.exceptions import DomainException

logger = structlog.get_logger(__name__)

ModelT = TypeVar("ModelT", bound=DeclarativeBase)
EntityT = TypeVar("EntityT")


class OptimisticLockError(DomainException):
    """Raised when optimistic lock check fails."""
    
    def __init__(self, entity_type: str, entity_id: str):
        super().__init__(
            f"Optimistic lock failed for {entity_type} {entity_id}. "
            "The entity was modified by another transaction.",
            code="OPTIMISTIC_LOCK_ERROR"
        )


class BaseRepository(Generic[ModelT, EntityT]):
    """
    Base repository with common CRUD operations.
    
    Implements:
    - Basic CRUD operations
    - Optimistic locking for concurrent updates
    - Pagination support
    """
    
    model_class: Type[ModelT]
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    def _to_entity(self, model: ModelT) -> EntityT:
        """Convert model to domain entity. Override in subclass."""
        raise NotImplementedError
    
    def _to_model(
        self,
        entity: EntityT,
        model: Optional[ModelT] = None,
    ) -> ModelT:
        """Convert domain entity to model. Override in subclass."""
        raise NotImplementedError
    
    async def get_by_id(self, entity_id: UUID) -> Optional[EntityT]:
        """
        Get entity by ID.
        
        Args:
            entity_id: Entity UUID
            
        Returns:
            Entity if found, None otherwise
        """
        stmt = select(self.model_class).where(
            self.model_class.id == entity_id
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def get_by_id_for_update(
        self,
        entity_id: UUID,
        nowait: bool = False,
    ) -> Optional[EntityT]:
        """
        Get entity by ID with row-level lock.
        
        Uses SELECT ... FOR UPDATE for pessimistic locking.
        
        Args:
            entity_id: Entity UUID
            nowait: If True, fail immediately if lock unavailable
            
        Returns:
            Entity if found, None otherwise
        """
        stmt = select(self.model_class).where(
            self.model_class.id == entity_id
        ).with_for_update(nowait=nowait)
        
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return None
        
        return self._to_entity(model)
    
    async def save(
        self,
        entity: EntityT,
        check_version: bool = True,
    ) -> EntityT:
        """
        Save entity (create or update).
        
        Implements optimistic locking by checking version field.
        
        Args:
            entity: Entity to save
            check_version: Whether to check version for optimistic locking
            
        Returns:
            Saved entity
            
        Raises:
            OptimisticLockError: If version check fails
        """
        # Check if entity exists
        stmt = select(self.model_class).where(
            self.model_class.id == entity.id
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing is not None:
            # Update existing
            if check_version and hasattr(entity, 'version'):
                if existing.version != entity.version:
                    raise OptimisticLockError(
                        entity_type=self.model_class.__name__,
                        entity_id=str(entity.id),
                    )
                # Increment version
                entity.version += 1
            
            model = self._to_model(entity, existing)
        else:
            # Create new
            if hasattr(entity, 'version'):
                entity.version = 0
            model = self._to_model(entity)
            self.session.add(model)
        
        await self.session.flush()
        
        # Refresh to get any DB-generated values
        await self.session.refresh(model)
        
        return self._to_entity(model)
    
    async def save_many(
        self,
        entities: list[EntityT],
        check_version: bool = True,
    ) -> list[EntityT]:
        """
        Save multiple entities.
        
        Args:
            entities: List of entities to save
            check_version: Whether to check version for optimistic locking
            
        Returns:
            List of saved entities
        """
        saved = []
        for entity in entities:
            saved.append(await self.save(entity, check_version))
        return saved
    
    async def delete(self, entity_id: UUID) -> bool:
        """
        Delete entity by ID.
        
        Args:
            entity_id: Entity UUID
            
        Returns:
            True if deleted, False if not found
        """
        stmt = select(self.model_class).where(
            self.model_class.id == entity_id
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        
        if model is None:
            return False
        
        await self.session.delete(model)
        await self.session.flush()
        
        return True
    
    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EntityT]:
        """
        List all entities with pagination.
        
        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            
        Returns:
            List of entities
        """
        stmt = (
            select(self.model_class)
            .order_by(self.model_class.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        
        result = await self.session.execute(stmt)
        models = result.scalars().all()
        
        return [self._to_entity(m) for m in models]
    
    async def count(self) -> int:
        """
        Count total entities.
        
        Returns:
            Total count
        """
        from sqlalchemy import func
        
        stmt = select(func.count()).select_from(self.model_class)
        result = await self.session.execute(stmt)
        
        return result.scalar_one()
    
    async def exists(self, entity_id: UUID) -> bool:
        """
        Check if entity exists.
        
        Args:
            entity_id: Entity UUID
            
        Returns:
            True if exists
        """
        from sqlalchemy import exists as sql_exists
        
        stmt = select(
            sql_exists().where(self.model_class.id == entity_id)
        )
        result = await self.session.execute(stmt)
        
        return result.scalar_one()
