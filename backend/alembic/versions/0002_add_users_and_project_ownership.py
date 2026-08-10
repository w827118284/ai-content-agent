"""Add users and content project ownership.

Revision ID: 0002_add_auth_ownership
Revises: 0001_phase5_baseline
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_add_auth_ownership"
down_revision: str | None = "0001_phase5_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.add_column(
        "content_projects",
        sa.Column("user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_content_projects_user_id_users",
        "content_projects",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_index(
        "ix_content_projects_user_id",
        "content_projects",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_content_projects_user_id", table_name="content_projects")
    op.drop_constraint(
        "fk_content_projects_user_id_users",
        "content_projects",
        type_="foreignkey",
    )
    op.drop_column("content_projects", "user_id")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
