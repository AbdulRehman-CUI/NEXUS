"""Private guest sessions and PostgreSQL document storage."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade():
    op.create_table(
        "guest_sessions",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_guest_sessions_expires_at", "guest_sessions", ["expires_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.create_table(
            "stored_files",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("content", sa.LargeBinary(), nullable=False),
        )
        op.create_table(
            "stored_vectors",
            sa.Column("namespace", sa.String(), primary_key=True),
            sa.Column("chunk_id", sa.String(), primary_key=True),
            sa.Column(
                "workspace_id",
                sa.String(),
                sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("embedding", sa.JSON(), nullable=False),
        )
        op.create_index("ix_stored_vectors_workspace_id", "stored_vectors", ["workspace_id"])
        op.create_index("ix_stored_vectors_document_id", "stored_vectors", ["document_id"])


def downgrade():
    raise RuntimeError("Restore a verified backup to downgrade the guest schema.")
