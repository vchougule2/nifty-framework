"""
data_fetcher.py - Clean Load Layer (Blocks C1-C10)
==================================================
WHAT:   Reads the raw CSVs written by smart_data_fetcher and returns tidy,
        column-standardized pandas DataFrames - selecting ONLY the columns the
        rules actually use.
WHY:    The rule engines must never know NSE's messy / changing column names.
        One translation layer = one place to fix when a format changes.
IMPACT: Every loader degrades gracefully (returns empty DF / None) and never
        raises, so a missing source becomes a data-quality flag (Part 9), not a crash.

Standard column vocabulary used downstream:
    OHLCV   : symbol, date, open, high, low, close, volume, value, trades
    delivery: symbol, deliv_qty, deliv_pct
    fii_dii : date, fii_net, dii_net, fii_gross_buy, fii_gross_sell
    options : strikePrice, expiryDate, type, openInterest, changeinOpenInterest,
              impliedVolatility, lastPrice, underlyingValue
"""

from __future__ import annotations

import glob
import os
from datetime import date

import numpy as np
import pandas as pd

try:
    from . import config
except ImportError:
    import config


# --- column-name resolver (handles legacy + UDiFF NSE formats) ---------------
def _pick(df: pd.DataFrame, *candidates: str):
    """Return the first column present in df from `candidates`, else None."""
    cols = {c.strip().upper(): c for c in df.columns}
    for cand in candidates:
        if cand.strip().upper() in cols:
            return cols[cand.strip().upper()]
    return None


def _latest_csv(folder: str, source: str, on: date | None = None) -> str | None:
    """Newest `<source>_*.csv` in folder, or the exact-date file if `on` given."""
    if on is not None:
        exact = os.path.join(folder, f"{source}_{on.isoformat()}.csv")
        if os.path.exists(exact):
            return exact
    matches = sorted(glob.glob(os.path.join(folder, f"{source}_*.csv")))
    return matches[-1] if matches else None


def _empty(*cols: str) -> pd.DataFrame:
    return pd.DataFrame(columns=list(cols))


# =============================================================================
# BLOCK C1 - LOAD EQUITY BHAVCOPY  -> standardized OHLCV
# =============================================================================
def load_equity(on: date | None = None) -> pd.DataFrame:
    path = _latest_csv(config.EQUITY_DIR, "equity", on)
    if not path:
        return _empty("symbol", "open", "high", "low", "close", "volume", "value", "trades")
    try:
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        out = pd.DataFrame({
            "symbol": df[_pick(df, "TckrSymb", "SYMBOL", "Symbol")].astype(str).str.strip(),
            "series": df[_pick(df, "SctySrs", "SERIES", "Series")] if _pick(df, "SctySrs", "SERIES", "Series") else "EQ",
            "open":  pd.to_numeric(df[_pick(df, "OpnPric", "OPEN", "Open")], errors="coerce"),
            "high":  pd.to_numeric(df[_pick(df, "HghPric", "HIGH", "High")], errors="coerce"),
            "low":   pd.to_numeric(df[_pick(df, "LwPric", "LOW", "Low")], errors="coerce"),
            "close": pd.to_numeric(df[_pick(df, "ClsPric", "CLOSE", "Close")], errors="coerce"),
            "volume": pd.to_numeric(df[_pick(df, "TtlTradgVol", "TOTTRDQTY", "Volume")], errors="coerce"),
            "value": pd.to_numeric(df[_pick(df, "TtlTrfVal", "TOTTRDVAL")], errors="coerce")
                     if _pick(df, "TtlTrfVal", "TOTTRDVAL") else np.nan,
            "trades": pd.to_numeric(df[_pick(df, "TtlNbOfTxsExctd", "TOTALTRADES")], errors="coerce")
                      if _pick(df, "TtlNbOfTxsExctd", "TOTALTRADES") else np.nan,
        })
        # Keep cash-segment equity only when a series column exists.
        if "series" in out and out["series"].notna().any():
            out = out[out["series"].astype(str).str.upper().isin(["EQ", "BE", ""])]
        return out.dropna(subset=["close"]).reset_index(drop=True)
    except Exception:
        return _empty("symbol", "open", "high", "low", "close", "volume", "value", "trades")


# =============================================================================
# BLOCK C2 - LOAD DELIVERY  -> symbol, deliv_qty, deliv_pct
# =============================================================================
def load_delivery(on: date | None = None) -> pd.DataFrame:
    path = _latest_csv(config.DELIVERY_DIR, "delivery", on)
    if not path:
        return _empty("symbol", "deliv_qty", "deliv_pct")
    try:
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        out = pd.DataFrame({
            "symbol": df[_pick(df, "SYMBOL", "TckrSymb")].astype(str).str.strip(),
            "deliv_qty": pd.to_numeric(df[_pick(df, "DELIV_QTY", "DelivQty")], errors="coerce"),
            "deliv_pct": pd.to_numeric(df[_pick(df, "DELIV_PER", "DelivPer")], errors="coerce"),
        })
        return out.dropna(subset=["symbol"]).reset_index(drop=True)
    except Exception:
        return _empty("symbol", "deliv_qty", "deliv_pct")


# =============================================================================
# BLOCK C3 - LOAD FII / DII CASH  -> net flows in Rs Cr
# =============================================================================
def load_fii_dii(on: date | None = None) -> pd.DataFrame:
    path = _latest_csv(config.FII_DIR, "fii_dii", on)
    if not path:
        return _empty("category", "date", "buy", "sell", "net")
    try:
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        cat = _pick(df, "category", "Category")
        buy = _pick(df, "buyValue", "buy_value", "Buy")
        sell = _pick(df, "sellValue", "sell_value", "Sell")
        net = _pick(df, "netValue", "net_value", "Net")
        out = pd.DataFrame({
            "category": df[cat].astype(str) if cat else "",
            "buy": pd.to_numeric(df[buy], errors="coerce") if buy else np.nan,
            "sell": pd.to_numeric(df[sell], errors="coerce") if sell else np.nan,
            "net": pd.to_numeric(df[net], errors="coerce") if net else np.nan,
        })
        return out
    except Exception:
        return _empty("category", "buy", "sell", "net")


# =============================================================================
# BLOCK C4 - LOAD INDEX CLOSE  -> index name + close + pct change
# =============================================================================
def load_indices(on: date | None = None) -> pd.DataFrame:
    path = _latest_csv(config.INDEX_DIR, "indices", on)
    if not path:
        return _empty("index_name", "close", "pct_change")
    try:
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        out = pd.DataFrame({
            "index_name": df[_pick(df, "Index Name", "IndexName", "index_name")].astype(str).str.strip(),
            "close": pd.to_numeric(df[_pick(df, "Closing Index Value", "Close", "closing_index_value")], errors="coerce"),
            "pct_change": pd.to_numeric(df[_pick(df, "Change(%)", "Pct Change", "change_pct")], errors="coerce")
                          if _pick(df, "Change(%)", "Pct Change", "change_pct") else np.nan,
        })
        return out.dropna(subset=["index_name"]).reset_index(drop=True)
    except Exception:
        return _empty("index_name", "close", "pct_change")


# =============================================================================
# BLOCK C5 - LOAD SECTORAL INDICES  (subset of C4) -> feeds S8 (SHADOW)
# =============================================================================
def load_sectoral(on: date | None = None) -> pd.DataFrame:
    idx = load_indices(on)
    if idx.empty:
        return idx
    mask = idx["index_name"].str.upper().str.startswith("NIFTY") & \
        idx["index_name"].str.upper().str.contains(
            "BANK|IT|AUTO|PHARMA|FMCG|METAL|REALTY|ENERGY|FIN|MEDIA|PSU|CONSUMER|INFRA")
    return idx[mask].reset_index(drop=True)


# =============================================================================
# BLOCK C6 - MERGE + STOCK HISTORY BUILDER
# WHAT:  (a) merge one day's equity + delivery; (b) stitch N daily bhavcopies
#        into a per-symbol OHLCV history (required by S1-S6 indicators).
# WHY:   Rules need trend/volume history, not a single snapshot.
# IMPACT: build_stock_history() is the main feed into rule_engine_stock.
# =============================================================================
def merge_equity_delivery(on: date | None = None) -> pd.DataFrame:
    eq = load_equity(on)
    dl = load_delivery(on)
    if eq.empty:
        return eq
    if dl.empty:
        eq["deliv_pct"] = np.nan
        eq["deliv_qty"] = np.nan
        return eq
    return eq.merge(dl, on="symbol", how="left")


def build_stock_history(symbol: str, lookback: int = 150) -> pd.DataFrame:
    """
    Concatenate the most recent `lookback` daily equity files into one OHLCV
    series for `symbol`, oldest->newest. Returns columns:
    date, open, high, low, close, volume, value, trades, deliv_pct, deliv_qty.
    """
    eq_files = sorted(glob.glob(os.path.join(config.EQUITY_DIR, "equity_*.csv")))[-lookback:]
    rows = []
    for f in eq_files:
        d = os.path.basename(f).replace("equity_", "").replace(".csv", "")
        try:
            day = load_equity(date.fromisoformat(d))
            row = day[day["symbol"].str.upper() == symbol.upper()]
            if row.empty:
                continue
            r = row.iloc[0].to_dict()
            r["date"] = d
            # attach delivery if present for that date
            dl = load_delivery(date.fromisoformat(d))
            if not dl.empty:
                drow = dl[dl["symbol"].str.upper() == symbol.upper()]
                if not drow.empty:
                    r["deliv_pct"] = drow.iloc[0]["deliv_pct"]
                    r["deliv_qty"] = drow.iloc[0]["deliv_qty"]
            rows.append(r)
        except Exception:
            continue
    if not rows:
        return _empty("date", "open", "high", "low", "close", "volume",
                      "value", "trades", "deliv_pct", "deliv_qty")
    hist = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return hist


# =============================================================================
# BLOCK C7 - VALIDATE / DATA-QUALITY FLAGS
# WHAT:  Quick health check of a loaded frame.
# WHY:   Feeds the adjusted-scoring denominator (Part 9): missing -> exclude rule.
# IMPACT: Returns {"ok": bool, "rows": int, "issues": [...]}.
# =============================================================================
def validate(df: pd.DataFrame, required: list[str] | None = None,
             min_rows: int = 1) -> dict:
    issues = []
    if df is None or len(df) < min_rows:
        issues.append("empty_or_too_few_rows")
    if required:
        missing = [c for c in required if c not in (df.columns if df is not None else [])]
        if missing:
            issues.append(f"missing_cols:{missing}")
    if df is not None and not df.empty:
        null_ratio = float(df.isna().mean().mean())
        if null_ratio > 0.5:
            issues.append(f"high_nulls:{null_ratio:.2f}")
    return {"ok": len(issues) == 0, "rows": 0 if df is None else len(df), "issues": issues}


# =============================================================================
# BLOCK C8 - LOAD OPTION CHAIN  -> feeds S12
# =============================================================================
def load_option_chain(symbol: str = "NIFTY", on: date | None = None) -> pd.DataFrame:
    path = _latest_csv(config.OPTIONS_DIR, f"options_{symbol}", on)
    if not path:
        return _empty("strikePrice", "expiryDate", "type", "openInterest",
                      "changeinOpenInterest", "impliedVolatility", "lastPrice", "underlyingValue")
    try:
        df = pd.read_csv(path)
        for col in ["openInterest", "changeinOpenInterest", "impliedVolatility",
                    "lastPrice", "underlyingValue", "strikePrice"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception:
        return _empty("strikePrice", "expiryDate", "type", "openInterest",
                      "changeinOpenInterest", "impliedVolatility", "lastPrice", "underlyingValue")


# =============================================================================
# BLOCK C9 - LOAD PARTICIPANT-WISE OI  -> feeds S15 (SHADOW)
# =============================================================================
def load_participant_oi(on: date | None = None) -> pd.DataFrame:
    path = _latest_csv(config.PARTICIPANT_DIR, "participant_oi", on)
    if not path:
        return _empty("client_type", "future_index_long", "future_index_short",
                      "option_index_call_long", "option_index_put_long")
    try:
        df = pd.read_csv(path)
        df.columns = [c.strip() for c in df.columns]
        rename = {
            _pick(df, "Client Type", "client_type"): "client_type",
            _pick(df, "Future Index Long", "future_index_long"): "future_index_long",
            _pick(df, "Future Index Short", "future_index_short"): "future_index_short",
            _pick(df, "Option Index Call Long", "option_index_call_long"): "option_index_call_long",
            _pick(df, "Option Index Put Long", "option_index_put_long"): "option_index_put_long",
            _pick(df, "Option Index Call Short", "option_index_call_short"): "option_index_call_short",
            _pick(df, "Option Index Put Short", "option_index_put_short"): "option_index_put_short",
        }
        rename = {k: v for k, v in rename.items() if k}
        return df.rename(columns=rename)
    except Exception:
        return _empty("client_type", "future_index_long", "future_index_short")


# =============================================================================
# BLOCK C10 - LOAD INTERMARKET  -> feeds S16 + S17
# =============================================================================
def load_intermarket(on: date | None = None) -> pd.DataFrame:
    path = _latest_csv(config.INTERMARKET_DIR, "intermarket", on)
    if not path:
        return _empty("Date", *INTERMARKET_COLS)
    try:
        df = pd.read_csv(path)
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        return df.sort_values("Date").reset_index(drop=True) if "Date" in df.columns else df
    except Exception:
        return _empty("Date", *INTERMARKET_COLS)


INTERMARKET_COLS = ["BRENT", "DXY", "USDINR", "GOLD", "SPX", "NIKKEI", "HSI", "IN10Y"]


# =============================================================================
# Convenience: load everything needed for one trading date into one bundle.
# =============================================================================
def load_bundle(on: date | None = None) -> dict:
    """Single call used by main_pipeline H3 to assemble all inputs + quality map."""
    bundle = {
        "equity": merge_equity_delivery(on),
        "fii_dii": load_fii_dii(on),
        "indices": load_indices(on),
        "sectoral": load_sectoral(on),
        "options": load_option_chain("NIFTY", on),
        "participant_oi": load_participant_oi(on),
        "intermarket": load_intermarket(on),
    }
    bundle["_quality"] = {k: validate(v) for k, v in bundle.items()}
    return bundle
