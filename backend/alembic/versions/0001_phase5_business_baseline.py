"""Create the Phase 5 content project baseline.

Revision ID: 0001_phase5_baseline
Revises:
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_phase5_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("topic_direction", sa.Text(), nullable=False),
        sa.Column("selected_topic_title", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("revision_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_projects_status",
        "content_projects",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_content_projects_thread_id",
        "content_projects",
        ["thread_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_content_projects_thread_id", table_name="content_projects")
    op.drop_index("ix_content_projects_status", table_name="content_projects")
    op.drop_table("content_projects")
