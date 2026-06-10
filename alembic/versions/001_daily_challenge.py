"""add daily challenge tables and profile columns

Revision ID: 001_daily_challenge
Revises: 
Create Date: 2025-06-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_daily_challenge"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- 1. Add 4 columns to profiles --
    op.add_column("profiles", sa.Column(
        "daily_streak", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("profiles", sa.Column(
        "best_daily_streak", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("profiles", sa.Column(
        "last_daily_completion_date", sa.Date(), nullable=True
    ))
    op.add_column("profiles", sa.Column(
        "perfect_daily_count", sa.Integer(), nullable=False, server_default="0"
    ))

    # -- 2. Create daily_results table --
    op.create_table(
        "daily_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("correct_count", sa.Integer(), nullable=False),
        sa.Column("total_time_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # -- 3. Indexes --
    op.create_index("ix_daily_results_user_id", "daily_results", ["user_id"])
    op.create_index("ix_daily_results_date", "daily_results", ["date"])

    # -- 4. Unique constraint: one result per user per day --
    op.create_unique_constraint(
        "uq_daily_results_user_date",
        "daily_results",
        ["user_id", "date"],
    )


def downgrade() -> None:
    op.drop_table("daily_results")

    op.drop_column("profiles", "perfect_daily_count")
    op.drop_column("profiles", "last_daily_completion_date")
    op.drop_column("profiles", "best_daily_streak")
    op.drop_column("profiles", "daily_streak")