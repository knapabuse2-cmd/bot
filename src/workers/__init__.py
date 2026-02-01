"""Workers module.

Important: keep this module lightweight.

This package is imported by the API layer (e.g. to expose worker manager
stats). Importing heavy Telegram/Redis dependencies at import-time can break
API startup and unit tests.

Therefore, we only import the always-available pieces eagerly and wrap
optional imports in try/except.
"""

from __future__ import annotations

from .manager import WorkerManager, get_worker_manager, shutdown_manager
from .scheduler import Scheduler, ScheduledTask

# Optional worker implementations
try:
    from .account_worker import AccountWorker  # noqa: F401
except Exception:  # pragma: no cover
    AccountWorker = None  # type: ignore

try:
    from .natural_worker import NaturalAccountWorker  # noqa: F401
except Exception:  # pragma: no cover
    NaturalAccountWorker = None  # type: ignore

__all__ = [
    "AccountWorker",
    "NaturalAccountWorker",
    "WorkerManager",
    "get_worker_manager",
    "shutdown_manager",
    "Scheduler",
    "ScheduledTask",
]
