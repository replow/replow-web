"""Add free-form friend link categories, without touching existing records."""
from alembic import op
import sqlalchemy as sa

revision = "20261022_0008"
down_revision = "20261017_0007"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("friend_links", sa.Column("category", sa.String(length=80), nullable=True))

def downgrade() -> None:
    op.drop_column("friend_links", "category")
