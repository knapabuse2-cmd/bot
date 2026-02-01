"""Add dialogue tracking fields.

This migration originally existed to add `interest_score` and `link_sent_count`.
In the cleaned baseline (`001_initial`) these columns already exist.

To keep upgrade paths safe for existing installations, this migration is now
idempotent: it only adds the columns if they are missing.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table_name)]
    return column_name in cols


def upgrade() -> None:
    # Add interest_score and link_sent_count only if missing.
    if not _has_column("dialogues", "interest_score"):
        op.add_column(
            "dialogues",
            sa.Column("interest_score", sa.Integer(), nullable=False, server_default="0"),
        )
    if not _has_column("dialogues", "link_sent_count"):
        op.add_column(
            "dialogues",
            sa.Column("link_sent_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    # Drop only if they exist.
    if _has_column("dialogues", "link_sent_count"):
        op.drop_column("dialogues", "link_sent_count")
    if _has_column("dialogues", "interest_score"):
        op.drop_column("dialogues", "interest_score")
