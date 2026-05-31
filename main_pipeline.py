"""
main_pipeline.py - Daily Orchestrator (Blocks H1-H9)
====================================================
WHAT:   The single entry point that runs the whole day end-to-end.
WHY:    One command -> data -> scores -> decisions -> charts -> alerts -> ML store.
IMPACT: Implements the blueprint daily pipeline:
        H1 Init -> H2 Download(A) -> H3 Load(C) -> H4 Score S1-S11(D)
        -> H7 Score S12-S15(J) -> H8 Score S16-S18(K) -> H9 PRECEDENCE ENGINE
        -> H5 Charts(F) -> H6 Alerts(G) -> ML1 Collect.

Usage:
    python main_pipeline.py --date 2026-05-27
    python main_pipeline.py --date 2026-05-27 --no-download   # use local CSVs
    python main_pipeline.py --watchlist RELIANCE TCS BHEL
"""

from __future__ import annotations

import argparse
import json
import os
import traceback
from datetime import datetime, date

import numpy as np
import pandas as pd

try:
    from . import (config, smart_data_fetcher as sdf, data_fetcher as dfetch,
                   rule_engine_stock as res, rule_engine_options as reo,
                   rule_engine_macro as rem, chart_generator as cg, alerts)
    from .ml import ml_optimizer
except ImportError:
    import config
    import smart_data_fetcher as sdf
    import data_fetcher as dfetch
    import rule_engine_stock as res
    import rule_engine_options as reo
    import rule_engine_macro as rem
    import chart_generator as cg
    import alerts
    from ml import ml_optimizer


# =============================================================================
# BLOCK H1 - INIT
# WHAT: Ensure directory tree + resolve the trading date. WHY: predictable I/O.
# =============================================================================
def h1_init(date_str: str | None) -> date:
    config.ensure_directories()
    target = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    target = sdf.last_trading_day(target)
    print(f"[H1] init | framework v{config.FRAMEWORK_VERSION} | trading date {target}")
    return target


# =============================================================================
# BLOCK H2 - DOWNLOAD (A1-A12)
# =============================================================================
def h2_download(target: date, do_download: bool) -> dict:
    if not do_download:
        print("[H2] download skipped (--no-download) -> using local CSVs")
        return {}
    print("[H2] downloading raw data ...")
    report = sdf.download_all(target)
    for src, r in report.items():
        print(f"     {src:>14}: {r.get('status')}")
    return report


# =============================================================================
# BLOCK H3 - LOAD (C1-C10)
# =============================================================================
def h3_load(target: date) -> dict:
    bundle = dfetch.load_bundle(target)
    q = bundle["_quality"]
    print("[H3] loaded:", {k: f"{v['rows']}r {'OK' if v['ok'] else v['issues']}"
                           for k, v in q.items()})
    return bundle


# --- shared market context derived once per day ------------------------------
def _india_vix(bundle: dict) -> float | None:
    idx = bundle.get("indices")
    if idx is not None and not idx.empty:
        m = idx[idx["index_name"].str.upper().str.contains("VIX", na=False)]
        if not m.empty and not pd.isna(m["close"].iloc[0]):
            return float(m["close"].iloc[0])
    im = bundle.get("intermarket")
    return None  # India VIX not in intermarket set; stays None -> S12 ungated


def _nifty_spot(bundle: dict) -> float | None:
    opt = bundle.get("options")
    if opt is not None and not opt.empty and "underlyingValue" in opt and opt["underlyingValue"].notna().any():
        return float(opt["underlyingValue"].dropna().iloc[0])
    idx = bundle.get("indices")
    if idx is not None and not idx.empty:
        m = idx[idx["index_name"].str.upper().str.contains("NIFTY 50", na=False)]
        if not m.empty:
            return float(m["close"].iloc[0])
    return config.NIFTY_KEY_LEVELS["ath"]  # last-resort placeholder


# =============================================================================
# BLOCK H7 - SCORE S12-S15 (options block, index level, computed once)
# =============================================================================
def h7_score_options(bundle: dict, spot, vix, event_week, nifty_change) -> dict:
    block = reo.score_options_block(
        bundle.get("options", pd.DataFrame()),
        spot=spot, vix=vix, event_week=event_week, price_change=nifty_change,
        futures_info=bundle.get("futures_info"),
        participant=bundle.get("participant_oi"))
    print(f"[H7] options: S12={block['S12']['score']}/{block['S12']['max']} "
          f"S14={block['S14']['score']}/{block['S14']['max']} "
          f"S15(shadow)={block['S15']['score']} S13={block['S13']['label']}")
    return block


# =============================================================================
# BLOCK H8 - SCORE S16-S18 (macro modifiers, computed once)
# =============================================================================
def h8_score_macro(bundle: dict) -> tuple[dict, dict]:
    im = bundle.get("intermarket", pd.DataFrame())
    s16 = rem.score_s16_intermarket(im)
    s17 = rem.score_s17_macro(im, s16)
    print(f"[H8] macro: S16={s16['score']}/{s16['max']} ({s16['label']}) "
          f"S17={s17['label']}")
    return s16, s17


# =============================================================================
# BLOCK H4 + H9 - SCORE S1-S11 PER STOCK, THEN PRECEDENCE ENGINE
# =============================================================================
def h4_h9_decide(target, bundle, options_block, s16, s17, watchlist) -> list[dict]:
    equity_df = bundle.get("equity", pd.DataFrame())
    vix = _india_vix(bundle)
    fii_dii = bundle.get("fii_dii")

    # S10 breadth is market-wide -> compute once and share.
    breadth = res.score_s10_breadth(equity_df) if not equity_df.empty else None
    # S9 event is market-wide -> compute once (also drives event_week for S12).
    event_res = res.score_s9_event(target, "LONG")
    event_week = event_res["components"].get("event_week", False)

    decisions = []
    print(f"[H4] scoring {len(watchlist)} stocks (S1-S11) + [H9] precedence ...")
    for sym in watchlist:
        try:
            hist = dfetch.build_stock_history(sym, lookback=250)
            if hist.empty:
                decisions.append({"symbol": sym, "grade": "NT", "grade_label": "No history",
                                  "conviction_pct": 0, "signal_agreement": "NO_TRADE",
                                  "gate_fail": True, "rule_scores": {}, "shadow": {},
                                  "direction": "NA"})
                continue
            ctx = {"fii_dii": fii_dii, "vix": vix, "breadth": breadth,
                   "equity_df": equity_df, "target": target}
            stock_result = res.composite_stock_score(sym, hist, ctx)
            decision = rem.run_precedence_engine(stock_result, options_block, s16, s17, sym)
            decision["shadow"] = stock_result.get("shadow", {})
            decisions.append(decision)
        except Exception as exc:  # noqa: BLE001 - one bad stock must not kill the run
            decisions.append({"symbol": sym, "grade": "ERR", "error": str(exc),
                              "conviction_pct": 0, "rule_scores": {}, "shadow": {}})
    graded = [d for d in decisions if d.get("grade") not in ("NT", "ERR", None)]
    print(f"[H9] decisions: {len(decisions)} scanned, "
          f"{len(graded)} tradable, "
          f"top={max((d.get('conviction_pct',0) for d in decisions), default=0):.0f}%")
    return decisions


# =============================================================================
# BLOCK H5 - CHARTS (F1-F7)
# =============================================================================
def h5_charts(decisions, bundle, spot, max_pain) -> dict:
    extras = {"spot": spot, "max_pain": max_pain}
    paths = cg.generate_all(decisions, bundle, extras)
    print(f"[H5] charts -> {len([p for p in paths.values() if p])} PNGs in output/charts")
    return paths


# =============================================================================
# BLOCK H6 - ALERTS (G1-G4) + shadow log
# =============================================================================
def h6_alerts(decisions, options_block, target) -> dict:
    rep = alerts.send_daily_alerts(decisions, target, min_grade="A")
    shadow_path = alerts.log_shadow(decisions, options_block, target)
    print(f"[H6] alerts: telegram={rep['telegram']['status']} "
          f"sheets={rep['sheets']['status']} | shadow_log -> {os.path.basename(shadow_path)}")
    return rep


# =============================================================================
# ORCHESTRATION
# =============================================================================
def run(date_str: str | None = None, do_download: bool = True,
        watchlist: list[str] | None = None) -> dict:
    target = h1_init(date_str)
    watchlist = watchlist or config.WATCHLIST

    h2_download(target, do_download)
    bundle = h3_load(target)

    spot = _nifty_spot(bundle)
    vix = _india_vix(bundle)
    event_week = res.score_s9_event(target, "LONG")["components"].get("event_week", False)
    nifty_change = None  # +/- nifty change drives S12 buildup; None when unknown

    options_block = h7_score_options(bundle, spot, vix, event_week, nifty_change)
    s16, s17 = h8_score_macro(bundle)
    decisions = h4_h9_decide(target, bundle, options_block, s16, s17, watchlist)

    max_pain = options_block["S12"]["components"].get("c1_maxpain", {}).get("max_pain")
    h5_charts(decisions, bundle, spot, max_pain)
    h6_alerts(decisions, options_block, target)

    # ML1 - data collector ALWAYS runs (even with ML disabled).
    try:
        store = ml_optimizer.collect_daily(target, decisions, bundle, options_block, s16, s17)
        print(f"[ML1] training row appended -> {os.path.basename(store)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[ML1] collector skipped: {exc}")

    _persist_scores(target, decisions)
    print(f"[DONE] {target} | grades: " + _grade_histogram(decisions))
    return {"target": target.isoformat(), "decisions": decisions,
            "options": options_block, "s16": s16, "s17": s17}


def _grade_histogram(decisions) -> str:
    from collections import Counter
    c = Counter(d.get("grade", "NA") for d in decisions)
    return " ".join(f"{k}:{v}" for k, v in sorted(c.items()))


def _persist_scores(target: date, decisions: list[dict]) -> str:
    out_dir = os.path.join(config.OUTPUT_DIR, "daily_scores")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"scores_{target.isoformat()}.json")
    with open(path, "w") as fh:
        json.dump([{k: v for k, v in d.items() if k != "shadow"} for d in decisions],
                  fh, indent=2, default=str)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Nifty Framework daily pipeline (H1-H9)")
    ap.add_argument("--date", help="trading date YYYY-MM-DD (default: last trading day)")
    ap.add_argument("--no-download", action="store_true", help="use local CSVs only")
    ap.add_argument("--watchlist", nargs="*", help="override symbols to scan")
    args = ap.parse_args()
    try:
        run(args.date, do_download=not args.no_download, watchlist=args.watchlist)
    except Exception:
        print("[FATAL] pipeline error:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
