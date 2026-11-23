"""Add guest_default_sort to user

Revision ID: c8d9e0f1a2b3
Revises: d6e7f8a9b0c1
Create Date: 2026-11-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c8d9e0f1a2b3"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "guest_default_sort",
                sa.String(length=10),
                nullable=False,
                server_default="recommended",
            )
        )


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("guest_default_sort")
