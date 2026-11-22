"""Add wishlist table, move gifts under it, drop user.list_name

One user can now own several named wishlists; each gift belongs to exactly one of
them. The user's pre-migration share_token moves onto their (single) migrated
list so every public /list/<token> link shared before this migration keeps working.

Revision ID: d6e7f8a9b0c1
Revises: d5e6f7a8b9c0
Create Date: 2026-11-22 00:00:00.000000

"""
import secrets
import string

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d6e7f8a9b0c1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


# same alphabet and length as the model's generate_list_code(), inlined so this
# migration stays self-contained even if the model helper changes later
LIST_CODE_ALPHABET = string.ascii_letters + string.digits


def _generate_list_code():
    return "".join(secrets.choice(LIST_CODE_ALPHABET) for _ in range(12))


def upgrade():
    op.create_table(
        "wishlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("share_token", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("share_token"),
        sa.UniqueConstraint("code"),
    )

    # wishlist_id starts nullable because gifts are backfilled below before the
    # NOT NULL switch. The FK is named: SQLite's batch table-rebuild can only carry
    # a named constraint (an unnamed one fails with "Constraint must have a name")
    with op.batch_alter_table("gift", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "wishlist_id",
                sa.Integer(),
                sa.ForeignKey("wishlist.id", name="fk_gift_wishlist_id_wishlist"),
                nullable=True,
            )
        )

    connection = op.get_bind()
    user = sa.table(
        "user",
        sa.column("id", sa.Integer),
        sa.column("username", sa.String),
        sa.column("list_name", sa.String),
        sa.column("share_token", sa.String),
    )
    wishlist = sa.table(
        "wishlist",
        sa.column("id", sa.Integer),
        sa.column("owner_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("share_token", sa.String),
        sa.column("code", sa.String),
    )
    gift = sa.table(
        "gift",
        sa.column("owner_id", sa.Integer),
        sa.column("wishlist_id", sa.Integer),
    )

    # one list per existing user, named after the current list_name (an empty or
    # NULL name falls back to the computed default, same rule as the old to_dict)
    users = connection.execute(
        sa.select(user.c.id, user.c.username, user.c.list_name, user.c.share_token)
    ).fetchall()
    for row in users:
        connection.execute(
            wishlist.insert().values(
                owner_id=row.id,
                name=row.list_name or f"{row.username}'s wishlist",
                # the user's public share token becomes the list's: regenerating it
                # here would orphan every /list/<token> link shared before this migration
                share_token=row.share_token,
                code=_generate_list_code(),
            )
        )

    # reassign every gift to its owner's (only) wishlist
    connection.execute(
        gift.update()
        .where(gift.c.wishlist_id.is_(None))
        .values(
            wishlist_id=sa.select(wishlist.c.id)
            .where(wishlist.c.owner_id == gift.c.owner_id)
            .scalar_subquery()
        )
    )

    with op.batch_alter_table("gift", schema=None) as batch_op:
        batch_op.alter_column("wishlist_id", existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("list_name")


def downgrade():
    connection = op.get_bind()
    user = sa.table(
        "user",
        sa.column("id", sa.Integer),
        sa.column("list_name", sa.String),
    )
    wishlist = sa.table(
        "wishlist",
        sa.column("id", sa.Integer),
        sa.column("owner_id", sa.Integer),
        sa.column("name", sa.String),
    )

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("list_name", sa.String(length=100), nullable=True))

    # the user's list_name is rebuilt from their first (oldest) list BEFORE the
    # wishlist table and its data are dropped below
    first_list_per_owner = {}
    rows = connection.execute(sa.select(wishlist.c.owner_id, wishlist.c.name).order_by(wishlist.c.id))
    for row in rows:
        first_list_per_owner.setdefault(row.owner_id, row.name)
    for owner_id, name in first_list_per_owner.items():
        connection.execute(
            user.update().where(user.c.id == owner_id).values(list_name=name)
        )

    with op.batch_alter_table("gift", schema=None) as batch_op:
        batch_op.drop_column("wishlist_id")

    op.drop_table("wishlist")
