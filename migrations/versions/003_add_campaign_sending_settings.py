"""Add campaign sending settings.

Adds fields for batch-based first message sending:
- sending_interval_hours: How often to send batches
- sending_messages_per_batch: Messages per batch
- sending_delay_min/max: Delay range between messages
- sending_last_batch_at: Last batch timestamp
- sending_targets_file_path: Source targets file path
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in cols


def upgrade() -> None:
    # Add sending settings columns to campaigns table
    if not _has_column("campaigns", "sending_interval_hours"):
        op.add_column(
            "campaigns",
            sa.Column("sending_interval_hours", sa.Float(), nullable=False, server_default="13.0"),
        )

    if not _has_column("campaigns", "sending_messages_per_batch"):
        op.add_column(
            "campaigns",
            sa.Column("sending_messages_per_batch", sa.Integer(), nullable=False, server_default="10"),
        )

    if not _has_column("campaigns", "sending_delay_min"):
        op.add_column(
            "campaigns",
            sa.Column("sending_delay_min", sa.Integer(), nullable=False, server_default="17"),
        )

    if not _has_column("campaigns", "sending_delay_max"):
        op.add_column(
            "campaigns",
            sa.Column("sending_delay_max", sa.Integer(), nullable=False, server_default="23"),
        )

    if not _has_column("campaigns", "sending_last_batch_at"):
        op.add_column(
            "campaigns",
            sa.Column("sending_last_batch_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _has_column("campaigns", "sending_targets_file_path"):
        op.add_column(
            "campaigns",
            sa.Column("sending_targets_file_path", sa.String(1024), nullable=True),
        )


def downgrade() -> None:
    # Drop columns in reverse order
    for col in [
        "sending_targets_file_path",
        "sending_last_batch_at",
        "sending_delay_max",
        "sending_delay_min",
        "sending_messages_per_batch",
        "sending_interval_hours",
    ]:
        if _has_column("campaigns", col):
            op.drop_column("campaigns", col)
