"""
Base entity classes for the domain layer.

All domain entities inherit from these base classes to ensure
consistent behavior and identification.
"""

from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass
class Entity(ABC):
    """
    Base class for all domain entities.
    
    Provides:
    - Unique identifier (UUID)
    - Creation timestamp
    - Update timestamp
    - Equality based on ID
    """
    
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Entity):
            return False
        return self.id == other.id
    
    def __hash__(self) -> int:
        return hash(self.id)
    
    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow()


@dataclass
class AggregateRoot(Entity):
    """
    Base class for aggregate roots.
    
    Aggregate roots are the main entry points for domain operations.
    They ensure consistency within their boundaries.
    """
    
    version: int = field(default=0)
    
    def increment_version(self) -> None:
        """Mark aggregate as changed.

        The optimistic-lock `version` is managed by the persistence layer
        (repositories) on successful save. Domain methods should not
        advance the version in-memory, otherwise the repository version
        check becomes inconsistent.
        """
        self.touch()
