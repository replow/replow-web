"""User restrictions, notification outbox and readable audit request snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT, BIGINT

revision = "20261028_0011"
down_revision = "20261023_0010"
branch_labels = None
depends_on = None


def upgrade():
    for kind in ("ban", "mute", "publish"):
        op.add_column("users", sa.Column(kind + "_started_at", sa.DateTime(), nullable=True))
        op.add_column("users", sa.Column(kind + "_until", sa.DateTime(), nullable=True))
        op.add_column("users", sa.Column(kind + "_reason", sa.String(1000), nullable=True))
    op.add_column("admin_audit_logs", sa.Column("request_details", LONGTEXT, nullable=True))
    op.add_column("admin_audit_logs", sa.Column("target_name", sa.String(500), nullable=True))
    op.create_table("moderation_mail_outbox",
        sa.Column("id", BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        mysql_charset="utf8mb4", mysql_engine="InnoDB")
    op.create_index("ix_moderation_mail_pending", "moderation_mail_outbox", ["sent_at", "next_attempt_at"])


def downgrade():
    op.drop_table("moderation_mail_outbox")
    op.drop_column("admin_audit_logs", "target_name")
    op.drop_column("admin_audit_logs", "request_details")
    for kind in ("ban", "mute", "publish"):
        for suffix in ("_started_at", "_until", "_reason"):
            op.drop_column("users", kind + suffix)
