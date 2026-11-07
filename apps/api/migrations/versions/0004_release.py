"""Add identity, memberships and release control/diagnostic records; preserve existing data."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"


def pk(name="id"):
    return sa.Column(name, sa.String(), primary_key=True)


def workspace(primary=False):
    return sa.Column(
        "workspace_id",
        sa.String(),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=primary,
        nullable=False,
        index=not primary,
    )


def upgrade():
    op.create_table(
        "users",
        pk(),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("admin", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "memberships",
        workspace(True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.CheckConstraint("role IN ('owner','editor','viewer')", name="valid_membership_role"),
    )
    op.create_table(
        "auth_sessions",
        pk("token_hash"),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("expires_at", sa.Integer(), nullable=False),
    )
    op.create_table("model_registry", pk(), sa.Column("configuration", sa.JSON(), nullable=False))
    op.create_table("route_policies", workspace(True), sa.Column("configuration", sa.JSON(), nullable=False))
    op.create_table(
        "usage_events",
        pk(),
        workspace(),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("token_source", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "request_events",
        pk(),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("workspace_id", sa.String(), nullable=True, index=True),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "feedback",
        pk(),
        workspace(),
        sa.Column(
            "message_id",
            sa.String(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("rating", sa.String(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )


def downgrade():
    raise RuntimeError("Release schema downgrade is unsupported. Restore a stopped, verified full backup.")
