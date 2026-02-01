"""add warmup tables

Revision ID: 007
Revises: 006
Create Date: 2026-01-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, None] = '006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""

    # 1. Create interest_categories table
    op.create_table(
        'interest_categories',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('keywords', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # 2. Create warmup_channels table
    op.create_table(
        'warmup_channels',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('username', sa.String(255), nullable=False),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('category_id', sa.String(36), nullable=True),
        sa.Column('language', sa.String(10), nullable=False, server_default='en'),
        sa.Column('subscriber_count', sa.Integer(), nullable=True),
        sa.Column('last_post_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['interest_categories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username')
    )

    # 3. Create warmup_groups table
    op.create_table(
        'warmup_groups',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('username', sa.String(255), nullable=False),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('category_id', sa.String(36), nullable=True),
        sa.Column('language', sa.String(10), nullable=False, server_default='en'),
        sa.Column('can_write', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('member_count', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['interest_categories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username')
    )

    # 4. Create warmup_profiles table
    op.create_table(
        'warmup_profiles',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('total_days', sa.Integer(), nullable=False, server_default='21'),
        sa.Column('stages', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('min_session_duration_minutes', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('max_session_duration_minutes', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('typing_speed_cpm', sa.Integer(), nullable=False, server_default='150'),
        sa.Column('reaction_probability', sa.Float(), nullable=False, server_default='0.3'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # 5. Create proxy_groups table
    op.create_table(
        'proxy_groups',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('country_code', sa.String(10), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # 6. Create account_groups table
    op.create_table(
        'account_groups',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('default_warmup_profile_id', sa.String(36), nullable=True),
        sa.Column('default_proxy_group_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['default_warmup_profile_id'], ['warmup_profiles.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['default_proxy_group_id'], ['proxy_groups.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # 7. Create account_warmups table
    op.create_table(
        'account_warmups',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('profile_id', sa.String(36), nullable=True),
        sa.Column('stage', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stage_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('channels_joined', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('groups_joined', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reactions_sent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('messages_sent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_session_minutes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('daily_reactions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('daily_messages', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('daily_joins', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_daily_reset', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_daily_message_limit', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('flood_wait_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['profile_id'], ['warmup_profiles.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id')
    )

    # 8. Create account_personas table
    op.create_table(
        'account_personas',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('interests', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('activity_pattern', sa.String(50), nullable=False, server_default='office_hours'),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='UTC'),
        sa.Column('language', sa.String(10), nullable=False, server_default='en'),
        sa.Column('typing_speed', sa.Integer(), nullable=False, server_default='150'),
        sa.Column('reaction_probability', sa.Float(), nullable=False, server_default='0.3'),
        sa.Column('min_response_delay', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('max_response_delay', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('active_hours', sa.JSON(), nullable=False, server_default='{"start": 9, "end": 22}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id')
    )

    # 9. Create account_subscriptions table
    op.create_table(
        'account_subscriptions',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('warmup_id', sa.String(36), nullable=False),
        sa.Column('channel_id', sa.String(36), nullable=True),
        sa.Column('group_id', sa.String(36), nullable=True),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('left_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['channel_id'], ['warmup_channels.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['warmup_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['warmup_id'], ['account_warmups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('warmup_id', 'channel_id', name='uq_account_channel_subscription'),
        sa.UniqueConstraint('warmup_id', 'group_id', name='uq_account_group_subscription')
    )

    # 10. Create warmup_activity_logs table
    op.create_table(
        'warmup_activity_logs',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('activity_type', sa.String(50), nullable=False),
        sa.Column('target', sa.String(255), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # 11. Create account_group_memberships table
    op.create_table(
        'account_group_memberships',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('group_id', sa.String(36), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['account_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'group_id', name='uq_account_group_membership')
    )

    # 12. Create proxy_group_memberships table
    op.create_table(
        'proxy_group_memberships',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('proxy_id', sa.String(36), nullable=False),
        sa.Column('group_id', sa.String(36), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['proxy_id'], ['proxies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['proxy_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('proxy_id', 'group_id', name='uq_proxy_group_membership')
    )

    # Add group_id column to accounts table
    op.add_column('accounts', sa.Column('group_id', sa.String(36), nullable=True))
    op.create_foreign_key(
        'fk_accounts_group_id',
        'accounts', 'account_groups',
        ['group_id'], ['id'],
        ondelete='SET NULL'
    )

    # Create indexes
    op.create_index('ix_warmup_activity_logs_account_id', 'warmup_activity_logs', ['account_id'])
    op.create_index('ix_warmup_activity_logs_created_at', 'warmup_activity_logs', ['created_at'])


def downgrade() -> None:
    """Downgrade database schema."""
    # Drop indexes
    op.drop_index('ix_warmup_activity_logs_created_at', 'warmup_activity_logs')
    op.drop_index('ix_warmup_activity_logs_account_id', 'warmup_activity_logs')

    # Drop group_id from accounts
    op.drop_constraint('fk_accounts_group_id', 'accounts', type_='foreignkey')
    op.drop_column('accounts', 'group_id')

    # Drop tables in reverse order (respect foreign keys)
    op.drop_table('proxy_group_memberships')
    op.drop_table('account_group_memberships')
    op.drop_table('warmup_activity_logs')
    op.drop_table('account_subscriptions')
    op.drop_table('account_personas')
    op.drop_table('account_warmups')
    op.drop_table('account_groups')
    op.drop_table('proxy_groups')
    op.drop_table('warmup_profiles')
    op.drop_table('warmup_groups')
    op.drop_table('warmup_channels')
    op.drop_table('interest_categories')
