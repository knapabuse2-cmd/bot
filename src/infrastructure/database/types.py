"""Custom SQLAlchemy types.

This project primarily targets PostgreSQL, but we also want the ORM models
(and especially the unit/integration tests) to work on SQLite.

The main incompatibility is UUID handling.

`GUID` stores UUIDs as native UUID on PostgreSQL and as 36-char strings on
SQLite/other dialects.
"""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):
    """Platform-independent GUID type.

    Stores UUIDs as CHAR(36) strings on all databases for consistency
    with existing migrations that use String(36).

    Returns/accepts Python ``uuid.UUID``.
    """

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        # Always use CHAR(36) for consistency with migrations
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None

        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))

        return str(value)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None

        if isinstance(value, uuid.UUID):
            return value

        return uuid.UUID(str(value))
