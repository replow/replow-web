"""Baseline the existing shared Replow MySQL schema.

The production schema predates this service and is intentionally not created,
altered, or dropped by the baseline revision.
"""

from alembic import op


revision = "20260905_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
