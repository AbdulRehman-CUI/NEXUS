"""Vault manifests, graph, retrieval profiles, index generations and transactional FTS5."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def pk():
    return sa.Column("id", sa.String(), primary_key=True)


def workspace():
    return sa.Column(
        "workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )


def upgrade():
    op.add_column("workspaces", sa.Column("index_configuration", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("origin", sa.String(), nullable=False, server_default="upload"))
    op.add_column("messages", sa.Column("evidence_snapshot", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("messages", sa.Column("diagnostics", sa.JSON(), nullable=False, server_default="{}"))
    connection = op.get_bind()
    for message_id in (
        connection.execute(sa.text("SELECT DISTINCT message_id FROM citations")).scalars().all()
    ):
        items = [
            json.loads(p)
            for p in connection.execute(
                sa.text("SELECT payload FROM citations WHERE message_id=:id"), {"id": message_id}
            ).scalars()
        ]
        items.sort(key=lambda p: p.get("order", 0))
        connection.execute(
            sa.text("UPDATE messages SET evidence_snapshot=:items WHERE id=:id"),
            {"items": json.dumps(items), "id": message_id},
        )
    op.create_table(
        "retrieval_profiles",
        sa.Column(
            "workspace_id", sa.String(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("configuration", sa.JSON(), nullable=False),
    )
    op.create_table(
        "vaults",
        pk(),
        workspace(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_scan", sa.String()),
        sa.Column("scan_requested_at", sa.String()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "notes",
        pk(),
        workspace(),
        sa.Column("vault_id", sa.String(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("vault_id", "path"),
    )
    op.create_table(
        "note_tags",
        sa.Column("note_id", sa.String(), sa.ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag", sa.String(), primary_key=True),
        workspace(),
    )
    op.create_table(
        "note_links",
        pk(),
        workspace(),
        sa.Column("vault_id", sa.String(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(), sa.ForeignKey("notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.String(), sa.ForeignKey("notes.id", ondelete="SET NULL")),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("anchor", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
    )
    op.create_table(
        "sync_runs",
        pk(),
        workspace(),
        sa.Column("vault_id", sa.String(), sa.ForeignKey("vaults.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manifest_hash", sa.String(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("cursor", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "index_generations",
        pk(),
        workspace(),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    for table in ("vaults", "notes", "note_tags", "note_links", "sync_runs", "index_generations"):
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
    for table in ("notes", "note_links", "sync_runs"):
        op.create_index(f"ix_{table}_vault_id", table, ["vault_id"])
    op.create_index("ix_notes_document_id", "notes", ["document_id"])
    for field in ("source_id", "target_id"):
        op.create_index(f"ix_note_links_{field}", "note_links", [field])
    op.create_index(
        "one_active_index",
        "index_generations",
        ["workspace_id"],
        unique=True,
        sqlite_where=sa.text("active=1"),
        postgresql_where=sa.text("active"),
    )
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute("""CREATE VIRTUAL TABLE chunk_fts USING fts5(
        chunk_id UNINDEXED, workspace_id UNINDEXED, document_id UNINDEXED,
        version_id UNINDEXED, fingerprint UNINDEXED, title, metadata, text,
        tokenize='unicode61 remove_diacritics 2')""")
    insert = """INSERT INTO chunk_fts SELECT c.id,c.workspace_id,c.document_id,c.version_id,c.fingerprint,d.title,
        COALESCE((SELECT group_concat(n.path || ' ' || n.tags, ' ') FROM notes n WHERE n.document_id=c.document_id AND n.deleted=0),''),c.text
        FROM chunks c JOIN documents d ON d.id=c.document_id"""
    op.execute(insert)
    op.execute(
        f"CREATE TRIGGER chunks_fts_insert AFTER INSERT ON chunks BEGIN {insert} WHERE c.id=new.id; END"
    )
    op.execute(
        "CREATE TRIGGER chunks_fts_delete AFTER DELETE ON chunks BEGIN DELETE FROM chunk_fts WHERE chunk_id=old.id; END"
    )
    op.execute(
        f"CREATE TRIGGER chunks_fts_update AFTER UPDATE ON chunks BEGIN DELETE FROM chunk_fts WHERE chunk_id=old.id; {insert} WHERE c.id=new.id; END"
    )
    update = """UPDATE chunk_fts SET metadata=COALESCE((SELECT group_concat(n.path || ' ' || n.tags,' ') FROM notes n WHERE n.document_id=chunk_fts.document_id AND n.deleted=0),'')"""
    op.execute(
        f"CREATE TRIGGER notes_fts_insert AFTER INSERT ON notes BEGIN {update} WHERE document_id=new.document_id; END"
    )
    op.execute(
        f"CREATE TRIGGER notes_fts_update AFTER UPDATE ON notes BEGIN {update} WHERE document_id IN (old.document_id,new.document_id); END"
    )
    op.execute(
        f"CREATE TRIGGER notes_fts_delete AFTER DELETE ON notes BEGIN {update} WHERE document_id=old.document_id; END"
    )


def downgrade():
    raise RuntimeError(
        "Phase 2 schema downgrade is unsupported; restore a stopped full data backup. Index rollback is supported through the API."
    )
