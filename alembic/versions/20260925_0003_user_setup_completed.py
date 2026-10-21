"""Track whether a code-login created account has finished setup.

Verification-code login now creates the account on the fly when the email is
unknown. Such an account has neither a username chosen by the person nor a
password, and the account console asks them to set both right after signing
in. ``setup_completed`` records whether that step is still pending.

``DEFAULT 1`` keeps every pre-existing path (password registration, admin
created users) untouched: they were always "done". Only the new code-login
path inserts 0 explicitly, and the backfill flips the few legacy rows whose
password was never set to pending so they get the same prompt.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260925_0003"
down_revision = "20260923_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("setup_completed", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.execute(
        "UPDATE users SET setup_completed = 0 WHERE password_hash = '!password-unset!'"
    )


def downgrade() -> None:
    op.drop_column("users", "setup_completed")
