"""Admin audit trail, revocable devices and published photo albums."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20261017_0006"
down_revision = "20261017_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_uid", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_agent", sa.String(512), nullable=False, server_default=""),
        sa.Column("ip_address", sa.String(45), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_uid"], ["users.uid"], onupdate="CASCADE", ondelete="CASCADE"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("ix_auth_sessions_user", "auth_sessions", ["user_uid", "revoked_at", "expires_at"])
    op.create_table("admin_audit_logs",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("actor_uid", sa.String(20), nullable=True),
        sa.Column("actor_name", sa.String(80), nullable=False, server_default=""),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("resource", sa.String(160), nullable=False),
        sa.Column("target_id", sa.String(80), nullable=False, server_default=""),
        sa.Column("changes", mysql.JSON(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_index("ix_audit_created", "admin_audit_logs", ["created_at", "id"])
    op.create_table("photo_albums",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False, server_default=""),
        sa.Column("cover_url", sa.String(2048), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")
    op.create_table("album_photos",
        sa.Column("id", mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column("album_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("media_id", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("caption", sa.String(500), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["album_id"], ["photo_albums.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media_objects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("album_id", "media_id", name="uq_album_media"),
        mysql_engine="InnoDB", mysql_charset="utf8mb4")


def downgrade():
    for table in ["album_photos", "photo_albums", "admin_audit_logs", "auth_sessions"]:
        op.drop_table(table)
