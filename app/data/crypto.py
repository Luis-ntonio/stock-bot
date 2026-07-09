import asyncio
import httpx
import pandas as pd
from datetime import datetime, timedelta, date
from app.config import settings
from app.data.rate_limiter import get_rate_limiter
from app.llm.schemas import FundamentalSnapshot
import structlog

logger = structlog.get_logger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_BASE = "https://api.binance.com/api/v3"

DEFAULT_CRYPTO_WATCHLIST = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOT", "LINK", "MATIC",
    "UNI", "ATOM", "LTC", "BCH", "NEAR", "APT", "ARB", "OP", "INJ", "SUI",
]

COINGECKO_ID_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
    "SOL": "solana", "XRP": "ripple", "ADA": "cardano",
    "AVAX": "avalanche-2", "DOT": "polkadot", "LINK": "chainlink",
    "MATIC": "matic-network", "UNI": "uniswap", "ATOM": "cosmos",
    "LTC": "litecoin", "BCH": "bitcoin-cash", "NEAR": "near",
    "APT": "aptos", "ARB": "arbitrum", "OP": "optimism",
    "INJ": "injective-protocol", "SUI": "sui",
}

BINANCE_SYMBOL_MAP = {
    k: f"{k}USDT" for k in DEFAULT_CRYPTO_WATCHLIST
    if k not in ("MATIC",)
}
BINANCE_SYMBOL_MAP["MATIC"] = "MATICUSDT"


async def get_price_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    try:
        df = await _binance_klines(symbol, period)
        if df is not None and len(df) > 20:
            return df
    except Exception as e:
        logger.warning("Binance klines failed", symbol=symbol, error=str(e))

    try:
        df = await _coingecko_ohlcv(symbol, period)
        if df is not None and len(df) > 20:
            return df
    except Exception as e:
        logger.warning("CoinGecko OHLCV failed", symbol=symbol, error=str(e))

    raise RuntimeError(f"All crypto price sources failed for {symbol}")


async def _binance_klines(symbol: str, period: str) -> pd.DataFrame | None:
    rl = get_rate_limiter()
    await rl.acquire("binance")

    binance_symbol = BINANCE_SYMBOL_MAP.get(symbol.upper(), f"{symbol}USDT")
    days = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730}.get(period, 365)
    limit = min(days, 1000)

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BINANCE_BASE}/klines",
            params={"symbol": binance_symbol, "interval": "1d", "limit": limit},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    if not data:
        return None

    records = [
        {
            "date": date.fromtimestamp(candle[0] / 1000),
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]),
        }
        for candle in data
    ]
    return pd.DataFrame(records).set_index("date")


async def _coingecko_ohlcv(symbol: str, period: str) -> pd.DataFrame | None:
    rl = get_rate_limiter()
    await rl.acquire("coingecko")

    coin_id = COINGECKO_ID_MAP.get(symbol.upper())
    if not coin_id:
        return None

    days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730}
    days = days_map.get(period, 365)

    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key

    async with httpx.AsyncClient(headers=headers) as client:
        r = await client.get(
            f"{COINGECKO_BASE}/coins/{coin_id}/ohlc",
            params={"vs_currency": "usd", "days": str(days)},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    if not data:
        return None

    records = [
        {
            "date": date.fromtimestamp(row[0] / 1000),
            "open": row[1], "high": row[2], "low": row[3], "close": row[4],
            "volume": 0,
        }
        for row in data
    ]
    df = pd.DataFrame(records).groupby("date").last()
    return df


async def get_company_info(symbol: str) -> dict[str, str | None]:
    empty = {"name": None, "sector": None, "industry": None}

    coin_id = COINGECKO_ID_MAP.get(symbol.upper())
    if not coin_id:
        return empty

    rl = get_rate_limiter()
    await rl.acquire("coingecko")

    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key

    try:
        async with httpx.AsyncClient(headers=headers) as client:
            r = await client.get(
                f"{COINGECKO_BASE}/coins/{coin_id}",
                params={
                    "localization": "false", "tickers": "false",
                    "market_data": "false", "community_data": "false",
                    "developer_data": "false",
                },
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        return {"name": data.get("name"), "sector": "Crypto", "industry": None}
    except Exception as e:
        logger.debug("CoinGecko company info failed", symbol=symbol, error=str(e))
        return empty


async def get_fundamentals(symbol: str) -> FundamentalSnapshot:
    rl = get_rate_limiter()
    await rl.acquire("coingecko")

    coin_id = COINGECKO_ID_MAP.get(symbol.upper())
    if not coin_id:
        return FundamentalSnapshot()

    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key

    async with httpx.AsyncClient(headers=headers) as client:
        r = await client.get(
            f"{COINGECKO_BASE}/coins/{coin_id}",
            params={"localization": "false", "tickers": "false", "community_data": "false"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

    md = data.get("market_data", {})

    # Mapear campos reales de CoinGecko — crypto no tiene P/E, usamos proxies
    price_change_30d = md.get("price_change_percentage_30d")
    price_change_1y  = md.get("price_change_percentage_1y")
    market_cap_usd   = (md.get("market_cap") or {}).get("usd")
    total_volume_usd = (md.get("total_volume") or {}).get("usd")

    # revenue_growth_yoy ← variación de precio 1 año (proxy de adopción)
    revenue_growth_yoy = price_change_1y / 100 if price_change_1y is not None else None

    # free_cash_flow_yield ← volumen/market_cap (proxy de liquidez)
    fcf_yield = (total_volume_usd / market_cap_usd) if market_cap_usd and total_volume_usd else None

    return FundamentalSnapshot(
        pe_ratio=None,
        pb_ratio=None,
        revenue_growth_yoy=revenue_growth_yoy,
        earnings_growth_yoy=price_change_30d / 100 if price_change_30d is not None else None,
        debt_to_equity=None,
        free_cash_flow_yield=fcf_yield,
        eps_surprise_last_q=None,
        eps_surprise_avg_4q=None,
    )
