"""Managed short updates migrated from Firefly."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
revision = "20261017_0007"
down_revision = "20261017_0006"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("dynamics",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("legacy_id", sa.String(64), nullable=True),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("images", mysql.JSON(), nullable=False),
        sa.Column("location", sa.String(160), nullable=False, server_default=""),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_dynamics_legacy"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("ix_dynamics_public", "dynamics", ["is_published","pinned","published_at","id"])

def downgrade():
    op.drop_table("dynamics")
