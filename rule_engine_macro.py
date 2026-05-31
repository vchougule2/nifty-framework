"""
rule_engine_macro.py - Macro / Intermarket Engine + Precedence (Blocks K1-K9)
============================================================================
WHAT:   Scores S16 (Intermarket, /10 MODIFIER), S17 (Currency & Macro, MODIFIER),
        S18 (Composite Aggregator, AUTO) and runs the PRECEDENCE ENGINE that
        fuses stock + options + macro into one graded decision per stock.
WHY:    Macro sets the tailwind/headwind; the precedence engine enforces the
        Tier-1..Tier-6 hierarchy from blueprint Part 4.
IMPACT: S16>=8 -> +5% conviction; S16<=4 -> -5%. S17 = sector boost/penalty only.
        run_precedence_engine() is what main_pipeline H9 calls.

Block map:
    K1 S16 crude | K2 S16 DXY | K3 S16 bonds/yield | K4 S16 global + composite/modifier
    K5 S17 INR | K6 S17 yield-spread macro | K7 S17 RBI | K8 S17 gold + sector map
    K9 S18 aggregator + run_precedence_engine
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from . import config
except ImportError:
    import config


def _r(rule, score, mode, tier, label="", components=None, notes="", dq="OK") -> dict:
    return {"rule": rule, "score": round(float(score), 2), "max": config.MAX_SCORES.get(rule),
            "mode": mode, "tier": tier, "label": label, "components": components or {},
            "notes": notes, "data_quality": dq}


def _roc(im: pd.DataFrame, col: str, periods: int) -> float | None:
    """Percentage rate-of-change of column `col` over `periods` rows (trading days)."""
    if im is None or im.empty or col not in im or im[col].dropna().shape[0] <= periods:
        return None
    s = im[col].dropna()
    last, past = s.iloc[-1], s.iloc[-1 - periods]
    if past == 0:
        return None
    return (last - past) / abs(past) * 100.0


def _delta(im: pd.DataFrame, col: str, periods: int) -> float | None:
    """Absolute change of `col` over `periods` rows (used for yields in bps)."""
    if im is None or im.empty or col not in im or im[col].dropna().shape[0] <= periods:
        return None
    s = im[col].dropna()
    return float(s.iloc[-1] - s.iloc[-1 - periods])


# =============================================================================
# BLOCK K1 - S16 C1 CRUDE (weekly ROC)  falling>3%=3 / rising>3%=0
# =============================================================================
def s16_c1_crude(im: pd.DataFrame) -> dict:
    cfg = config.S16_INTERMARKET
    roc = _roc(im, "BRENT", 5)
    if roc is None:
        return {"score": 0, "roc": None, "dq": "MISSING"}
    if roc <= cfg["crude_weekly_roc_bullish"]:
        s = 3
    elif roc < 0:
        s = 2
    elif roc < cfg["crude_weekly_roc_bearish"]:
        s = 1
    else:
        s = 0
    return {"score": s, "roc": round(roc, 2), "dq": "OK"}


# =============================================================================
# BLOCK K2 - S16 C2 DXY (monthly ROC)  falling=3 / rising>2%=0
# =============================================================================
def s16_c2_dxy(im: pd.DataFrame) -> dict:
    cfg = config.S16_INTERMARKET
    roc = _roc(im, "DXY", 22)
    if roc is None:
        return {"score": 0, "roc": None, "dq": "MISSING"}
    if roc <= cfg["dxy_monthly_roc_bullish_em"]:
        s = 3
    elif roc < 0:
        s = 2
    elif roc < cfg["dxy_monthly_roc_bearish_em"]:
        s = 1
    else:
        s = 0
    return {"score": s, "roc": round(roc, 2), "dq": "OK"}


# =============================================================================
# BLOCK K3 - S16 C3 INDIA 10Y YIELD (2-week delta)  falling>20bps=2 / rising>20bps=0
# =============================================================================
def s16_c3_yield(im: pd.DataFrame) -> dict:
    cfg = config.S16_INTERMARKET
    d = _delta(im, "IN10Y", 10)  # ^TNX proxy is in % (e.g. 4.25); 0.20 = 20bps
    if d is None:
        return {"score": 1, "delta_bps": None, "dq": "MISSING"}
    bps = d * 100.0
    if bps <= cfg["yield_change_bullish_bps"]:
        s = 2
    elif bps >= cfg["yield_change_bearish_bps"]:
        s = 0
    else:
        s = 1
    return {"score": s, "delta_bps": round(bps, 1), "dq": "OK"}


# =============================================================================
# BLOCK K4 - S16 C4 GLOBAL MARKETS + S16 COMPOSITE + MODIFIER
# all positive=2 ; composite /10 ; S16>=8 -> +5% , S16<=4 -> -5%
# =============================================================================
def s16_c4_global(im: pd.DataFrame) -> dict:
    rocs = [_roc(im, c, 1) for c in ["SPX", "NIKKEI", "HSI"]]
    have = [x for x in rocs if x is not None]
    if not have:
        return {"score": 0, "global_rocs": rocs, "dq": "MISSING"}
    pos = sum(x > 0 for x in have)
    s = 2 if pos == len(have) else 1 if pos >= 1 else 0
    return {"score": s, "global_rocs": [None if x is None else round(x, 2) for x in rocs], "dq": "OK"}


def score_s16_intermarket(im: pd.DataFrame) -> dict:
    cfg = config.S16_INTERMARKET
    c1, c2, c3, c4 = s16_c1_crude(im), s16_c2_dxy(im), s16_c3_yield(im), s16_c4_global(im)
    total = c1["score"] + c2["score"] + c3["score"] + c4["score"]
    total = min(cfg["max_score"], total)
    # Data-quality: how many components actually had data?
    missing = sum(x.get("dq") == "MISSING" for x in (c1, c2, c3, c4))
    dq = "DEGRADED" if missing else "OK"
    if missing >= 3:
        # Optional modifier with too little data -> NEUTRAL (blueprint Part 9).
        modifier, label = 0.0, "NEUTRAL(NO_DATA)"
    elif total >= cfg["boost_threshold"]:
        modifier, label = cfg["boost_pct"], "TAILWIND(+5%)"
    elif total <= cfg["penalty_threshold"]:
        modifier, label = cfg["penalty_pct"], "HEADWIND(-5%)"
    else:
        modifier, label = 0.0, "NEUTRAL"
    res = _r("S16", total, "MODIFIER", 4, label,
             {"c1_crude": c1, "c2_dxy": c2, "c3_yield": c3, "c4_global": c4}, dq=dq)
    res["modifier"] = modifier
    # Crude-crash override: extra sector bonus for OMC/auto (handled by S17 sector map).
    res["crude_crash"] = bool(c1["roc"] is not None and c1["roc"] <= -5.0)
    return res


# =============================================================================
# BLOCK K5-K8 - S17 CURRENCY & MACRO (MODIFIER, sector boost/penalty only)
# K5 INR | K6 yield-spread macro | K7 RBI stance | K8 gold + sector map
# =============================================================================
def score_s17_macro(im: pd.DataFrame, s16: dict | None = None) -> dict:
    cfg = config.S17_MACRO
    inr_roc = _roc(im, "USDINR", 5)          # K5: USDINR weekly ROC (up = INR weak)
    gold_roc = _roc(im, "GOLD", 5)           # K8: gold weekly ROC (up = risk-off)

    boosts, penalties, tags = [], [], []
    # K5 INR regime -> exporters vs domestics.
    if inr_roc is not None and inr_roc >= cfg["usdinr_weak_threshold"]:
        boosts += cfg["inr_weak_boost"]
        tags.append("INR_WEAK->exporters")
    elif inr_roc is not None and inr_roc <= cfg["usdinr_strong_threshold"]:
        boosts += cfg["inr_strong_boost"]
        tags.append("INR_STRONG->domestics")

    # K7 RBI stance.
    if cfg["rbi_stance"] == "accommodative":
        tags.append("RBI_ACCOMMODATIVE(+)")
    elif cfg["rbi_stance"] == "tightening":
        tags.append("RBI_TIGHTENING(caution)")

    # K8 gold risk-off + crude-crash override (from S16).
    risk_off = bool(gold_roc is not None and gold_roc >= cfg["gold_risk_off_roc"])
    if risk_off:
        tags.append("GOLD_RISK_OFF")
    if s16 and s16.get("crude_crash"):
        boosts += cfg["crude_crash_boost"]
        tags.append("CRUDE_CRASH->OMC/auto")

    return _r("S17", 0, "MODIFIER", 4, ";".join(tags) or "NEUTRAL",
              {"usdinr_roc": None if inr_roc is None else round(inr_roc, 2),
               "gold_roc": None if gold_roc is None else round(gold_roc, 2),
               "boost_symbols": sorted(set(boosts)),
               "penalty_symbols": sorted(set(penalties)),
               "risk_off": risk_off},
              "sector boost/penalty only - weakest evidence (6/10)")


def s17_sector_adjust(symbol: str, s17: dict) -> float:
    """Return a conviction multiplier delta for `symbol` from the S17 sector map."""
    comp = s17.get("components", {})
    if symbol.upper() in [s.upper() for s in comp.get("boost_symbols", [])]:
        return +config.S16_INTERMARKET["boost_pct"]    # reuse +5% step
    if symbol.upper() in [s.upper() for s in comp.get("penalty_symbols", [])]:
        return config.S16_INTERMARKET["penalty_pct"]
    return 0.0


# =============================================================================
# BLOCK K9a - S18 COMPOSITE AGGREGATOR (AUTO)
# Auto-combines S12 + S14 ; S13 weight 0 (parked), S15 weight 0 (shadow).
# =============================================================================
def score_s18_aggregate(options_block: dict) -> dict:
    s12 = options_block.get("S12", {})
    s14 = options_block.get("S14", {})
    score = s12.get("score", 0) + s14.get("score", 0)
    mx = (config.MAX_SCORES["S12"] + config.MAX_SCORES["S14"])
    return {"rule": "S18", "score": round(score, 2), "max": mx, "mode": "AUTO", "tier": None,
            "label": "DERIV_COMPOSITE",
            "components": {"S12": s12.get("score"), "S14": s14.get("score"),
                           "S13_weight": 0, "S15_weight": 0},
            "pct": round(score / mx, 4) if mx else 0.0}


# =============================================================================
# BLOCK K9b - PRECEDENCE ENGINE  (the H9 decision core)
# Tier1 gates -> Tier2 (need 3/4) -> Tier3 confirm -> Tier4 modifiers -> grade.
# =============================================================================
def _positive(rule_res: dict, frac: float = 0.4) -> bool:
    mx = rule_res.get("max") or 1
    return rule_res.get("score", 0) >= frac * mx


def run_precedence_engine(stock_result: dict, options_block: dict,
                          s16: dict, s17: dict, symbol: str | None = None) -> dict:
    """
    Fuse the three engines into one graded decision. Implements blueprint Part 4
    (precedence) + Part 5 (scoring/grading) + S16/S17 modifiers.
    """
    symbol = symbol or stock_result.get("symbol", "?")
    rules = dict(stock_result.get("rules", {}))
    rules["S12"] = options_block.get("S12", _r("S12", 0, "ACTIVE", 2, "NO_DATA"))
    rules["S14"] = options_block.get("S14", _r("S14", 0, "ACTIVE", 3, "NO_DATA"))

    # ---- Tier 1: GATES (S1, S5) ----
    s1_pass = rules.get("S1", {}).get("passed", False)
    s5 = rules.get("S5", {})
    s2, s4 = rules.get("S2", {}), rules.get("S4", {})
    s5_block = s5.get("score", 0) <= config.S5_BOS["hard_block_score"] and not (
        s2.get("score", 0) >= config.S5_BOS["s2_override_min"] and
        s4.get("score", 0) >= config.S5_BOS["s4_override_min"])
    gate_fail = (not s1_pass) or s5_block

    # ---- Tier 2 PRIMARY (need 3/4 positive) ----
    t2 = ["S2", "S4", "S6", "S12"]
    t2_pos = sum(_positive(rules.get(r, {})) for r in t2)
    # ---- Tier 3 CONFIRMATION ----
    t3 = ["S3", "S7", "S9", "S10", "S14"]
    t3_pos = sum(_positive(rules.get(r, {})) for r in t3)

    # ---- Weighted score across the active 117 (S5 + S2,S3,S4,S6,S7,S9,S10,S12,S14) ----
    weights = config.get_active_weight_profile()
    scored = ["S5", "S2", "S3", "S4", "S6", "S7", "S9", "S10", "S12", "S14"]
    wsum = wmax = 0.0
    for rkey in scored:
        w = weights.get(rkey, 1.0)
        wsum += max(0, rules.get(rkey, {}).get("score", 0)) * w
        wmax += config.MAX_SCORES[rkey] * w
    base_pct = (wsum / wmax) if wmax else 0.0

    # ---- Tier 4 MODIFIERS (S16 conviction +/-5%, S17 sector) ----
    modifier = s16.get("modifier", 0.0) + s17_sector_adjust(symbol, s17)
    conviction = base_pct * (1.0 + modifier)
    conviction = max(0.0, min(1.0, conviction))

    # ---- Decision / Grade ----
    if gate_fail or t2_pos == 0:
        grade, label, pos = "NT", "No Trade", 0.0
        signal = "NO_TRADE"
    else:
        if conviction >= config.GRADE_THRESHOLDS["A_PLUS"]:
            grade, label, pos = "A+", "Sniper Entry", 1.0
        elif conviction >= config.GRADE_THRESHOLDS["A"]:
            grade, label, pos = "A", "Strong Setup", 0.75
        elif conviction >= config.GRADE_THRESHOLDS["B"]:
            grade, label, pos = "B", "Moderate", 0.50
        elif conviction >= config.GRADE_THRESHOLDS["C"]:
            grade, label, pos = "C", "Weak - Paper Only", 0.0
        else:
            grade, label, pos = "NT", "No Trade", 0.0
        # Signal agreement (blueprint Part 4).
        if not gate_fail and t2_pos >= 3:
            signal = "HIGH"
        elif not gate_fail and t2_pos >= 2 and t3_pos >= 2:
            signal = "MODERATE"
        elif not gate_fail and t2_pos >= 1:
            signal = "LOW"
        else:
            signal = "NO_TRADE"

    return {
        "symbol": symbol,
        "direction": stock_result.get("direction", "LONG"),
        "grade": grade,
        "grade_label": label,
        "position_pct": pos,
        "signal_agreement": signal,
        "conviction_pct": round(conviction * 100, 2),
        "base_pct": round(base_pct * 100, 2),
        "modifier_pct": round(modifier * 100, 2),
        "gate_fail": gate_fail,
        "gate_reasons": (["S1 fail"] if not s1_pass else []) + (["S5 soft-gate block"] if s5_block else []),
        "tier2_positive": t2_pos,
        "tier3_positive": t3_pos,
        "s18_aggregate": score_s18_aggregate(options_block),
        "rule_scores": {k: v.get("score") for k, v in rules.items()},
    }
