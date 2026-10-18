"""positions table — track purchased shares for hold/sell review

Revision ID: 002
Revises: 001
Create Date: 2026-10-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("companies.ticker"), nullable=False),
        sa.Column("purchase_date", sa.Date, nullable=False),
        sa.Column("purchase_price", sa.Float, nullable=False),
        sa.Column("quantity", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("closed_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_positions_ticker", "positions", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_positions_ticker", table_name="positions")
    op.drop_table("positions")
