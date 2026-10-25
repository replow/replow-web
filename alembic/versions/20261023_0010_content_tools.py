"""Recoverable media removal, article revisions and private autosaves."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT, BIGINT

revision = '20261023_0010'
down_revision = '20261022_0009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('media_objects', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.add_column('media_objects', sa.Column('deleted_by', BIGINT(unsigned=True), nullable=True))
    op.create_index('ix_media_trash_owner', 'media_objects', ['deleted_at', 'uploader_id'])
    op.create_table('article_versions',
        sa.Column('id', BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column('article_id', BIGINT(unsigned=True), sa.ForeignKey('articles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', BIGINT(unsigned=True), nullable=True),
        sa.Column('reason', sa.String(24), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('snapshot_json', LONGTEXT, nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        mysql_charset='utf8mb4')
    op.create_index('ix_versions_article', 'article_versions', ['article_id', 'id'])
    op.create_table('article_autosaves',
        sa.Column('actor_id', BIGINT(unsigned=True), sa.ForeignKey('users.uid', ondelete='CASCADE'), primary_key=True),
        sa.Column('draft_key', sa.String(96), primary_key=True),
        sa.Column('article_id', BIGINT(unsigned=True), sa.ForeignKey('articles.id', ondelete='CASCADE'), nullable=True),
        sa.Column('payload_json', LONGTEXT, nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        mysql_charset='utf8mb4')


def downgrade():
    op.drop_table('article_autosaves')
    op.drop_table('article_versions')
    op.drop_index('ix_media_trash_owner', 'media_objects')
    op.drop_column('media_objects', 'deleted_by')
    op.drop_column('media_objects', 'deleted_at')
