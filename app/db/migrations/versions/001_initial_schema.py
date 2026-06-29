"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-26
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("ticker", sa.String(20), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("market", sa.String(10), nullable=False),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("active", sa.Boolean, default=True),
        sa.Column("added_to_watchlist", sa.DateTime, nullable=True),
    )

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("companies.ticker"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("open", sa.Float, nullable=True),
        sa.Column("high", sa.Float, nullable=True),
        sa.Column("low", sa.Float, nullable=True),
        sa.Column("close", sa.Float, nullable=True),
        sa.Column("volume", sa.Integer, nullable=True),
        sa.Column("sma_50", sa.Float, nullable=True),
        sa.Column("sma_200", sa.Float, nullable=True),
        sa.Column("rsi_14", sa.Float, nullable=True),
        sa.Column("macd", sa.Float, nullable=True),
        sa.Column("golden_cross", sa.Boolean, nullable=True),
        sa.UniqueConstraint("ticker", "date", name="uq_price_ticker_date"),
    )
    op.create_index("ix_price_ticker_date", "price_history", ["ticker", "date"])

    op.create_table(
        "fundamentals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("companies.ticker"), nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("pe_ratio", sa.Float, nullable=True),
        sa.Column("pb_ratio", sa.Float, nullable=True),
        sa.Column("revenue_ttm", sa.Float, nullable=True),
        sa.Column("revenue_growth_yoy", sa.Float, nullable=True),
        sa.Column("earnings_growth_yoy", sa.Float, nullable=True),
        sa.Column("debt_to_equity", sa.Float, nullable=True),
        sa.Column("free_cash_flow", sa.Float, nullable=True),
        sa.Column("market_cap", sa.Float, nullable=True),
        sa.Column("raw_json", sa.JSON, nullable=True),
    )

    op.create_table(
        "earnings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("companies.ticker"), nullable=False),
        sa.Column("quarter_end", sa.Date, nullable=False),
        sa.Column("eps_estimate", sa.Float, nullable=True),
        sa.Column("eps_actual", sa.Float, nullable=True),
        sa.Column("surprise_pct", sa.Float, nullable=True),
        sa.Column("revenue_estimate", sa.Float, nullable=True),
        sa.Column("revenue_actual", sa.Float, nullable=True),
    )

    op.create_table(
        "news",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("companies.ticker"), nullable=False),
        sa.Column("published_at", sa.DateTime, nullable=False),
        sa.Column("headline", sa.String(500), nullable=False),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("sentiment_score", sa.Float, nullable=True),
    )

    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), sa.ForeignKey("companies.ticker"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("signal", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("timeframe", sa.String(5), default="1M"),
        sa.Column("risk_level", sa.String(20), nullable=True),
        sa.Column("current_price", sa.Float, nullable=False),
        sa.Column("target_price_low", sa.Float, nullable=True),
        sa.Column("target_price_base", sa.Float, nullable=True),
        sa.Column("target_price_high", sa.Float, nullable=True),
        sa.Column("bull_case", sa.Text, nullable=True),
        sa.Column("bear_case", sa.Text, nullable=True),
        sa.Column("final_reasoning", sa.Text, nullable=True),
        sa.Column("key_catalysts", sa.JSON, nullable=True),
        sa.Column("key_risks", sa.JSON, nullable=True),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("data_sources", sa.JSON, nullable=True),
        sa.Column("full_output", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("suggestions")
    op.drop_table("news")
    op.drop_table("earnings")
    op.drop_table("fundamentals")
    op.drop_index("ix_price_ticker_date", table_name="price_history")
    op.drop_table("price_history")
    op.drop_table("companies")
