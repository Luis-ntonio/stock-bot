from sqlalchemy import (
    Column, String, Float, Integer, Date, DateTime, Boolean, Text, JSON,
    ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship
from datetime import datetime


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    ticker = Column(String(20), primary_key=True)
    name = Column(String(200), nullable=False)
    market = Column(String(10), nullable=False)   # "US" | "CRYPTO" | "LATAM"
    sector = Column(String(100), nullable=True)
    industry = Column(String(100), nullable=True)
    active = Column(Boolean, default=True)
    added_to_watchlist = Column(DateTime, default=datetime.utcnow)

    price_history = relationship("PriceHistory", back_populates="company", lazy="dynamic")
    fundamentals = relationship("FundamentalData", back_populates="company", lazy="dynamic")
    earnings = relationship("EarningsRecord", back_populates="company", lazy="dynamic")
    news = relationship("NewsItem", back_populates="company", lazy="dynamic")
    suggestions = relationship("Suggestion", back_populates="company", lazy="dynamic")


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_price_ticker_date"),
        Index("ix_price_ticker_date", "ticker", "date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)
    sma_50 = Column(Float, nullable=True)
    sma_200 = Column(Float, nullable=True)
    rsi_14 = Column(Float, nullable=True)
    macd = Column(Float, nullable=True)
    golden_cross = Column(Boolean, nullable=True)

    company = relationship("Company", back_populates="price_history")


class FundamentalData(Base):
    __tablename__ = "fundamentals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    pe_ratio = Column(Float, nullable=True)
    pb_ratio = Column(Float, nullable=True)
    revenue_ttm = Column(Float, nullable=True)
    revenue_growth_yoy = Column(Float, nullable=True)
    earnings_growth_yoy = Column(Float, nullable=True)
    debt_to_equity = Column(Float, nullable=True)
    free_cash_flow = Column(Float, nullable=True)
    market_cap = Column(Float, nullable=True)
    raw_json = Column(JSON, nullable=True)

    company = relationship("Company", back_populates="fundamentals")


class EarningsRecord(Base):
    __tablename__ = "earnings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    quarter_end = Column(Date, nullable=False)
    eps_estimate = Column(Float, nullable=True)
    eps_actual = Column(Float, nullable=True)
    surprise_pct = Column(Float, nullable=True)
    revenue_estimate = Column(Float, nullable=True)
    revenue_actual = Column(Float, nullable=True)

    company = relationship("Company", back_populates="earnings")


class NewsItem(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    published_at = Column(DateTime, nullable=False)
    headline = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=True)
    source = Column(String(100), nullable=True)
    sentiment_score = Column(Float, nullable=True)

    company = relationship("Company", back_populates="news")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(20), ForeignKey("companies.ticker"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    signal = Column(String(10), nullable=False)
    confidence = Column(Float, nullable=False)
    timeframe = Column(String(5), default="1M")
    risk_level = Column(String(20), nullable=True)
    current_price = Column(Float, nullable=False)
    target_price_low = Column(Float, nullable=True)
    target_price_base = Column(Float, nullable=True)
    target_price_high = Column(Float, nullable=True)
    bull_case = Column(Text, nullable=True)
    bear_case = Column(Text, nullable=True)
    final_reasoning = Column(Text, nullable=True)
    key_catalysts = Column(JSON, nullable=True)
    key_risks = Column(JSON, nullable=True)
    llm_model = Column(String(100), nullable=True)
    data_sources = Column(JSON, nullable=True)
    full_output = Column(JSON, nullable=True)

    company = relationship("Company", back_populates="suggestions")
