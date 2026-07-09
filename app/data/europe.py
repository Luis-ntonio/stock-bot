import asyncio
import pandas as pd
from app.data.rate_limiter import get_rate_limiter
from app.data.us_stocks import add_technical_indicators
from app.llm.schemas import FundamentalSnapshot
import structlog

logger = structlog.get_logger(__name__)

# Nemónico local -> ticker yfinance (sufijo de bolsa europea).
# XETRA (.DE) es la bolsa por defecto para large caps alemanas.
EU_TICKERS_YF = {
    "MBG": "MBG.DE",    # Mercedes-Benz Group
    "BMW": "BMW.DE",
    "VOW3": "VOW3.DE",  # Volkswagen (preferente)
    "SAP": "SAP.DE",
    "SIE": "SIE.DE",    # Siemens
    "ALV": "ALV.DE",    # Allianz
    "DTE": "DTE.DE",    # Deutsche Telekom
    "BAS": "BAS.DE",    # BASF
    "BAYN": "BAYN.DE",  # Bayer
    "ADS": "ADS.DE",    # Adidas
    "DBK": "DBK.DE",    # Deutsche Bank
    "MUV2": "MUV2.DE",  # Munich Re
    "IFX": "IFX.DE",    # Infineon
    "RWE": "RWE.DE",
    "EOAN": "EOAN.DE",  # E.ON
}


def _resolve_ticker(ticker: str) -> str:
    if ticker in EU_TICKERS_YF:
        return EU_TICKERS_YF[ticker]
    # Ya viene con sufijo de bolsa (.DE, .PA, .AS, .L, ...) o el caller lo sabe
    return ticker


# Finnhub (fuente de peers para US) no cubre bolsas europeas, así que se usa
# un agrupamiento sectorial curado a mano entre los tickers ya soportados.
EU_PEER_GROUPS: list[list[str]] = [
    ["MBG", "BMW", "VOW3"],           # Automotriz
    ["SAP", "SIE", "IFX"],            # Tech / industrial
    ["ALV", "MUV2", "DBK"],           # Financiero / seguros
    ["BAS", "BAYN"],                  # Químico / salud
    ["RWE", "EOAN"],                  # Utilities / energía
]


async def get_peers(ticker: str, n: int = 5) -> list[str]:
    for group in EU_PEER_GROUPS:
        if ticker in group:
            return [t for t in group if t != ticker][:n]
    return []


async def get_price_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    yf_ticker = _resolve_ticker(ticker)

    df = await _yfinance_europe(yf_ticker, period)
    if df is None or len(df) < 20:
        raise RuntimeError(f"No price data available for European ticker {ticker}")

    return add_technical_indicators(df)


async def _yfinance_europe(yf_ticker: str, period: str) -> pd.DataFrame | None:
    rl = get_rate_limiter()
    await rl.acquire("yfinance")

    loop = asyncio.get_event_loop()

    def _fetch():
        import yfinance as yf
        from curl_cffi.requests import Session as CurlSession
        with CurlSession(impersonate="chrome") as session:
            t = yf.Ticker(yf_ticker, session=session)
            df = t.history(period=period, interval="1d", auto_adjust=True)
        return df

    df = await loop.run_in_executor(None, _fetch)
    if df.empty:
        return None

    df.index = pd.to_datetime(df.index).date
    df.index.name = "date"
    return df[["Open", "High", "Low", "Close", "Volume"]].rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}
    )


async def get_fundamentals(ticker: str) -> FundamentalSnapshot:
    yf_ticker = _resolve_ticker(ticker)

    try:
        info = await _yfinance_info(yf_ticker)
        if info:
            fcf = info.get("freeCashflow")
            market_cap = info.get("marketCap")
            fcf_yield = (fcf / market_cap) if fcf and market_cap else None

            return FundamentalSnapshot(
                pe_ratio=info.get("trailingPE"),
                pb_ratio=info.get("priceToBook"),
                revenue_growth_yoy=info.get("revenueGrowth"),
                earnings_growth_yoy=info.get("earningsGrowth"),
                debt_to_equity=info.get("debtToEquity"),
                free_cash_flow_yield=fcf_yield,
            )
    except Exception as e:
        logger.warning("yfinance info failed (EU)", ticker=ticker, error=str(e))

    return FundamentalSnapshot()


async def _yfinance_info(yf_ticker: str) -> dict | None:
    rl = get_rate_limiter()
    await rl.acquire("yfinance")

    loop = asyncio.get_event_loop()

    def _fetch():
        import yfinance as yf
        from curl_cffi.requests import Session as CurlSession
        with CurlSession(impersonate="chrome") as session:
            return yf.Ticker(yf_ticker, session=session).info

    return await loop.run_in_executor(None, _fetch)
