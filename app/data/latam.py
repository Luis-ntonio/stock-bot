import asyncio
import httpx
import pandas as pd
from app.config import settings
from app.data.rate_limiter import get_rate_limiter
from app.llm.schemas import FundamentalSnapshot
import structlog

logger = structlog.get_logger(__name__)

BVL_TICKERS_YF = {
    "CREDITC1": "CREDITC1.LM",
    "CVERDEC1": "CVERDEC1.LM",
    "MINSURI1": "MINSURI1.LM",
    "FERREYC1": "FERREYC1.LM",
    "ALICORC1": "ALICORC1.LM",
    "INRETC1":  "INRETC1.LM",
    "VOLCABC1": "VOLCABC1.LM",
    "BACKUSC1": "BACKUSC1.LM",
}

PERU_ADRS = {
    "BAP":  "Credicorp Ltd.",
    "BVN":  "Compañía de Minas Buenaventura",
    "SCCO": "Southern Copper Corporation",
    "IFS":  "Intercorp Financial Services",
}

LATAM_INDICES = {
    "^BVSP": "Bovespa (Brasil)",
    "^MXX":  "IPC (México)",
    "^IPSA": "IPSA (Chile)",
    "^MERV": "Merval (Argentina)",
}

SMV_WSDL = "https://mvnet.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx?WSDL"

# Mapa: nemónico local → ticker yfinance
def _resolve_ticker(ticker: str) -> str:
    if ticker in BVL_TICKERS_YF:
        return BVL_TICKERS_YF[ticker]
    return ticker


# Finnhub (fuente de peers para US) no cubre la BVL ni ADRs peruanos, así que
# se usa un agrupamiento sectorial curado a mano entre los tickers soportados.
LATAM_PEER_GROUPS: list[list[str]] = [
    ["BAP", "IFS", "CREDITC1"],                  # Financiero
    ["BVN", "CVERDEC1", "MINSURI1", "VOLCABC1"],  # Minería
    ["ALICORC1", "INRETC1", "BACKUSC1"],          # Consumo / retail
]


async def get_peers(ticker: str, n: int = 5) -> list[str]:
    for group in LATAM_PEER_GROUPS:
        if ticker in group:
            return [t for t in group if t != ticker][:n]
    return []


async def get_price_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    yf_ticker = _resolve_ticker(ticker)

    try:
        df = await _yfinance_latam(yf_ticker, period)
        if df is not None and len(df) > 10:
            # Validar que hay suficientes datos para indicadores técnicos
            _validate_data(df, ticker)
            return df
    except Exception as e:
        logger.warning("yfinance LATAM failed", ticker=ticker, error=str(e))

    # Fallback: si es ADR, ya tiene ticker US-style
    if ticker in PERU_ADRS:
        logger.info("Using ADR as fallback", ticker=ticker)
        from app.data import us_stocks
        return await us_stocks.get_price_history(ticker, period)

    raise RuntimeError(f"All LATAM price sources failed for {ticker}")


async def _yfinance_latam(yf_ticker: str, period: str) -> pd.DataFrame | None:
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


def _validate_data(df: pd.DataFrame, ticker: str) -> None:
    if len(df) < 50:
        logger.warning(
            "Insufficient data for technical indicators",
            ticker=ticker,
            rows=len(df),
            note="Need at least 50 rows for SMA50",
        )


async def get_fundamentals(ticker: str) -> FundamentalSnapshot:
    # Para ADRs peruanos usar el mismo path que US stocks
    if ticker in PERU_ADRS:
        from app.data import us_stocks
        return await us_stocks.get_fundamentals(ticker)

    # Para tickers BVL intentar SMV
    try:
        return await _smv_fundamentals(ticker)
    except Exception as e:
        logger.warning("SMV fundamentals failed", ticker=ticker, error=str(e))

    return FundamentalSnapshot()


async def _smv_fundamentals(ticker: str) -> FundamentalSnapshot:
    """
    Llama al web service SOAP de SMV para obtener fundamentales oficiales peruanos.
    Timeout generoso: SMV puede tardar 10-30 segundos.
    """
    try:
        import zeep
        from zeep.transports import Transport
        import requests as req_sync

        session = req_sync.Session()
        session.timeout = 30

        transport = Transport(session=session, timeout=30, operation_timeout=30)
        loop = asyncio.get_event_loop()

        def _call():
            client = zeep.Client(wsdl=SMV_WSDL, transport=transport)
            # Obtener estado de resultados del último período anual
            result = client.service.obtener_GanciaPerdida(
                ruc="",
                nemonic=ticker,
                periodo="202312",
                tipo_periodo="A",
            )
            return result

        result = await loop.run_in_executor(None, _call)
        if result:
            return _map_smv_response(result)
    except Exception as e:
        logger.debug("SMV SOAP failed", ticker=ticker, error=str(e))

    return FundamentalSnapshot()


def _map_smv_response(result) -> FundamentalSnapshot:
    """
    Maps SMV SOAP GanciaPerdida response to FundamentalSnapshot.
    SMV returns a list of period rows; we compare latest vs prior year.
    Fields documented at: https://mvnet.smv.gob.pe/ws_od_eeff/
    """
    try:
        rows = result if isinstance(result, list) else getattr(result, "GanciaPerdida", []) or []
        if not rows:
            return FundamentalSnapshot()

        def _val(row, key: str) -> float | None:
            v = getattr(row, key, None)
            if v is None:
                v = row.get(key) if isinstance(row, dict) else None
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        # SMV rows ordered latest first; take first two for YoY comparison
        latest = rows[0]
        prior  = rows[1] if len(rows) > 1 else None

        revenue_latest = _val(latest, "VentasNetas") or _val(latest, "IngresosTotales")
        revenue_prior  = _val(prior, "VentasNetas") or _val(prior, "IngresosTotales") if prior else None
        revenue_growth = (
            (revenue_latest - revenue_prior) / abs(revenue_prior)
            if revenue_latest is not None and revenue_prior and revenue_prior != 0
            else None
        )

        net_income_latest = _val(latest, "UtilidadNeta") or _val(latest, "ResultadoNeto")
        net_income_prior  = _val(prior, "UtilidadNeta") or _val(prior, "ResultadoNeto") if prior else None
        earnings_growth = (
            (net_income_latest - net_income_prior) / abs(net_income_prior)
            if net_income_latest is not None and net_income_prior and net_income_prior != 0
            else None
        )

        return FundamentalSnapshot(
            revenue_growth_yoy=revenue_growth,
            earnings_growth_yoy=earnings_growth,
        )
    except Exception:
        return FundamentalSnapshot()


async def get_latam_indices() -> dict[str, dict]:
    results = {}
    for idx_ticker, name in LATAM_INDICES.items():
        try:
            df = await _yfinance_latam(idx_ticker, "3mo")
            if df is not None and not df.empty:
                last_close = float(df["close"].iloc[-1])
                prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else last_close
                results[idx_ticker] = {
                    "name": name,
                    "price": last_close,
                    "change_pct": (last_close - prev_close) / prev_close * 100,
                }
        except Exception as e:
            logger.warning("LATAM index fetch failed", ticker=idx_ticker, error=str(e))
    return results
