"""
rule_engine_options.py - Options / Futures / Participant Engine (Blocks J1-J13)
==============================================================================
WHAT:   Scores S12 (Options Chain Intelligence), S13 (IV - PARKED),
        S14 (Futures Basis & Rollover) and S15 (F&O Participant - SHADOW).
WHY:    Derivatives positioning is the institutional footprint - it confirms or
        vetoes the cash-market read from rule_engine_stock.
IMPACT: S12 is a Tier-2 PRIMARY rule but is MANDATORY-gated by VIX (<18) and the
        S9 event flag (max-pain weight halved on event weeks). S13 stays parked
        until ML_ENABLED. S15 is collected in shadow only.

Block map:
    J1 S12 Max Pain | J2 S12 PCR | J3 S12 OI Walls | J4 S12 OI Buildup
    J5 S12 VIX gate + S9 cross-check | J6 S12 composite
    J7 S13 IV (PARKED) | J8 S14 basis | J9 S14 ROC | J10 S14 rollover
    J11 S14 term-structure + composite | J12 S15 participant | J13 S15 composite + aggregate
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


def _nearest_expiry(chain: pd.DataFrame) -> pd.DataFrame:
    """Filter the chain to the nearest expiry (front month)."""
    if "expiryDate" not in chain or chain["expiryDate"].isna().all():
        return chain
    try:
        exp = pd.to_datetime(chain["expiryDate"], errors="coerce")
        nearest = exp.dropna().min()
        return chain[exp == nearest]
    except Exception:
        return chain


# =============================================================================
# BLOCK J1 - S12 C1 MAX PAIN (/4)
# Below MP >2%=4 / 1-2%=3 / at MP=2 / above 1-2%=1 / above >2%=0 / trap=-1
# Pain asymmetry: put/call value >1.5 bullish skew, <0.7 bearish skew
# =============================================================================
def _max_pain_strike(chain: pd.DataFrame) -> float | None:
    ce = chain[chain["type"] == "CE"]
    pe = chain[chain["type"] == "PE"]
    strikes = sorted(set(chain["strikePrice"].dropna()))
    if not strikes:
        return None
    best, best_pain = None, float("inf")
    for k in strikes:
        ce_pain = float((ce["openInterest"] * (k - ce["strikePrice"]).clip(lower=0)).sum())
        pe_pain = float((pe["openInterest"] * (pe["strikePrice"] - k).clip(lower=0)).sum())
        total = ce_pain + pe_pain
        if total < best_pain:
            best_pain, best = total, k
    return best


def s12_c1_max_pain(chain: pd.DataFrame, spot: float) -> dict:
    cfg = config.S12_OPTIONS
    front = _nearest_expiry(chain)
    mp = _max_pain_strike(front)
    if mp is None or not spot:
        return {"score": 0, "max_pain": mp, "dist_pct": None, "asymmetry": None}
    dist_pct = (spot - mp) / mp * 100
    if dist_pct <= -cfg["max_pain_extended_pct"]:
        score = 4
    elif dist_pct <= -1:
        score = 3
    elif abs(dist_pct) < 0.5:
        score = 2
    elif dist_pct <= cfg["max_pain_extended_pct"]:
        score = 1
    else:
        score = 0
    # Pain asymmetry around spot (put value vs call value).
    near = front[(front["strikePrice"] >= spot * 0.97) & (front["strikePrice"] <= spot * 1.03)]
    put_val = float((near[near["type"] == "PE"]["openInterest"]).sum())
    call_val = float((near[near["type"] == "CE"]["openInterest"]).sum())
    asym = put_val / call_val if call_val else None
    if asym is not None:
        if asym >= cfg["pain_asymmetry_bullish"] and score < 4:
            score += 1
        elif asym <= cfg["pain_asymmetry_bearish"]:
            score = max(-1, score - 1)  # trap risk
    return {"score": max(-1, min(4, score)), "max_pain": mp,
            "dist_pct": round(dist_pct, 2), "asymmetry": None if asym is None else round(asym, 2)}


# =============================================================================
# BLOCK J2 - S12 C2 PCR (/3)
# all bullish (>1.2 & rising)=3 / mixed=1 / all bearish=0
# contrarian: PCR>1.5 or <0.6 => 72% reversal flag
# =============================================================================
def s12_c2_pcr(chain: pd.DataFrame, pcr_history: list[float] | None = None) -> dict:
    cfg = config.S12_OPTIONS
    front = _nearest_expiry(chain)
    put_oi = float(front[front["type"] == "PE"]["openInterest"].sum())
    call_oi = float(front[front["type"] == "CE"]["openInterest"].sum())
    pcr = put_oi / call_oi if call_oi else 0
    rising = bool(pcr_history and len(pcr_history) >= 2 and pcr > pcr_history[-1])
    if pcr >= cfg["pcr_strong_bullish"] and rising:
        score = 3
    elif pcr >= cfg["pcr_bullish"]:
        score = 1
    else:
        score = 0
    contrarian = pcr >= cfg["pcr_contrarian_high"] or (0 < pcr <= cfg["pcr_contrarian_low"])
    return {"score": score, "pcr": round(pcr, 3), "rising": rising,
            "contrarian_reversal": contrarian}


# =============================================================================
# BLOCK J3 - S12 C3 OI WALLS (/4)
# put floor + call ceiling weakening=4 / put floor=3 / balanced=2
# OI CHANGE% matters more than absolute OI
# =============================================================================
def s12_c3_oi_walls(chain: pd.DataFrame, spot: float) -> dict:
    front = _nearest_expiry(chain)
    ce = front[front["type"] == "CE"]
    pe = front[front["type"] == "PE"]
    if ce.empty or pe.empty:
        return {"score": 0, "call_wall": None, "put_wall": None}
    call_wall = ce.loc[ce["openInterest"].idxmax(), "strikePrice"]
    put_wall = pe.loc[pe["openInterest"].idxmax(), "strikePrice"]
    # Is the call ceiling weakening (call OI being shed) while put floor builds?
    call_chg = float(ce[ce["strikePrice"] == call_wall]["changeinOpenInterest"].sum())
    put_chg = float(pe[pe["strikePrice"] == put_wall]["changeinOpenInterest"].sum())
    put_floor_below = put_wall <= spot if spot else True
    call_ceiling_above = call_wall >= spot if spot else True
    if put_floor_below and call_ceiling_above and put_chg > 0 and call_chg < 0:
        score = 4
    elif put_floor_below and put_chg > 0:
        score = 3
    else:
        score = 2
    return {"score": score, "call_wall": call_wall, "put_wall": put_wall,
            "call_oi_chg": call_chg, "put_oi_chg": put_chg}


# =============================================================================
# BLOCK J4 - S12 C4 OI BUILDUP (/4)
# Long Buildup(price^ OI^)=4(78%) / Short Covering(price^ OI v)=2(55%)
# Long Unwinding(price v OI v)=1 / Short Buildup(price v OI^)=0(74% down)
# =============================================================================
def s12_c4_buildup(chain: pd.DataFrame, price_change: float | None) -> dict:
    cfg = config.S12_OPTIONS["buildup"]
    front = _nearest_expiry(chain)
    net_oi_chg = float(front["changeinOpenInterest"].sum())
    if price_change is None:
        return {"score": 1, "type": "unknown", "net_oi_chg": net_oi_chg}
    if price_change > 0 and net_oi_chg > 0:
        t, s = "long_buildup", cfg["long_buildup"]
    elif price_change > 0 and net_oi_chg <= 0:
        t, s = "short_covering", cfg["short_covering"]
    elif price_change <= 0 and net_oi_chg <= 0:
        t, s = "long_unwinding", cfg["long_unwinding"]
    else:
        t, s = "short_buildup", cfg["short_buildup"]
    return {"score": s, "type": t, "net_oi_chg": net_oi_chg}


# =============================================================================
# BLOCK J5 - S12 VIX GATE + S9 EVENT CROSS-CHECK  (MANDATORY)
# WHAT: Caps/penalises max-pain when VIX>=18 and halves it on event weeks.
# WHY:  Max pain is unreliable in high-vol / event tape (82% -> 34% accuracy).
# =============================================================================
def s12_apply_gates(c1_score: float, vix: float | None, event_week: bool) -> tuple[float, list[str]]:
    cfg = config.S12_OPTIONS
    notes = []
    out = c1_score
    if vix is not None and vix >= cfg["vix_gate"]:
        out = min(out, cfg["vix_high_score_cap"])
        notes.append(f"VIX {vix}>=18 -> C1 capped at {cfg['vix_high_score_cap']}")
    if event_week:
        out = out * cfg["event_week_multiplier"]
        notes.append("event week -> C1 x0.5")
    return out, notes


# =============================================================================
# BLOCK J6 - S12 COMPOSITE (/15)
# =============================================================================
def score_s12_options(chain: pd.DataFrame, spot: float | None = None,
                      vix: float | None = None, event_week: bool = False,
                      price_change: float | None = None,
                      pcr_history: list[float] | None = None) -> dict:
    if chain is None or chain.empty:
        return _r("S12", 0, "ACTIVE", 2, "NO_DATA", dq="MISSING")
    if spot is None and "underlyingValue" in chain:
        spot = float(chain["underlyingValue"].dropna().iloc[0]) if chain["underlyingValue"].notna().any() else None

    c1 = s12_c1_max_pain(chain, spot or 0)
    c2 = s12_c2_pcr(chain, pcr_history)
    c3 = s12_c3_oi_walls(chain, spot or 0)
    c4 = s12_c4_buildup(chain, price_change)

    c1_gated, gate_notes = s12_apply_gates(c1["score"], vix, event_week)
    total = max(0, c1_gated) + c2["score"] + c3["score"] + c4["score"]
    total = max(0, min(config.MAX_SCORES["S12"], total))
    label = ("Strong" if total >= 11 else "Moderate" if total >= 7 else "Weak" if total >= 4 else "Flat")
    return _r("S12", total, "ACTIVE", 2, label,
              {"c1_maxpain": c1, "c1_gated": round(max(0, c1_gated), 2),
               "c2_pcr": c2, "c3_walls": c3, "c4_buildup": c4},
              "; ".join(gate_notes))


# =============================================================================
# BLOCK J7 - S13 IV & VOLATILITY (/10)  [PARKED until ML_ENABLED]
# Rule-based Sharpe only 0.12 -> parked; ML-enhanced 0.78.
# =============================================================================
def score_s13_iv(chain: pd.DataFrame | None = None) -> dict:
    if not config.S13_ENABLED:
        return _r("S13", 0, "PARKED", 6, "PARKED",
                  notes="S13 parked until ML_ENABLED (rule-based Sharpe 0.12)")
    # (Active logic would compute IV skew / term structure / IV rank here.)
    return _r("S13", 0, "PARKED", 6, "PARKED", notes="active path reserved")


# =============================================================================
# BLOCK J8-J11 - S14 FUTURES BASIS & ROLLOVER (/10)
# C1 basis vs fair value(/3) | C2 basis ROC(/3) | C3 rollover%(/2) | C4 term(/2)
# FV basis = Spot*(RFR-DivY)/100*(DTE/365)
# =============================================================================
def _fair_value_basis(spot: float, dte: int) -> float:
    cfg = config.S14_BASIS
    return spot * (cfg["risk_free_rate"] - cfg["div_yield"]) / 100.0 * (dte / 365.0)


def s14_c1_basis(spot: float, near_fut: float, dte: int) -> dict:  # J8
    cfg = config.S14_BASIS
    basis = near_fut - spot
    excess = basis - _fair_value_basis(spot, dte)
    if excess >= cfg["excess_basis_significant"]:
        s = 3
    elif excess >= cfg["excess_basis_mild"]:
        s = 2
    elif excess >= cfg["discount_threshold"]:
        s = 1
    elif excess >= -cfg["excess_basis_significant"]:
        s = 0
    else:
        s = -1
    return {"score": s, "basis": round(basis, 2), "excess_pts": round(excess, 2)}


def s14_c2_roc(basis_history: list[float] | None, price_up: bool) -> dict:  # J9
    if not basis_history or len(basis_history) < 2:
        return {"score": 1, "trend": "unknown"}
    delta = basis_history[-1] - basis_history[-1 - min(len(basis_history) - 1, config.S14_BASIS["basis_roc_lookback"])]
    if delta > config.S14_BASIS["basis_expanding_threshold"] and price_up:
        return {"score": 3, "trend": "expanding+up"}
    if abs(delta) <= config.S14_BASIS["basis_expanding_threshold"] and price_up:
        return {"score": 2, "trend": "stable+up"}
    if delta < 0 and price_up:
        return {"score": 1, "trend": "contracting+up(weak)"}
    return {"score": 0, "trend": "down"}


def s14_c3_rollover(rollover_pct: float | None, is_expiry_week: bool) -> dict:  # J10
    cfg = config.S14_BASIS
    if rollover_pct is None or not is_expiry_week:
        return {"score": 0, "rollover_pct": rollover_pct, "note": "only last 3 expiry sessions"}
    if rollover_pct >= cfg["rollover_high"]:
        s = 2
    elif rollover_pct >= cfg["rollover_normal"]:
        s = 1
    else:
        s = 0
    return {"score": s, "rollover_pct": rollover_pct}


def s14_c4_term(near_fut: float, far_fut: float | None) -> dict:  # J11
    if far_fut is None:
        return {"score": 1, "structure": "unknown"}
    spread = far_fut - near_fut
    if spread >= config.S14_BASIS["contango_threshold_pts"]:
        return {"score": 2, "structure": "contango"}
    if spread <= config.S14_BASIS["backwardation_threshold_pts"]:
        return {"score": 0, "structure": "backwardation"}
    return {"score": 1, "structure": "flat"}


def score_s14_basis(fut: dict | None) -> dict:
    """
    fut keys: spot, near_fut, far_fut, dte, rollover_pct, is_expiry_week,
              basis_history (list), price_up (bool).
    """
    if not fut or not fut.get("spot") or not fut.get("near_fut"):
        return _r("S14", 0, "ACTIVE", 3, "NO_DATA", dq="MISSING")
    c1 = s14_c1_basis(fut["spot"], fut["near_fut"], fut.get("dte", 7))
    c2 = s14_c2_roc(fut.get("basis_history"), fut.get("price_up", True))
    c3 = s14_c3_rollover(fut.get("rollover_pct"), fut.get("is_expiry_week", False))
    c4 = s14_c4_term(fut["near_fut"], fut.get("far_fut"))
    total = max(0, min(config.MAX_SCORES["S14"], c1["score"] + c2["score"] + c3["score"] + c4["score"]))
    return _r("S14", total, "ACTIVE", 3, "BASIS",
              {"c1_basis": c1, "c2_roc": c2, "c3_rollover": c3, "c4_term": c4})


# =============================================================================
# BLOCK J12 - S15 F&O PARTICIPANT POSITIONING (/12)  [SHADOW]
# C1 FII index futures NET(/4) | C2 FII options writing(/3)
# C3 client contrarian(/3) | C4 pro/DII confirm(/2)
# =============================================================================
def score_s15_participant(part: pd.DataFrame | None, prev_part: pd.DataFrame | None = None) -> dict:
    if part is None or part.empty:
        return _r("S15", 0, "SHADOW", 5, "NO_DATA", dq="MISSING")

    def _row(df, key):
        m = df[df["client_type"].astype(str).str.upper().str.contains(key, na=False)]
        return m.iloc[0] if not m.empty else None

    fii = _row(part, "FII")
    client = _row(part, "CLIENT")
    pro = _row(part, "PRO")
    dii = _row(part, "DII")
    cfg = config.S15_PARTICIPANT

    c1 = c2 = c3 = c4 = 0
    fii_net = None
    if fii is not None and "future_index_long" in fii and "future_index_short" in fii:
        fii_net = float(fii["future_index_long"]) - float(fii["future_index_short"])
        adding = True
        if prev_part is not None:
            pf = _row(prev_part, "FII")
            if pf is not None:
                prev_net = float(pf["future_index_long"]) - float(pf["future_index_short"])
                adding = fii_net > prev_net
        if fii_net > 0 and adding:
            c1 = 4
        elif fii_net < 0 and not adding:
            c1 = 3  # short but covering
        elif fii_net > 0:
            c1 = 2
        else:
            c1 = 0  # short and adding

    if fii is not None and "option_index_put_long" in fii:
        # Writing puts (short puts) = bullish; writing calls = bearish (proxy via long legs).
        put_long = float(fii.get("option_index_put_long", 0) or 0)
        call_long = float(fii.get("option_index_call_long", 0) or 0)
        c2 = 3 if call_long > put_long else 0

    if client is not None and fii_net is not None and "future_index_long" in client:
        client_net = float(client["future_index_long"]) - float(client["future_index_short"])
        if client_net > 0 and fii_net < 0:
            c3 = 3  # best contrarian: client long, FII short

    if pro is not None and dii is not None and fii_net is not None:
        pro_net = float(pro.get("future_index_long", 0)) - float(pro.get("future_index_short", 0))
        if (pro_net > 0) == (fii_net > 0):
            c4 = cfg["pro_dii_alignment_bonus"]

    total = min(cfg["max_score"], c1 + c2 + c3 + c4)
    return _r("S15", total, "SHADOW", 5, "PARTICIPANT",
              {"fii_fut_net": fii_net, "c1": c1, "c2": c2, "c3": c3, "c4": c4},
              "SHADOW: collecting 24-36 months before thresholds firm up")


# =============================================================================
# BLOCK J13 - OPTIONS-ENGINE AGGREGATE
# WHAT: One call returns S12, S13, S14, S15 for the pipeline (H7).
# =============================================================================
def score_options_block(option_chain: pd.DataFrame, *, spot=None, vix=None,
                        event_week=False, price_change=None, pcr_history=None,
                        futures_info=None, participant=None, prev_participant=None) -> dict:
    return {
        "S12": score_s12_options(option_chain, spot, vix, event_week, price_change, pcr_history),
        "S13": score_s13_iv(option_chain),
        "S14": score_s14_basis(futures_info),
        "S15": score_s15_participant(participant, prev_participant),
    }
