"""
institutional_swing_backtest.py - Proxy Swing Backtest Engine
=============================================================
WHAT:   A standalone backtester that replays history bar-by-bar, scores each bar
        with a PROXY of the institutional rules (S1 gate + S2/S4/S5/S6), simulates
        swing trades (ATR stop / R-multiple target / time stop) and reports stats.
WHY:    Before trusting the live framework, we need an objective read on the edge
        of the cash-side SMC + volume rules across many names and many sessions.
IMPACT: This is the "first proxy backtest engine" from the build sheet. It fetches
        OHLCV via yfinance when available and falls back to a clearly-labelled
        SYNTHETIC random-walk series so the engine always runs offline.

Notes / honest limitations:
  * Delivery%, FII/DII, options and participant data are NOT in OHLCV feeds, so
    S6 here uses a volume-only proxy and S3/S7/S9-S17 are intentionally excluded.
  * Treat results as a directional sanity check, not a production P&L.

Usage:
    python institutional_swing_backtest.py --symbols RELIANCE.NS TCS.NS --period 2y
    python institutional_swing_backtest.py --synthetic --bars 600
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

try:
    from . import config, rule_engine_stock as res
except ImportError:
    import config
    import rule_engine_stock as res

try:
    import yfinance as yf
except ImportError:
    yf = None


# =============================================================================
# DATA LOADING (yfinance with synthetic fallback)
# =============================================================================
def load_ohlcv(symbol: str, period: str = "2y") -> pd.DataFrame:
    """Return columns: open, high, low, close, volume (oldest -> newest)."""
    if yf is not None:
        try:
            h = yf.Ticker(symbol).history(period=period, interval="1d")
            if h is not None and not h.empty:
                df = h.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                       "Close": "close", "Volume": "volume"})
                df = df[["open", "high", "low", "close", "volume"]].reset_index(drop=True)
                df.attrs["source"] = "yfinance"
                return df.dropna().reset_index(drop=True)
        except Exception:
            pass
    return synthetic_series(symbol)


def synthetic_series(symbol: str, bars: int = 600, seed: int | None = None) -> pd.DataFrame:
    """Geometric-Brownian-ish OHLCV with mild trend + volume bursts (offline demo)."""
    rng = np.random.default_rng(seed if seed is not None else abs(hash(symbol)) % (2**32))
    drift, vol = 0.0004, 0.014
    rets = rng.normal(drift, vol, bars)
    # inject a few trending regimes so the trend gate has something to bite on
    for start in rng.integers(0, bars - 40, size=4):
        rets[start:start + 30] += rng.choice([-1, 1]) * 0.0015
    close = 1000 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.006, bars)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, bars)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    volume = rng.lognormal(mean=13, sigma=0.4, size=bars).astype(int)
    volume[rng.integers(0, bars, size=20)] *= 3  # whale-ish bursts
    df = pd.DataFrame({"open": open_, "high": high, "low": low,
                       "close": close, "volume": volume})
    df.attrs["source"] = "SYNTHETIC"
    return df


# =============================================================================
# PROXY SCORING (reuses rule_engine_stock on an OHLCV slice)
# =============================================================================
def proxy_score(slice_df: pd.DataFrame) -> dict:
    """Run S1 gate + S2/S4/S5/S6 proxies on the slice; return a small signal dict."""
    s1 = res.score_s1_gate(slice_df)
    direction = s1.get("direction", "LONG") if s1.get("passed") else "LONG"
    s2 = res.score_s2_ob(slice_df, direction)
    s4 = res.score_s4_sweep(slice_df, direction)
    s5 = res.score_s5_bos(slice_df, direction)
    s6 = res.score_s6_volume(slice_df)  # volume-only (no delivery in OHLCV)
    # Proxy conviction over the available proxy rules.
    sub = s2["score"] + s4["score"] + max(0, s5["score"]) + s6["score"]
    sub_max = sum(config.MAX_SCORES[r] for r in ["S2", "S4", "S5", "S6"])
    return {"s1_pass": s1.get("passed", False), "direction": direction,
            "S2": s2["score"], "S4": s4["score"], "S5": s5["score"], "S6": s6["score"],
            "conviction": sub / sub_max if sub_max else 0.0}


# =============================================================================
# TRADE SIMULATION
# =============================================================================
@dataclass
class Trade:
    symbol: str
    entry_i: int
    entry: float
    direction: str
    stop: float
    target: float
    exit_i: int | None = None
    exit: float | None = None
    reason: str = ""
    r_multiple: float = 0.0


@dataclass
class BacktestResult:
    symbol: str
    source: str
    trades: list = field(default_factory=list)

    def stats(self) -> dict:
        closed = [t for t in self.trades if t.exit is not None]
        if not closed:
            return {"symbol": self.symbol, "source": self.source, "trades": 0}
        rs = np.array([t.r_multiple for t in closed])
        wins = rs[rs > 0]
        losses = rs[rs <= 0]
        gross_win = wins.sum()
        gross_loss = -losses.sum()
        equity = np.cumsum(rs)
        peak = np.maximum.accumulate(equity)
        max_dd = float((equity - peak).min()) if len(equity) else 0.0
        return {
            "symbol": self.symbol, "source": self.source,
            "trades": len(closed),
            "win_rate": round(len(wins) / len(closed) * 100, 1),
            "avg_R": round(float(rs.mean()), 2),
            "expectancy_R": round(float(rs.mean()), 2),
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else float("inf"),
            "total_R": round(float(rs.sum()), 2),
            "max_drawdown_R": round(max_dd, 2),
        }


def backtest_symbol(symbol: str, df: pd.DataFrame, *, entry_conviction: float = 0.45,
                    rr: float = 2.0, atr_mult: float = 1.5, max_hold: int = 15,
                    warmup: int = 210) -> BacktestResult:
    """Single-symbol, one-position-at-a-time swing simulation."""
    result = BacktestResult(symbol=symbol, source=df.attrs.get("source", "?"))
    atr_series = res.atr(df["high"], df["low"], df["close"]).bfill()
    open_trade: Trade | None = None

    for i in range(warmup, len(df) - 1):
        bar = df.iloc[i]
        # ---- manage open position ----
        if open_trade is not None:
            hi, lo = df["high"].iloc[i], df["low"].iloc[i]
            exit_price = exit_reason = None
            if open_trade.direction == "LONG":
                if lo <= open_trade.stop:
                    exit_price, exit_reason = open_trade.stop, "stop"
                elif hi >= open_trade.target:
                    exit_price, exit_reason = open_trade.target, "target"
            else:
                if hi >= open_trade.stop:
                    exit_price, exit_reason = open_trade.stop, "stop"
                elif lo <= open_trade.target:
                    exit_price, exit_reason = open_trade.target, "target"
            if exit_price is None and (i - open_trade.entry_i) >= max_hold:
                exit_price, exit_reason = df["close"].iloc[i], "time"
            if exit_price is not None:
                risk = abs(open_trade.entry - open_trade.stop) or 1e-9
                pnl = (exit_price - open_trade.entry) if open_trade.direction == "LONG" \
                    else (open_trade.entry - exit_price)
                open_trade.exit_i, open_trade.exit = i, exit_price
                open_trade.reason, open_trade.r_multiple = exit_reason, round(pnl / risk, 3)
                result.trades.append(open_trade)
                open_trade = None

        # ---- look for a new entry ----
        if open_trade is None:
            sig = proxy_score(df.iloc[:i + 1])
            if sig["s1_pass"] and sig["conviction"] >= entry_conviction:
                entry = df["close"].iloc[i]
                a = float(atr_series.iloc[i]) or entry * 0.01
                if sig["direction"] == "LONG":
                    stop, target = entry - atr_mult * a, entry + atr_mult * a * rr
                else:
                    stop, target = entry + atr_mult * a, entry - atr_mult * a * rr
                open_trade = Trade(symbol, i, entry, sig["direction"], stop, target)
    return result


# =============================================================================
# RUNNER / CLI
# =============================================================================
def run_backtest(symbols: list[str], period: str = "2y", synthetic: bool = False,
                 bars: int = 600, **kw) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        df = synthetic_series(sym, bars) if synthetic else load_ohlcv(sym, period)
        res_bt = backtest_symbol(sym, df, **kw)
        rows.append(res_bt.stats())
    table = pd.DataFrame(rows)
    return table


def _print_table(table: pd.DataFrame) -> None:
    if table.empty:
        print("No results.")
        return
    print("\n=== BACKTEST SUMMARY (proxy S1+S2/S4/S5/S6) ===")
    print(table.to_string(index=False))
    traded = table[table["trades"] > 0]
    if not traded.empty:
        print("\n--- Aggregate (symbols with trades) ---")
        print(f"  symbols traded : {len(traded)}")
        print(f"  avg win-rate   : {traded['win_rate'].mean():.1f}%")
        print(f"  avg expectancy : {traded['expectancy_R'].mean():.2f} R")
        print(f"  total R        : {traded['total_R'].sum():.2f}")
    print("\n(For reference, blueprint Part 8 reports 59% WR on a 56-session framework test.)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Institutional proxy swing backtest")
    ap.add_argument("--symbols", nargs="*", default=["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS"],
                    help="Yahoo tickers (append .NS for NSE)")
    ap.add_argument("--period", default="2y", help="yfinance period (e.g. 1y, 2y, 5y)")
    ap.add_argument("--synthetic", action="store_true", help="force synthetic offline data")
    ap.add_argument("--bars", type=int, default=600, help="synthetic bar count")
    ap.add_argument("--rr", type=float, default=2.0, help="reward:risk target multiple")
    ap.add_argument("--atr-mult", type=float, default=1.5, help="ATR stop multiple")
    ap.add_argument("--max-hold", type=int, default=15, help="max bars to hold")
    ap.add_argument("--conviction", type=float, default=0.45, help="entry conviction threshold")
    args = ap.parse_args()

    table = run_backtest(args.symbols, period=args.period, synthetic=args.synthetic,
                         bars=args.bars, rr=args.rr, atr_mult=args.atr_mult,
                         max_hold=args.max_hold, entry_conviction=args.conviction)
    _print_table(table)


if __name__ == "__main__":
    main()
