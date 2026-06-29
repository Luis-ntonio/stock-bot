import asyncio
import pandas as pd
import ta as ta_lib
from datetime import date, datetime, timedelta
from typing import Any
import httpx
from curl_cffi.requests import AsyncSession as CurlSession
from app.config import settings
from app.data.rate_limiter import get_rate_limiter
from app.llm.schemas import FundamentalSnapshot
import structlog

logger = structlog.get_logger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"
FMP_BASE = "https://financialmodelingprep.com/api/v3"
FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


# ── Precios EOD ──────────────────────────────────────────────────────────────

async def get_price_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    try:
        df = await _yfinance_history(ticker, period, interval)
        if df is not None and len(df) > 20:
            return add_technical_indicators(df)
    except Exception as e:
        logger.warning("yfinance failed", ticker=ticker, error=str(e))

    try:
        df = await _finnhub_candles(ticker, period)
        if df is not None and len(df) > 20:
            return add_technical_indicators(df)
    except Exception as e:
        logger.warning("finnhub candles failed", ticker=ticker, error=str(e))

    raise RuntimeError(f"All price sources failed for {ticker}")


async def _yfinance_history(ticker: str, period: str, interval: str) -> pd.DataFrame | None:
    rl = get_rate_limiter()
    await rl.acquire("yfinance")

    loop = asyncio.get_event_loop()

    def _fetch():
        import yfinance as yf
        from curl_cffi.requests import Session as CurlSession
        # curl_cffi browser impersonation para mitigar 429s desde nov 2024
        with CurlSession(impersonate="chrome") as session:
            t = yf.Ticker(ticker, session=session)
            df = t.history(period=period, interval=interval, auto_adjust=True)
        return df

    df = await loop.run_in_executor(None, _fetch)
    if df.empty:
        return None
    df.index = pd.to_datetime(df.index).date
    df.index.name = "date"
    return df[["Open", "High", "Low", "Close", "Volume"]].rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    )


async def _finnhub_candles(ticker: str, period: str) -> pd.DataFrame | None:
    if not settings.finnhub_api_key:
        return None

    rl = get_rate_limiter()
    await rl.acquire("finnhub")

    end = int(datetime.now().timestamp())
    days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730}.get(period, 365)
    start = int((datetime.now() - timedelta(days=days)).timestamp())

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{FINNHUB_BASE}/stock/candle",
            params={"symbol": ticker, "resolution": "D", "from": start, "to": end,
                    "token": settings.finnhub_api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    if data.get("s") != "ok":
        return None

    df = pd.DataFrame({
        "date": [date.fromtimestamp(t) for t in data["t"]],
        "open": data["o"], "high": data["h"], "low": data["l"],
        "close": data["c"], "volume": data["v"],
    }).set_index("date")
    return df


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df["close"]

    df["SMA_50"] = ta_lib.trend.SMAIndicator(close, window=50).sma_indicator()
    df["SMA_200"] = ta_lib.trend.SMAIndicator(close, window=200).sma_indicator()
    df["RSI_14"] = ta_lib.momentum.RSIIndicator(close, window=14).rsi()

    macd = ta_lib.trend.MACD(close)
    df["MACD_12_26_9"] = macd.macd()
    df["MACDh_12_26_9"] = macd.macd_diff()
    df["MACDs_12_26_9"] = macd.macd_signal()

    bb = ta_lib.volatility.BollingerBands(close, window=20)
    df["BBU_20_2.0"] = bb.bollinger_hband()
    df["BBM_20_2.0"] = bb.bollinger_mavg()
    df["BBL_20_2.0"] = bb.bollinger_lband()

    df["golden_cross"] = df["SMA_50"] > df["SMA_200"]
    return df


# ── Fundamentales ────────────────────────────────────────────────────────────

async def get_fundamentals(ticker: str) -> FundamentalSnapshot:
    data: dict[str, Any] = {}

    # FMP como fuente primaria de fundamentales
    try:
        fmp_data = await _fmp_profile(ticker)
        if fmp_data:
            data.update(fmp_data)
    except Exception as e:
        logger.warning("FMP profile failed", ticker=ticker, error=str(e))

    # yfinance complementa campos que FMP no devuelve
    try:
        yf_data = await _yfinance_info(ticker)
        if yf_data:
            for k, v in yf_data.items():
                if data.get(k) is None:
                    data[k] = v
    except Exception as e:
        logger.warning("yfinance info failed", ticker=ticker, error=str(e))

    # EPS surprise desde Finnhub
    try:
        eps = await _finnhub_eps_surprise(ticker)
        if eps:
            data.update(eps)
    except Exception as e:
        logger.warning("finnhub EPS failed", ticker=ticker, error=str(e))

    return FundamentalSnapshot(
        pe_ratio=data.get("pe_ratio"),
        pb_ratio=data.get("pb_ratio"),
        revenue_growth_yoy=data.get("revenue_growth_yoy"),
        earnings_growth_yoy=data.get("earnings_growth_yoy"),
        debt_to_equity=data.get("debt_to_equity"),
        free_cash_flow_yield=data.get("free_cash_flow_yield"),
        eps_surprise_last_q=data.get("eps_surprise_last_q"),
        eps_surprise_avg_4q=data.get("eps_surprise_avg_4q"),
    )


async def _fmp_profile(ticker: str) -> dict | None:
    if not settings.fmp_api_key:
        return None

    rl = get_rate_limiter()
    await rl.acquire("fmp")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{FMP_STABLE_BASE}/profile",
            params={"symbol": ticker, "apikey": settings.fmp_api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    if not data:
        return None

    p = data[0] if isinstance(data, list) else data
    return {
        "pe_ratio": p.get("pe"),
        "pb_ratio": p.get("priceToBook"),
        "market_cap": p.get("mktCap"),
        "sector": p.get("sector"),
    }


async def _yfinance_info(ticker: str) -> dict | None:
    rl = get_rate_limiter()
    await rl.acquire("yfinance")

    loop = asyncio.get_event_loop()

    def _fetch():
        import yfinance as yf
        from curl_cffi.requests import Session as CurlSession
        with CurlSession(impersonate="chrome") as session:
            return yf.Ticker(ticker, session=session).info

    info = await loop.run_in_executor(None, _fetch)
    if not info:
        return None

    fcf = info.get("freeCashflow")
    market_cap = info.get("marketCap")
    fcf_yield = (fcf / market_cap) if fcf and market_cap else None

    return {
        "pe_ratio": info.get("trailingPE"),
        "pb_ratio": info.get("priceToBook"),
        "revenue_growth_yoy": info.get("revenueGrowth"),
        "earnings_growth_yoy": info.get("earningsGrowth"),
        "debt_to_equity": info.get("debtToEquity"),
        "free_cash_flow_yield": fcf_yield,
    }


async def _finnhub_eps_surprise(ticker: str) -> dict | None:
    if not settings.finnhub_api_key:
        return None

    rl = get_rate_limiter()
    await rl.acquire("finnhub")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{FINNHUB_BASE}/stock/earnings",
            params={"symbol": ticker, "limit": 4, "token": settings.finnhub_api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    if not data:
        return None

    surprises = [
        d["surprisePercent"]
        for d in data
        if d.get("surprisePercent") is not None
    ]
    if not surprises:
        return None

    return {
        "eps_surprise_last_q": surprises[0] if surprises else None,
        "eps_surprise_avg_4q": sum(surprises) / len(surprises) if surprises else None,
    }


# ── Earnings History ─────────────────────────────────────────────────────────

async def get_earnings_history(ticker: str, quarters: int = 8) -> list[dict]:
    try:
        return await _finnhub_earnings_history(ticker, quarters)
    except Exception as e:
        logger.warning("finnhub earnings history failed", ticker=ticker, error=str(e))
        return []


async def _finnhub_earnings_history(ticker: str, quarters: int) -> list[dict]:
    if not settings.finnhub_api_key:
        return []

    rl = get_rate_limiter()
    await rl.acquire("finnhub")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{FINNHUB_BASE}/stock/earnings",
            params={"symbol": ticker, "limit": quarters, "token": settings.finnhub_api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    return [
        {
            "quarter_end": d.get("period"),
            "eps_estimate": d.get("estimate"),
            "eps_actual": d.get("actual"),
            "surprise_pct": d.get("surprisePercent"),
        }
        for d in data
    ]


# ── Upcoming Earnings ────────────────────────────────────────────────────────

async def get_upcoming_earnings(ticker: str) -> dict | None:
    if not settings.finnhub_api_key:
        return None

    rl = get_rate_limiter()
    await rl.acquire("finnhub")

    today = date.today()
    end = today + timedelta(days=60)

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{FINNHUB_BASE}/calendar/earnings",
            params={"from": str(today), "to": str(end), "symbol": ticker,
                    "token": settings.finnhub_api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    entries = data.get("earningsCalendar", [])
    if not entries:
        return None

    e = entries[0]
    return {
        "date": e.get("date"),
        "eps_estimate": e.get("epsEstimate"),
        "revenue_estimate": e.get("revenueEstimate"),
        "hour": e.get("hour"),  # "BMO" | "AMC" | "DMH"
    }


# ── Peers ────────────────────────────────────────────────────────────────────

async def get_peers(ticker: str, n: int = 5) -> list[str]:
    try:
        peers = await _finnhub_peers(ticker)
        if peers:
            return peers[:n]
    except Exception as e:
        logger.warning("finnhub peers failed", ticker=ticker, error=str(e))

    try:
        peers = await _fmp_peers(ticker)
        if peers:
            return peers[:n]
    except Exception as e:
        logger.warning("FMP peers failed", ticker=ticker, error=str(e))

    return []


async def _finnhub_peers(ticker: str) -> list[str]:
    if not settings.finnhub_api_key:
        return []

    rl = get_rate_limiter()
    await rl.acquire("finnhub")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{FINNHUB_BASE}/stock/peers",
            params={"symbol": ticker, "token": settings.finnhub_api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    return [p for p in data if p != ticker]


async def _fmp_peers(ticker: str) -> list[str]:
    if not settings.fmp_api_key:
        return []

    rl = get_rate_limiter()
    await rl.acquire("fmp")

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{FMP_BASE}/stock_peers",
            params={"symbol": ticker, "apikey": settings.fmp_api_key},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    if not data:
        return []
    return [p for p in data[0].get("peersList", []) if p != ticker]
