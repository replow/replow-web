"""Track media storage backend and checksum for R2/local media routing."""

from alembic import op
import sqlalchemy as sa


revision = "20260926_0004"
down_revision = "20260925_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_objects",
        sa.Column("storage_backend", sa.String(length=16), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "media_objects",
        sa.Column("sha256", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("media_objects", "sha256")
    op.drop_column("media_objects", "storage_backend")
