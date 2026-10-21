"""Add language and RSS metadata to friend links."""

from alembic import op
import sqlalchemy as sa


revision = "20260923_0002"
down_revision = "20260905_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "friend_links",
        sa.Column("language", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "friend_links",
        sa.Column("rss_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "friend_link_applications",
        sa.Column("language", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "friend_link_applications",
        sa.Column("rss_url", sa.String(length=2048), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("friend_link_applications", "rss_url")
    op.drop_column("friend_link_applications", "language")
    op.drop_column("friend_links", "rss_url")
    op.drop_column("friend_links", "language")

