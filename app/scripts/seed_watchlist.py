"""Poblar la base de datos con el watchlist inicial de prueba."""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from app.db.session import SyncSessionLocal as SessionLocal
from app.db.crud import get_or_create_company

INITIAL_WATCHLIST = {
    "US": [
        ("AAPL",  "Apple Inc.",              "Technology",    "Consumer Electronics"),
        ("MSFT",  "Microsoft Corporation",   "Technology",    "Software"),
        ("NVDA",  "NVIDIA Corporation",      "Technology",    "Semiconductors"),
        ("JPM",   "JPMorgan Chase & Co.",    "Financials",    "Banks"),
        ("BAC",   "Bank of America Corp.",   "Financials",    "Banks"),
        ("XOM",   "Exxon Mobil Corp.",       "Energy",        "Integrated Oil & Gas"),
        ("CVX",   "Chevron Corporation",     "Energy",        "Integrated Oil & Gas"),
    ],
    "CRYPTO": [
        ("BTC",   "Bitcoin",                 None, None),
        ("ETH",   "Ethereum",                None, None),
        ("SOL",   "Solana",                  None, None),
    ],
    "LATAM": [
        ("BAP",       "Credicorp Ltd.",              "Financials", "Banks"),
        ("SCCO",      "Southern Copper Corp.",       "Materials",  "Copper"),
        ("PETR4.SA",  "Petrobras (Brasil)",          "Energy",     "Integrated Oil & Gas"),
    ],
}


def seed():
    db = SessionLocal()
    total = 0
    try:
        for market, tickers in INITIAL_WATCHLIST.items():
            for ticker, name, sector, industry in tickers:
                company = get_or_create_company(
                    db, ticker=ticker, name=name, market=market,
                    sector=sector, industry=industry,
                )
                print(f"  OK {ticker} ({market})")
                total += 1
    finally:
        db.close()
    print(f"\nSeeded {total} tickers.")


if __name__ == "__main__":
    seed()
