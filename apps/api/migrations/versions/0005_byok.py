"""Private provider configurations, encrypted credentials, selection and usage."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.create_table(
        "provider_configurations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("connection", sa.JSON(), nullable=False),
        sa.Column("revision", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_provider_configurations_owner", "provider_configurations", ["owner"])
    op.create_table(
        "provider_selections",
        sa.Column("owner", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "configuration_id",
            sa.String(),
            sa.ForeignKey("provider_configurations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_table(
        "provider_usage",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column(
            "configuration_id",
            sa.String(),
            sa.ForeignKey("provider_configurations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("cost_source", sa.String(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_provider_usage_owner", "provider_usage", ["owner"])
    op.create_index("ix_provider_usage_configuration_id", "provider_usage", ["configuration_id"])


def downgrade():
    op.drop_table("provider_usage")
    op.drop_table("provider_selections")
    op.drop_table("provider_configurations")
