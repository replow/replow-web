"""Track per-user comment image upload limits.

Revision ID: 20261022_0009
Revises: 20261022_0008
"""
from alembic import op

revision = "20261022_0009"
down_revision = "20261022_0008"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS comment_image_uploads (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            user_id BIGINT UNSIGNED NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_comment_upload_user_time(user_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

def downgrade() -> None:
    op.drop_table("comment_image_uploads")
