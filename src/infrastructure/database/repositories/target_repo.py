"""Backward compatible import wrapper.

Earlier versions of the project used `target_repo.py` as the canonical
implementation for target users.

The current code uses `user_target_repo.py`.
To avoid import-time crashes for older imports, this file simply re-exports
the same repository class.
"""

from .user_target_repo import PostgresUserTargetRepository

__all__ = ["PostgresUserTargetRepository"]
