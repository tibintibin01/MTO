"""Add organizational property portfolios.

Revision ID: f6a1b2c3d4e5
Revises: e4c8a1b7d2f6
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a1b2c3d4e5"
down_revision = "e4c8a1b7d2f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "property_portfolios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("created_by", sa.String(length=150), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("name", name="uq_property_portfolios_name"),
    )
    op.create_index(
        "ix_property_portfolios_is_active",
        "property_portfolios",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ix_property_portfolios_active_name",
        "property_portfolios",
        ["is_active", "name"],
        unique=False,
    )

    op.create_table(
        "property_portfolio_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("linked_by", sa.String(length=150), nullable=False),
        sa.Column(
            "linked_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["property_portfolios.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "property_id",
            name="uq_property_portfolio_links_property_id",
        ),
    )
    op.create_index(
        "ix_property_portfolio_links_portfolio_id",
        "property_portfolio_links",
        ["portfolio_id"],
        unique=False,
    )
    op.create_index(
        "ix_property_portfolio_links_portfolio_property",
        "property_portfolio_links",
        ["portfolio_id", "property_id"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "ix_property_portfolio_links_portfolio_property",
        table_name="property_portfolio_links",
    )
    op.drop_index(
        "ix_property_portfolio_links_portfolio_id",
        table_name="property_portfolio_links",
    )
    op.drop_table("property_portfolio_links")
    op.drop_index(
        "ix_property_portfolios_active_name",
        table_name="property_portfolios",
    )
    op.drop_index(
        "ix_property_portfolios_is_active",
        table_name="property_portfolios",
    )
    op.drop_table("property_portfolios")
