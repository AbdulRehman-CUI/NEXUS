"""Initial immutable schema for the local Phase 1 data plane."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def scoped():
    return sa.Column(
        "workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )


def document():
    return sa.Column(
        "document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )


def identity():
    return sa.Column("id", sa.String(), primary_key=True)


def upgrade():
    op.create_table(
        "workspaces",
        identity(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("cloud_opt_in", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "documents",
        identity(),
        scoped(),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("extension", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False, unique=True),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("workspace_id", "content_hash"),
    )
    op.create_table(
        "spans",
        identity(),
        scoped(),
        document(),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("heading", sa.String()),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_table(
        "chunks",
        identity(),
        scoped(),
        document(),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("span_id", sa.String(), sa.ForeignKey("spans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
    )
    op.create_table(
        "jobs",
        identity(),
        scoped(),
        document(),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "chats",
        identity(),
        scoped(),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "messages",
        identity(),
        scoped(),
        sa.Column("chat_id", sa.String(), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provider", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "citations",
        identity(),
        scoped(),
        document(),
        sa.Column(
            "message_id", sa.String(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chunk_id", sa.String(), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    for table in ["documents", "spans", "chunks", "jobs", "chats", "messages", "citations"]:
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
    for table in ["spans", "chunks", "jobs", "citations"]:
        op.create_index(f"ix_{table}_document_id", table, ["document_id"])
    op.create_index("ix_messages_chat_id", "messages", ["chat_id"])
    op.create_index("ix_citations_message_id", "citations", ["message_id"])


def downgrade():
    for table in ["citations", "messages", "chats", "jobs", "chunks", "spans", "documents", "workspaces"]:
        op.drop_table(table)
