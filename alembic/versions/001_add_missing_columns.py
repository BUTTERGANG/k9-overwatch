"""Add missing columns: match_count, user fields, resolved fields on pets table.

Revision ID: 001_add_missing_columns
Revises:
Create Date: 2026-04-15

These columns were added to the ORM model (PetRow) but the database was never
migrated, causing every SQLAlchemy PetRow query to fail with
"column does not exist".

Affected table: pets
Missing columns:
  - match_count       (Integer, NOT NULL, default 0)
  - user_id           (VARCHAR 36, nullable)
  - user_submitted    (Boolean, default False)
  - moderation_status (Text, default 'approved')
  - resolved          (Boolean, default False)
  - resolved_at       (Timestamp, nullable)
  - resolved_reason   (Text, nullable)
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001_add_missing_columns"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch mode for SQLite compatibility (batch_alter_table is a no-op on PG)
    with op.batch_alter_table("pets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "match_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("user_id", sa.String(36), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "user_submitted",
                sa.Boolean(),
                nullable=True,
                server_default="false",
            )
        )
        batch_op.add_column(
            sa.Column(
                "moderation_status",
                sa.Text(),
                nullable=True,
                server_default="'approved'",
            )
        )
        batch_op.add_column(
            sa.Column(
                "resolved",
                sa.Boolean(),
                nullable=True,
                server_default="false",
            )
        )
        batch_op.add_column(
            sa.Column("resolved_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("resolved_reason", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("pets") as batch_op:
        batch_op.drop_column("resolved_reason")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("resolved")
        batch_op.drop_column("moderation_status")
        batch_op.drop_column("user_submitted")
        batch_op.drop_column("user_id")
        batch_op.drop_column("match_count")
