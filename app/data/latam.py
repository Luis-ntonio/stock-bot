import asyncio
import json
import httpx
import pandas as pd
from datetime import datetime, timedelta, date
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

# Mapa nemónico local -> RUC (identificador tributario peruano), requerido para
# filtrar la respuesta de SMV (obtener_GanciaPerdida trae TODAS las empresas
# reportantes en un solo payload, sin parámetro de filtro por empresa).
# RUC verificado en vivo contra el WSDL real para ALICORC1; el resto queda
# pendiente de lookup manual (mismo proceso: llamar obtener_GanciaPerdida,
# buscar coincidencia de substring del nombre de la empresa en NombreEmpresa,
# anotar el RUC asociado).
TICKER_TO_RUC: dict[str, str] = {
    "ALICORC1": "20100055237",  # Alicorp S.A.A. — verificado
    # "CREDITC1": None,   # TODO: lookup RUC
    # "CVERDEC1": None,   # TODO: lookup RUC
    # "MINSURI1": None,   # TODO: lookup RUC
    # "FERREYC1": None,   # TODO: lookup RUC
    # "INRETC1":  None,   # TODO: lookup RUC
    # "VOLCABC1": None,   # TODO: lookup RUC
    # "BACKUSC1": None,   # TODO: lookup RUC
}

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
        snapshot = await us_stocks.get_fundamentals(ticker)

        # yfinance frecuentemente no trae debt_to_equity para estos ADRs —
        # completar con Alpha Vantage (verificado en vivo para BAP) solo si
        # hace falta, dado su límite diario muy ajustado (25/día).
        if snapshot.debt_to_equity is None:
            av_data = await _alpha_vantage_fundamentals(ticker)
            if av_data:
                snapshot = snapshot.model_copy(update={
                    k: v for k, v in av_data.items()
                    if getattr(snapshot, k, None) is None and v is not None
                })
        return snapshot

    # Para tickers BVL intentar SMV
    try:
        return await _smv_fundamentals(ticker)
    except Exception as e:
        logger.warning("SMV fundamentals failed", ticker=ticker, error=str(e))

    return FundamentalSnapshot()


ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"


async def _alpha_vantage_fundamentals(ticker: str) -> dict | None:
    """
    Fallback para debt_to_equity en ADRs LATAM cuando yfinance no lo trae
    (caso frecuente para BAP/BVN/SCCO/IFS). Verificado en vivo contra el API
    real — funciona para tickers listados en US (incluye ADRs), no para
    exchanges extranjeros directos (probado y confirmado vacío para .DE).

    Free tier: 25 requests/día compartidos por toda la app — 1 llamada por
    ticker (BALANCE_SHEET). Se usa el mismo mecanismo de exhaustion-flag que
    Gemini para no reintentar todo el día una vez agotada la cuota.
    """
    if not settings.alpha_vantage_key:
        return None

    rl = get_rate_limiter()
    if await rl.is_exhausted("alpha_vantage"):
        return None

    try:
        await rl.acquire("alpha_vantage")
        balance = await _av_call("BALANCE_SHEET", ticker)
        if balance is None:
            return None

        reports = balance.get("annualReports") or []
        if not reports:
            return None

        latest = reports[0]
        liabilities = _av_float(latest.get("totalLiabilities"))
        equity = _av_float(latest.get("totalShareholderEquity"))
        if liabilities is None or not equity:
            return None

        return {"debt_to_equity": liabilities / equity}
    except Exception as e:
        logger.debug("Alpha Vantage fundamentals failed", ticker=ticker, error=str(e))
        return None


async def _av_call(function: str, ticker: str) -> dict | None:
    async with httpx.AsyncClient() as client:
        r = await client.get(ALPHA_VANTAGE_BASE, params={
            "function": function, "symbol": ticker, "apikey": settings.alpha_vantage_key,
        }, timeout=15)
        r.raise_for_status()
        data = r.json()

    if "Information" in data:
        # Mensaje de cuota agotada (free tier: 25 req/día) — no es un error
        # de red, es la respuesta real del API cuando se excede el límite.
        rl = get_rate_limiter()
        await rl.mark_exhausted("alpha_vantage")
        logger.debug("Alpha Vantage quota exhausted for today", message=data["Information"])
        return None

    if not data:
        return None

    return data


def _av_float(v) -> float | None:
    try:
        return float(v) if v not in (None, "None") else None
    except (TypeError, ValueError):
        return None


# Cuenta codes verificados en vivo contra el WSDL real de SMV (obtener_GanciaPerdida)
SMV_CUENTA_REVENUE = "2D01ST"      # "Ingresos de Actividades Ordinarias"
SMV_CUENTA_NET_INCOME = "2D07ST"   # "Ganancia (Pérdida) Neta del Ejercicio"

SMV_CACHE_TTL = timedelta(hours=24)
# Los estados financieros no cambian intradía y el bot corre en cadencia mensual;
# cachear evita re-descargar el payload completo (~5MB/~12k filas, TODAS las
# empresas reportantes) por cada ticker BVL analizado en la misma corrida.
_smv_cache: dict[str, tuple[datetime, list[dict]]] = {}


async def _smv_fundamentals(ticker: str) -> FundamentalSnapshot:
    """
    Llama al web service SOAP de SMV para obtener fundamentales oficiales peruanos.
    Timeout generoso: SMV puede tardar 10-30 segundos.

    obtener_GanciaPerdida(Ejercicio, Periodo, Tipo) devuelve un JSON string con
    el estado de resultados de TODAS las empresas reportantes para ese
    ejercicio/periodo/tipo — no hay parámetro de filtro por empresa en el SOAP.
    Hay que descargar el dataset completo y filtrar client-side por RUC.
    """
    ruc = TICKER_TO_RUC.get(ticker)
    if not ruc:
        logger.debug("No RUC known for ticker, skipping SMV lookup", ticker=ticker)
        return FundamentalSnapshot()

    ejercicio = str(date.today().year - 1)  # filings anuales tienen rezago

    try:
        rows = await _fetch_smv_dataset(ejercicio)
        return _extract_smv_fundamentals(rows, ruc)
    except Exception as e:
        logger.debug("SMV SOAP failed", ticker=ticker, ruc=ruc, error=str(e))
        return FundamentalSnapshot()


async def _fetch_smv_dataset(ejercicio: str) -> list[dict]:
    """Fetch (with in-memory cache) the full SMV annual-individual income
    statement dataset for a given fiscal year, across all reporting companies."""
    cached = _smv_cache.get(ejercicio)
    if cached is not None:
        cached_at, rows = cached
        if datetime.utcnow() - cached_at < SMV_CACHE_TTL:
            return rows

    rl = get_rate_limiter()
    await rl.acquire("smv")

    import zeep
    from zeep.transports import Transport
    import requests as req_sync

    session = req_sync.Session()
    session.timeout = 30
    transport = Transport(session=session, timeout=30, operation_timeout=30)
    loop = asyncio.get_event_loop()

    def _call():
        client = zeep.Client(wsdl=SMV_WSDL, transport=transport)
        return client.service.obtener_GanciaPerdida(
            Ejercicio=ejercicio, Periodo="A", Tipo="I",
        )

    result = await loop.run_in_executor(None, _call)
    rows = json.loads(result) if result else []

    _smv_cache[ejercicio] = (datetime.utcnow(), rows)
    return rows


def _extract_smv_fundamentals(rows: list[dict], ruc: str) -> FundamentalSnapshot:
    """
    Filtra el dataset completo de SMV por RUC y por las cuentas de ingresos y
    utilidad neta, calculando crecimiento YoY desde Monto1 (período actual) vs
    Monto2 (mismo período, año anterior) de cada línea de cuenta.
    """
    try:
        company_rows = [r for r in rows if r.get("RUC") == ruc]
        if not company_rows:
            return FundamentalSnapshot()

        def _growth(cuenta: str) -> float | None:
            row = next((r for r in company_rows if r.get("Cuenta") == cuenta), None)
            if not row:
                return None
            current = row.get("Monto1")
            prior = row.get("Monto2")
            if current is None or prior is None or prior == 0:
                return None
            return (current - prior) / abs(prior)

        return FundamentalSnapshot(
            revenue_growth_yoy=_growth(SMV_CUENTA_REVENUE),
            earnings_growth_yoy=_growth(SMV_CUENTA_NET_INCOME),
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
