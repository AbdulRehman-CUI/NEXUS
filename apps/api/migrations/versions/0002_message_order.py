"""Stable conversation order independent of clock resolution or UUID order."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    op.add_column("messages", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.execute("""WITH ordered AS (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY chat_id ORDER BY created_at, rowid) AS pos FROM messages
    ) UPDATE messages SET position = (SELECT pos FROM ordered WHERE ordered.id = messages.id)""")


def downgrade():
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("position")
