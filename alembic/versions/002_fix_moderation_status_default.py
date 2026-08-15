"""Fix moderation_status column: strip spurious quotes from existing rows and correct the default.

Revision ID: 002_fix_moderation_status_default
Revises: 001_add_missing_columns
Create Date: 2026-04-15

Migration 001 used server_default="'approved'" which rendered correctly in DDL
but Alembic's batch_alter_table path double-wrapped the quotes, so all rows
received the literal string "'approved'" (with quotes) instead of "approved".
This migration trims those quotes and resets the column default.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "002_fix_modstatus"
down_revision: Union[str, None] = "001_add_missing_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fix existing rows: strip the spurious surrounding single quotes
    op.execute(
        text(
            "UPDATE pets SET moderation_status = 'approved' "
            "WHERE moderation_status = '''approved'''"
        )
    )

    # Fix the column default so future inserts use the bare string
    op.execute(
        text(
            "ALTER TABLE pets ALTER COLUMN moderation_status SET DEFAULT 'approved'"
        )
    )


def downgrade() -> None:
    # Restore the broken default (only useful for development rollback)
    op.execute(
        text(
            "ALTER TABLE pets ALTER COLUMN moderation_status SET DEFAULT '''approved'''"
        )
    )
