"""
ml/ml_optimizer.py - ML Data Collector & Feature Store (Blocks ML1-ML3)
=======================================================================
WHAT:   Collects the daily feature vector (all rule scores + macro context +
        decision) into a growing training store, engineers features, and reports
        how close we are to the 120-day threshold.
WHY:    The predictor (ML4-ML6) and S13 stay parked until we have enough labelled
        history. The collector must run EVERY day so that data exists when ML turns on.
IMPACT: ML1 is ALWAYS-ON (config.ML_CONFIG.collector_always_on). It writes
        ml/data/training_store.csv. The 5-day forward return label is back-filled
        later by label_forward_returns() once price history catches up.

Block map: ML1 collect_daily | ML2 engineer_features | ML3 store/report + labelling
"""

from __future__ import annotations

import os
from datetime import date

import numpy as np
import pandas as pd

try:
    from .. import config
except ImportError:
    import config


STORE = lambda: os.path.join(config.ML_DIR, "training_store.csv")  # noqa: E731

# Columns captured per stock per day (rule scores are the model features).
FEATURE_RULES = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S9", "S10", "S12", "S14"]


# =============================================================================
# BLOCK ML1 - DAILY COLLECTOR (ALWAYS ON)
# WHAT: Append one row per stock with rule scores + macro + decision.
# WHY:  Builds the labelled dataset the model will eventually train on.
# =============================================================================
def collect_daily(target: date, decisions: list[dict], bundle: dict,
                  options_block: dict, s16: dict, s17: dict) -> str:
    config.ensure_directories()
    if not config.ML_CONFIG.get("collector_always_on", True):
        return STORE()

    macro = {
        "S16": s16.get("score"), "S16_mod": s16.get("modifier"),
        "crude_roc": s16.get("components", {}).get("c1_crude", {}).get("roc"),
        "dxy_roc": s16.get("components", {}).get("c2_dxy", {}).get("roc"),
        "usdinr_roc": s17.get("components", {}).get("usdinr_roc"),
        "S12_index": options_block.get("S12", {}).get("score"),
        "S14_index": options_block.get("S14", {}).get("score"),
        "S15_index": options_block.get("S15", {}).get("score"),
    }

    rows = []
    for d in decisions:
        if not d or d.get("grade") in ("ERR",):
            continue
        rs = d.get("rule_scores", {})
        row = {"date": target.isoformat(), "symbol": d.get("symbol"),
               "direction": d.get("direction"),
               "grade": d.get("grade"), "conviction_pct": d.get("conviction_pct"),
               "signal": d.get("signal_agreement"),
               "fwd_return_5d": np.nan}            # label - back-filled later
        for r in FEATURE_RULES:
            row[f"f_{r}"] = rs.get(r)
        row.update(macro)
        rows.append(row)

    if not rows:
        return STORE()
    df = pd.DataFrame(rows)
    header = not os.path.exists(STORE())
    df.to_csv(STORE(), mode="a", header=header, index=False)
    return STORE()


# =============================================================================
# BLOCK ML2 - FEATURE ENGINEERING
# WHAT: Build a clean (X, y) matrix from the store for training/inspection.
# WHY:  Encapsulates rule-score -> feature transform so ML4-ML6 stay simple.
# =============================================================================
def engineer_features(store_path: str | None = None) -> pd.DataFrame:
    path = store_path or STORE()
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    feat_cols = [c for c in df.columns if c.startswith("f_")] + \
                ["S16", "crude_roc", "dxy_roc", "usdinr_roc",
                 "S12_index", "S14_index", "conviction_pct"]
    for c in feat_cols:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Simple engineered features: tier sums + agreement count.
    tier2 = [f"f_{r}" for r in ["S2", "S4", "S6", "S12"] if f"f_{r}" in df]
    tier3 = [f"f_{r}" for r in ["S3", "S7", "S9", "S10", "S14"] if f"f_{r}" in df]
    df["tier2_sum"] = df[tier2].sum(axis=1) if tier2 else 0
    df["tier3_sum"] = df[tier3].sum(axis=1) if tier3 else 0
    return df


# =============================================================================
# BLOCK ML3 - STORE REPORT + FORWARD-RETURN LABELLING
# WHAT: Days collected vs the 120-day gate; back-fill the 5-day forward label.
# WHY:  ML / S13 only switch on when readiness() says we have enough labelled data.
# =============================================================================
def readiness() -> dict:
    path = STORE()
    if not os.path.exists(path):
        return {"days": 0, "min_days": config.ML_CONFIG["min_days"], "ready": False}
    df = pd.read_csv(path)
    days = df["date"].nunique() if "date" in df else 0
    labelled = int(df["fwd_return_5d"].notna().sum()) if "fwd_return_5d" in df else 0
    ready = days >= config.ML_CONFIG["min_days"] and labelled > 0
    return {"days": int(days), "labelled": labelled,
            "min_days": config.ML_CONFIG["min_days"], "ready": bool(ready)}


def label_forward_returns(price_lookup) -> str:
    """
    Back-fill fwd_return_5d using price_lookup(symbol, date)->close.
    Called periodically once enough forward price history exists.
    """
    path = STORE()
    if not os.path.exists(path):
        return path
    df = pd.read_csv(path)
    if "fwd_return_5d" not in df:
        df["fwd_return_5d"] = np.nan
    for i, row in df[df["fwd_return_5d"].isna()].iterrows():
        try:
            entry = price_lookup(row["symbol"], row["date"])
            fwd = price_lookup(row["symbol"], row["date"], offset=5)
            if entry and fwd:
                df.at[i, "fwd_return_5d"] = (fwd - entry) / entry * 100
        except Exception:
            continue
    df.to_csv(path, index=False)
    return path
