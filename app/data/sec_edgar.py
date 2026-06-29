import asyncio
from app.config import settings
from app.data.rate_limiter import get_rate_limiter
import structlog

logger = structlog.get_logger(__name__)

_identity_set = False


def _ensure_identity():
    global _identity_set
    if not _identity_set:
        from edgar import set_identity
        name = settings.sec_identity_name
        email = settings.sec_identity_email
        if not email:
            email = "stockbot@example.com"
        set_identity(f"{name} {email}")
        _identity_set = True


async def get_filing_text(ticker: str, form_type: str = "10-K") -> str:
    rl = get_rate_limiter()
    await rl.acquire("sec_edgar")

    loop = asyncio.get_event_loop()

    def _fetch():
        _ensure_identity()
        from edgar import Company
        company = Company(ticker)
        filings = company.get_filings(form=form_type)
        if not filings:
            raise ValueError(f"No {form_type} found for {ticker}")

        filing = filings.latest(1)
        doc = filing.obj()

        # Extraer solo secciones clave para no enviar 200 páginas al LLM
        sections = []
        for item in ["Item 1", "Item 1A", "Item 7"]:
            section = doc.sections.get(item)
            if section:
                text = getattr(section, "text", str(section))
                sections.append(f"=== {item} ===\n{text}")

        if sections:
            return "\n\n".join(sections)

        # Fallback: texto completo truncado
        full_text = str(doc)
        return full_text[:50_000]

    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        logger.error("SEC EDGAR fetch failed", ticker=ticker, form=form_type, error=str(e))
        raise


async def get_company_facts(ticker: str) -> dict:
    """Descarga CompanyFacts XBRL directamente desde data.sec.gov."""
    import httpx

    rl = get_rate_limiter()
    await rl.acquire("sec_edgar")

    # Primero resolver CIK
    async with httpx.AsyncClient(
        headers={"User-Agent": f"{settings.sec_identity_name} {settings.sec_identity_email}"}
    ) as client:
        r = await client.get("https://www.sec.gov/files/company_tickers.json", timeout=15)
        r.raise_for_status()
        tickers_map = r.json()

    cik = None
    for entry in tickers_map.values():
        if entry.get("ticker", "").upper() == ticker.upper():
            cik = str(entry["cik_str"]).zfill(10)
            break

    if not cik:
        raise ValueError(f"CIK not found for {ticker}")

    async with httpx.AsyncClient(
        headers={"User-Agent": f"{settings.sec_identity_name} {settings.sec_identity_email}"}
    ) as client:
        r = await client.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
