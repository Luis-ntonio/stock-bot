from fastapi import APIRouter, HTTPException, Query
from app.data.us_stocks import get_price_history as get_us_price_history
from app.data.crypto import get_price_history as get_crypto_price_history
import structlog

router = APIRouter(prefix="/price", tags=["price"])
logger = structlog.get_logger(__name__)


@router.get("/{ticker}/ohlc")
async def get_ohlc(
    ticker: str,
    period: str = Query("6mo", pattern="^(1mo|3mo|6mo|1y|2y)$"),
    market: str = Query("US", pattern="^(US|CRYPTO|LATAM)$"),
):
    ticker = ticker.upper()
    try:
        if market == "CRYPTO":
            df = await get_crypto_price_history(ticker, period)
        else:
            df = await get_us_price_history(ticker, period=period, interval="1d")

        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="No price data found")

        df = df.reset_index()
        date_col = "date" if "date" in df.columns else df.columns[0]
        df[date_col] = df[date_col].astype(str)

        cols = [date_col, "open", "high", "low", "close", "volume"]
        optional = ["SMA_50", "SMA_200", "BBU_20_2.0", "BBM_20_2.0", "BBL_20_2.0", "RSI_14"]
        cols += [c for c in optional if c in df.columns]

        return df[cols].where(df[cols].notna(), other=None).to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("OHLC fetch failed", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
