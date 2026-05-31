"""
smart_data_fetcher.py - Raw Data Acquisition Layer (Blocks A1-A12)
==================================================================
WHAT:   Downloads every raw input the framework needs (NSE bhavcopies, delivery,
        FII/DII, indices, option-chain, participant OI, F&O bhav, intermarket).
WHY:    A single, fault-tolerant entry point so the rest of the system only ever
        reads clean local CSVs - never the live internet.
IMPACT: Implements the blueprint Part 9 "4-Level Resilience":
            1. CHECK    -> holiday / weekend validation before any request
            2. TRY/EXCEPT -> every download wrapped, never crashes the pipeline
            3. FALLBACK -> step back up to 3 trading days on failure
            4. FLAG     -> append SUCCESS|FAILED|FALLBACK to download_log.csv

Run modes (Block A1):
    python smart_data_fetcher.py --mode daily                # today (or last trading day)
    python smart_data_fetcher.py --mode daily --date 2026-05-27
    python smart_data_fetcher.py --mode historical --days 60 # backfill N sessions
    python smart_data_fetcher.py                             # interactive menu
"""

from __future__ import annotations

import argparse
import io
import os
import time
import zipfile
from datetime import datetime, date, timedelta

import pandas as pd

try:  # package import
    from . import config
except ImportError:  # script / standalone import
    import config

try:
    import requests
except ImportError:  # pragma: no cover - requests is in requirements.txt
    requests = None

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - optional until intermarket needed
    yf = None


# =============================================================================
# BLOCK A2 - NSE ENDPOINTS (centralized)
# WHAT:  All NSE/archive URLs in one dict. {date} tokens filled per request.
# WHY:   NSE changes URL formats periodically - one place to patch.
# IMPACT: Every A4-A11 downloader reads its URL template from here.
# =============================================================================
NSE_BASE = "https://www.nseindia.com"
NSE_ARCHIVE = "https://nsearchives.nseindia.com"

ENDPOINTS = {
    # A4 equity bhavcopy (UDiFF format: token = %Y%m%d)
    "equity_bhav": NSE_ARCHIVE + "/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip",
    # A5 security-wise delivery (token = %d%m%Y)
    "delivery": NSE_ARCHIVE + "/products/content/sec_bhavdata_full_{dmy}.csv",
    # A6 FII/DII cash (JSON API)
    "fii_dii": NSE_BASE + "/api/fiidiiTradeReact",
    # A7 index close values (token = %d%m%Y)
    "index_close": NSE_ARCHIVE + "/content/indices/ind_close_all_{dmy}.csv",
    # A9 option chain (JSON API)
    "option_chain": NSE_BASE + "/api/option-chain-indices?symbol={symbol}",
    # A10 F&O participant-wise OI (token = %d%m%Y)
    "participant_oi": NSE_ARCHIVE + "/content/nsccl/fao_participant_oi_{dmy}.csv",
    # A11 F&O bhavcopy (UDiFF format: token = %Y%m%d)
    "fo_bhav": NSE_ARCHIVE + "/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip",
}

# Browser-like headers - NSE blocks non-browser user agents.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": NSE_BASE + "/",
}

# A12 intermarket symbols (Yahoo Finance tickers) -> see config / blueprint Part 6.
INTERMARKET_SYMBOLS = {
    "BRENT": "BZ=F",      # S16 C1 crude
    "DXY": "DX-Y.NYB",    # S16 C2 dollar index
    "USDINR": "USDINR=X", # S17 C1 rupee
    "GOLD": "GC=F",       # S17 gold (risk-off)
    "SPX": "^GSPC",       # S16 C4 global
    "NIKKEI": "^N225",    # S16 C4 global
    "HSI": "^HSI",        # S16 C4 global
    "IN10Y": "^TNX",      # proxy for yields when IN10Y unavailable
}


# =============================================================================
# BLOCK A3 - CALENDAR / HOLIDAY VALIDATION + FALLBACK
# WHAT:  is_trading_day(), last_trading_day(), fallback walker.
# WHY:   Requesting a holiday/weekend file = guaranteed 404 -> wasted retries.
# IMPACT: Drives the resilience layer; fallback steps back up to 3 sessions.
# =============================================================================
def is_trading_day(d: date) -> bool:
    """True only for Mon-Fri that is not an NSE holiday."""
    if d.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    return d.isoformat() not in config.NSE_HOLIDAYS


def last_trading_day(ref: date | None = None) -> date:
    """Most recent trading day on or before `ref` (defaults to today)."""
    d = ref or date.today()
    for _ in range(10):  # safety bound
        if is_trading_day(d):
            return d
        d -= timedelta(days=1)
    return d


def previous_trading_day(d: date) -> date:
    """The trading day strictly before `d`."""
    p = d - timedelta(days=1)
    while not is_trading_day(p):
        p -= timedelta(days=1)
    return p


def trading_days_back(end: date, n: int) -> list[date]:
    """List of the last `n` trading days ending at/<= `end`, oldest first."""
    out, d = [], last_trading_day(end)
    while len(out) < n:
        if is_trading_day(d):
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


# =============================================================================
# BLOCK A8 - FILE MANAGEMENT + DOWNLOAD LOG
# WHAT:  Path builders, CSV savers, and the download_log.csv writer.
# WHY:   Consistent naming (source_YYYY-MM-DD.csv) so data_fetcher can find files.
# IMPACT: download_log.csv is the audit trail for data-quality flags downstream.
# =============================================================================
def _dest_path(folder: str, source: str, d: date) -> str:
    config.ensure_directories()
    return os.path.join(folder, f"{source}_{d.isoformat()}.csv")


def _log_download(trading_date: date, source: str, status: str,
                  error: str = "", fallback_date: str = "") -> None:
    """Append one row to output/logs/download_log.csv (blueprint Part 9)."""
    config.ensure_directories()
    path = os.path.join(config.LOGS_DIR, "download_log.csv")
    row = {
        "timestamp_ist": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trading_date": trading_date.isoformat(),
        "source": source,
        "status": status,            # SUCCESS | FAILED | FALLBACK
        "error": error[:300],
        "fallback_date": fallback_date,
    }
    header = not os.path.exists(path)
    pd.DataFrame([row]).to_csv(path, mode="a", header=header, index=False)


def _save_csv(df: pd.DataFrame, folder: str, source: str, d: date) -> str:
    path = _dest_path(folder, source, d)
    df.to_csv(path, index=False)
    return path


# --- Shared HTTP session (warms cookies on the NSE home page) ----------------
_session = None


def _get_session():
    """Lazily build a requests.Session pre-loaded with NSE cookies."""
    global _session
    if requests is None:
        raise RuntimeError("`requests` not installed - run pip install -r requirements.txt")
    if _session is None:
        s = requests.Session()
        s.headers.update(_HEADERS)
        try:
            s.get(NSE_BASE, timeout=10)  # seed cookies
            time.sleep(0.5)
        except Exception:
            pass  # proceed; individual calls will retry/fallback
        _session = s
    return _session


def _http_get(url: str, timeout: int = 20, expect_json: bool = False):
    s = _get_session()
    r = s.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json() if expect_json else r.content


# =============================================================================
# Generic resilient runner used by every A-block downloader.
# Implements TRY/EXCEPT + FALLBACK + FLAG in one place.
# =============================================================================
def _resilient(source: str, folder: str, target: date, parse_fn,
               max_fallback: int = 3) -> dict:
    """
    parse_fn(d: date) -> pd.DataFrame  (raises on failure / empty).
    Steps back up to `max_fallback` trading days, logging each attempt.
    Returns a small result dict for the pipeline's data-quality map.
    """
    attempt_date = last_trading_day(target)
    first = attempt_date
    for i in range(max_fallback + 1):
        try:
            df = parse_fn(attempt_date)
            if df is None or len(df) == 0:
                raise ValueError("empty dataframe")
            path = _save_csv(df, folder, source, target)
            status = "SUCCESS" if attempt_date == first else "FALLBACK"
            _log_download(target, source, status,
                          fallback_date=("" if status == "SUCCESS" else attempt_date.isoformat()))
            return {"source": source, "status": status, "rows": len(df),
                    "used_date": attempt_date.isoformat(), "path": path}
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline
            if i == max_fallback:
                _log_download(target, source, "FAILED", error=str(exc))
                return {"source": source, "status": "FAILED", "rows": 0,
                        "used_date": None, "error": str(exc)}
            attempt_date = previous_trading_day(attempt_date)
    return {"source": source, "status": "FAILED", "rows": 0, "used_date": None}


def _read_zip_csv(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            return pd.read_csv(fh)


# =============================================================================
# BLOCK A4 - EQUITY BHAVCOPY  (feeds S1-S6)
# =============================================================================
def fetch_equity_bhav(target: date) -> dict:
    def parse(d: date) -> pd.DataFrame:
        url = ENDPOINTS["equity_bhav"].format(ymd=d.strftime("%Y%m%d"))
        return _read_zip_csv(_http_get(url))
    return _resilient("equity", config.EQUITY_DIR, target, parse)


# =============================================================================
# BLOCK A5 - SECURITY-WISE DELIVERY  (feeds S6 delivery%)
# =============================================================================
def fetch_delivery(target: date) -> dict:
    def parse(d: date) -> pd.DataFrame:
        url = ENDPOINTS["delivery"].format(dmy=d.strftime("%d%m%Y"))
        df = pd.read_csv(io.BytesIO(_http_get(url)))
        df.columns = [c.strip() for c in df.columns]
        return df
    return _resilient("delivery", config.DELIVERY_DIR, target, parse)


# =============================================================================
# BLOCK A6 - FII / DII CASH  (feeds S7)
# =============================================================================
def fetch_fii_dii(target: date) -> dict:
    def parse(d: date) -> pd.DataFrame:
        data = _http_get(ENDPOINTS["fii_dii"], expect_json=True)
        return pd.DataFrame(data)
    # FII/DII API only returns latest two rows; no per-date fallback needed.
    return _resilient("fii_dii", config.FII_DIR, target, parse, max_fallback=0)


# =============================================================================
# BLOCK A7 - INDEX CLOSE VALUES  (feeds S10 breadth + N-rules + S8 sectors)
# =============================================================================
def fetch_indices(target: date) -> dict:
    def parse(d: date) -> pd.DataFrame:
        url = ENDPOINTS["index_close"].format(dmy=d.strftime("%d%m%Y"))
        return pd.read_csv(io.BytesIO(_http_get(url)))
    return _resilient("indices", config.INDEX_DIR, target, parse)


# =============================================================================
# BLOCK A9 - OPTION CHAIN  (feeds S12)
# =============================================================================
def fetch_option_chain(target: date, symbol: str = "NIFTY") -> dict:
    def parse(d: date) -> pd.DataFrame:
        url = ENDPOINTS["option_chain"].format(symbol=symbol)
        data = _http_get(url, expect_json=True)
        records = data.get("records", {}).get("data", [])
        rows = []
        for rec in records:
            strike = rec.get("strikePrice")
            expiry = rec.get("expiryDate")
            for side in ("CE", "PE"):
                leg = rec.get(side)
                if leg:
                    rows.append({
                        "strikePrice": strike, "expiryDate": expiry, "type": side,
                        "openInterest": leg.get("openInterest", 0),
                        "changeinOpenInterest": leg.get("changeinOpenInterest", 0),
                        "impliedVolatility": leg.get("impliedVolatility", 0),
                        "lastPrice": leg.get("lastPrice", 0),
                        "underlyingValue": leg.get("underlyingValue", 0),
                    })
        return pd.DataFrame(rows)
    return _resilient(f"options_{symbol}", config.OPTIONS_DIR, target, parse, max_fallback=0)


# =============================================================================
# BLOCK A10 - F&O PARTICIPANT-WISE OI  (feeds S15 - SHADOW)
# =============================================================================
def fetch_participant_oi(target: date) -> dict:
    def parse(d: date) -> pd.DataFrame:
        url = ENDPOINTS["participant_oi"].format(dmy=d.strftime("%d%m%Y"))
        # File has a 1-line title above the real header.
        return pd.read_csv(io.BytesIO(_http_get(url)), skiprows=1)
    return _resilient("participant_oi", config.PARTICIPANT_DIR, target, parse)


# =============================================================================
# BLOCK A11 - F&O BHAVCOPY  (feeds S14 futures basis / rollover)
# =============================================================================
def fetch_fo_bhav(target: date) -> dict:
    def parse(d: date) -> pd.DataFrame:
        url = ENDPOINTS["fo_bhav"].format(ymd=d.strftime("%Y%m%d"))
        return _read_zip_csv(_http_get(url))
    return _resilient("futures", config.FUTURES_DIR, target, parse)


# =============================================================================
# BLOCK A12 - INTERMARKET (Yahoo Finance)  (feeds S16 + S17)
# WHAT:  Crude / DXY / USDINR / Gold / global indices + yield proxy.
# WHY:   Macro modifiers (S16/S17) need cross-asset context.
# IMPACT: Writes one tidy CSV (intermarket_<date>.csv) with ~3 months history.
# =============================================================================
def fetch_intermarket(target: date, period: str = "3mo") -> dict:
    config.ensure_directories()
    if yf is None:
        _log_download(target, "intermarket", "FAILED", error="yfinance not installed")
        return {"source": "intermarket", "status": "FAILED", "rows": 0}
    frames = []
    for name, ticker in INTERMARKET_SYMBOLS.items():
        try:
            hist = yf.Ticker(ticker).history(period=period, interval="1d")
            if hist is None or hist.empty:
                continue
            tmp = hist[["Close"]].rename(columns={"Close": name}).reset_index()
            tmp["Date"] = pd.to_datetime(tmp["Date"]).dt.tz_localize(None).dt.date
            frames.append(tmp.set_index("Date"))
        except Exception:
            continue
    if not frames:
        _log_download(target, "intermarket", "FAILED", error="all tickers failed")
        return {"source": "intermarket", "status": "FAILED", "rows": 0}
    merged = pd.concat(frames, axis=1).sort_index().reset_index()
    path = _save_csv(merged, config.INTERMARKET_DIR, "intermarket", target)
    _log_download(target, "intermarket", "SUCCESS")
    return {"source": "intermarket", "status": "SUCCESS", "rows": len(merged), "path": path}


# =============================================================================
# Orchestration helpers
# =============================================================================
ALL_FETCHERS = {
    "equity": fetch_equity_bhav,
    "delivery": fetch_delivery,
    "fii_dii": fetch_fii_dii,
    "indices": fetch_indices,
    "options": fetch_option_chain,
    "participant_oi": fetch_participant_oi,
    "futures": fetch_fo_bhav,
    "intermarket": fetch_intermarket,
}


def download_all(target: date, sources: list[str] | None = None) -> dict:
    """Run every (or a subset of) downloader for one trading date. Returns a report."""
    sources = sources or list(ALL_FETCHERS.keys())
    report = {}
    for src in sources:
        fn = ALL_FETCHERS.get(src)
        if fn is None:
            continue
        report[src] = fn(target)
        time.sleep(0.4)  # be polite to NSE
    return report


def download_historical(end: date, days: int) -> dict:
    """Backfill `days` trading sessions (daily bhav/delivery/index/F&O)."""
    daily_sources = ["equity", "delivery", "indices", "futures", "participant_oi"]
    report = {}
    for d in trading_days_back(end, days):
        report[d.isoformat()] = download_all(d, daily_sources)
    # Intermarket is range-based; fetch once with a long window.
    report["intermarket"] = fetch_intermarket(end, period="6mo")
    return report


# =============================================================================
# BLOCK A1 - CLI / INTERACTIVE MENU
# WHAT:  argparse front-end + a simple interactive fallback menu.
# WHY:   One command runs daily downloads; another backfills history.
# IMPACT: Entry point when this file is executed directly.
# =============================================================================
def _interactive_menu() -> None:
    print("\n=== Smart Data Fetcher (A1) ===")
    print("1) Daily download (last trading day)")
    print("2) Historical backfill")
    print("3) Single source (daily)")
    choice = input("Select [1-3]: ").strip()
    today = date.today()
    if choice == "2":
        n = int(input("How many sessions? ").strip() or "60")
        _print_report(download_historical(today, n))
    elif choice == "3":
        print("Sources:", ", ".join(ALL_FETCHERS))
        src = input("Source: ").strip()
        _print_report({src: ALL_FETCHERS[src](last_trading_day(today))})
    else:
        _print_report(download_all(last_trading_day(today)))


def _print_report(report: dict) -> None:
    print("\n--- Download report ---")
    for k, v in report.items():
        print(f"{k:>14}: {v}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Smart Data Fetcher (A1-A12)")
    ap.add_argument("--mode", choices=["daily", "historical"], help="run mode")
    ap.add_argument("--date", help="trading date YYYY-MM-DD (daily mode)")
    ap.add_argument("--days", type=int, default=60, help="sessions to backfill")
    ap.add_argument("--source", help="single source name (daily mode)")
    args = ap.parse_args()

    if not args.mode:
        _interactive_menu()
        return

    target = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    if args.mode == "historical":
        _print_report(download_historical(target, args.days))
    else:
        if args.source:
            _print_report({args.source: ALL_FETCHERS[args.source](last_trading_day(target))})
        else:
            _print_report(download_all(last_trading_day(target)))


if __name__ == "__main__":
    main()
