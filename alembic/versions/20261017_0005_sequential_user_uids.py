"""Allocate user UIDs sequentially from 10000 without renumbering users."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20261017_0005"
down_revision = "20260926_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_uid_sequences",
        sa.Column("id", mysql.TINYINT(unsigned=True), primary_key=True),
        sa.Column("last_uid", mysql.BIGINT(unsigned=True), nullable=False),
        mysql_engine="InnoDB",
    )
    op.execute(
        "INSERT INTO user_uid_sequences (id, last_uid) "
        "SELECT 1, GREATEST(9999, COALESCE(MAX(uid), 0)) FROM users"
    )


def downgrade():
    op.drop_table("user_uid_sequences")
