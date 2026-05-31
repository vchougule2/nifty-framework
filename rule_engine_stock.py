"""
rule_engine_stock.py - Stock-side Scoring Engine (Blocks D1-D12)
================================================================
WHAT:   Scores rules S1-S11 for a single stock from its OHLCV(+delivery) history,
        then a composite + a watchlist scan.
WHY:    These are the SMC / volume / flow / breadth rules that decide a per-stock
        setup. Tier-1 gates (S1, S5) can hard-block; Tier-2/3 accumulate score.
IMPACT: Output feeds the precedence engine (rule_engine_macro) which fuses these
        with options (S12-S15) and macro modifiers (S16-S17) for the final grade.

Block map (logical, matches H4 "score S1-S11"):
    D1 S1 Trend Gate | D2 S2 OB+PA | D3 S3 FVG | D4 S4 Sweep | D5 S5 BOS/CHoCH
    D6 S6 Volume/Whale | D7 S7 FII/DII | D8 S10 Breadth | D9 S8 Sector(SHADOW)
    D10 S11 Risk(SHADOW) | D11 S9 Event | D12 composite_stock_score + score_universe

All thresholds come from config.py (B3-B13). Every function returns the standard
result dict: {rule, score, max, mode, tier, label, components, notes, data_quality}.
"""

from __future__ import annotations

from datetime import date, datetime
import numpy as np
import pandas as pd

try:
    from . import config
except ImportError:
    import config


# =============================================================================
# INDICATOR HELPERS (shared by D1-D6)
# WHAT: EMA / ADX / RSI / ATR + swing detection. WHY: SMC rules need structure.
# =============================================================================
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high, low, close, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def adx(high, low, close, period: int = 14) -> pd.Series:
    """Classic Wilder ADX (simplified rolling-mean smoothing)."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = pd.concat([(high - low),
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.rolling(period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(period).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(period).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()


def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> pd.DataFrame:
    """Mark fractal swing highs/lows (a high/low surrounded by lower/higher bars)."""
    highs, lows = df["high"].values, df["low"].values
    n = len(df)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        if highs[i] == max(highs[i - left:i + right + 1]):
            is_high[i] = True
        if lows[i] == min(lows[i - left:i + right + 1]):
            is_low[i] = True
    out = df.copy()
    out["swing_high"] = is_high
    out["swing_low"] = is_low
    return out


def _result(rule, score, mode, tier, label="", components=None, notes="",
            dq="OK", passed=None, direction=None) -> dict:
    d = {
        "rule": rule, "score": round(float(score), 2),
        "max": config.MAX_SCORES.get(rule),
        "mode": mode, "tier": tier, "label": label,
        "components": components or {}, "notes": notes, "data_quality": dq,
    }
    if passed is not None:
        d["passed"] = passed
    if direction is not None:
        d["direction"] = direction
    return d


def _enough(df: pd.DataFrame, n: int) -> bool:
    return df is not None and len(df) >= n


# =============================================================================
# BLOCK D1 - S1 TREND GATE  (HARD GATE)
# Logic: EMA21>50>200 & ADX>20 => PASS long ; EMA21<50<200 & ADX>20 => PASS short
#        else FAIL -> HARD BLOCK (no trade). Blocks ~40% counter-trend setups.
# =============================================================================
def score_s1_gate(df: pd.DataFrame) -> dict:
    cfg = config.S1_GATE
    if not _enough(df, cfg["ema_slow"]):
        return _result("S1", 0, "ACTIVE", 1, "INSUFFICIENT_HISTORY",
                       notes="need >=200 daily bars", dq="DEGRADED", passed=False)
    c = df["close"]
    e_f, e_m, e_s = ema(c, cfg["ema_fast"]).iloc[-1], ema(c, cfg["ema_medium"]).iloc[-1], ema(c, cfg["ema_slow"]).iloc[-1]
    adx_val = adx(df["high"], df["low"], df["close"]).iloc[-1]
    adx_ok = bool(adx_val >= cfg["adx_min"]) if not np.isnan(adx_val) else False
    comp = {"ema21": round(e_f, 2), "ema50": round(e_m, 2), "ema200": round(e_s, 2),
            "adx": None if np.isnan(adx_val) else round(adx_val, 1)}
    if e_f > e_m > e_s and adx_ok:
        return _result("S1", 1, "ACTIVE", 1, "PASS", comp, "bullish alignment",
                       passed=True, direction="LONG")
    if e_f < e_m < e_s and adx_ok:
        return _result("S1", 1, "ACTIVE", 1, "PASS", comp, "bearish alignment",
                       passed=True, direction="SHORT")
    return _result("S1", 0, "ACTIVE", 1, "FAIL", comp,
                   "EMA not aligned or ADX weak -> HARD BLOCK", passed=False, direction="NONE")


# =============================================================================
# BLOCK D2 - S2 OB QUALITY + PA CONFIRMATION (/12)
# A OB Quality(/7): type(extreme3/decisive2/normal1)+freshness(0-5:2,6-10:1)+vol>1.5x:1+weekly:1
# B PA Confirm(/5): bounce >1%:3 / 0.5-1%:2 / <0.5%:1 + wick:1 + engulfing:1
# =============================================================================
def score_s2_ob(df: pd.DataFrame, direction: str = "LONG") -> dict:
    cfg = config.S2_OB
    if not _enough(df, 25):
        return _result("S2", 0, "ACTIVE", 2, "NT", notes="short history", dq="DEGRADED")
    look = df.tail(20).reset_index(drop=True)
    body = (look["close"] - look["open"]).abs()
    rng = (look["high"] - look["low"]).replace(0, np.nan)
    body_pct = (body / rng * 100).fillna(0)
    vol_avg = df["volume"].tail(20).mean()

    # Candidate OB = last demand candle (down candle preceding up-move) for LONG.
    idx = None
    for i in range(len(look) - 2, 0, -1):
        is_demand = look["close"].iloc[i] < look["open"].iloc[i] if direction == "LONG" \
            else look["close"].iloc[i] > look["open"].iloc[i]
        moved = look["close"].iloc[-1] > look["close"].iloc[i] if direction == "LONG" \
            else look["close"].iloc[-1] < look["close"].iloc[i]
        if is_demand and moved:
            idx = i
            break
    if idx is None:
        return _result("S2", 0, "ACTIVE", 2, "NT", notes="no order block found")

    bpct = body_pct.iloc[idx]
    ob_type = 3 if bpct >= 70 else 2 if bpct >= cfg["ob_body_pct_min"] else 1
    freshness_age = (len(look) - 1) - idx
    fresh = 2 if freshness_age <= 5 else 1 if freshness_age <= 10 else 0
    vol_pts = 1 if (vol_avg and look["volume"].iloc[idx] > cfg["ob_vol_multiplier"] * vol_avg) else 0
    weekly_pts = 1 if bpct >= 80 else 0  # proxy for "sits at weekly level"
    ob_quality = min(7, ob_type + fresh + vol_pts + weekly_pts)

    ob_level = look["low"].iloc[idx] if direction == "LONG" else look["high"].iloc[idx]
    last_close = look["close"].iloc[-1]
    bounce_pct = abs(last_close - ob_level) / ob_level * 100
    pa_bounce = 3 if bounce_pct >= cfg["pa_bounce_strong_pct"] else 2 if bounce_pct >= cfg["pa_bounce_moderate_pct"] else 1
    last = look.iloc[-1]
    last_rng = max(last["high"] - last["low"], 1e-9)
    lower_wick = (min(last["open"], last["close"]) - last["low"]) / last_rng * 100
    wick_pts = 1 if lower_wick >= cfg["pa_wick_rejection_pct"] else 0
    prev = look.iloc[-2]
    engulf = 1 if (last["close"] > last["open"] and last["close"] > prev["high"]) else 0
    pa_confirm = min(5, pa_bounce + wick_pts + engulf)

    score = ob_quality + pa_confirm
    label = ("A+" if score >= cfg["grade_A_plus"] else "A" if score >= cfg["grade_A"]
             else "B" if score >= cfg["grade_B"] else "C" if score >= cfg["grade_C"] else "NT")
    return _result("S2", score, "ACTIVE", 2, label,
                   {"ob_quality": ob_quality, "pa_confirm": pa_confirm,
                    "ob_type": ob_type, "freshness_age": freshness_age,
                    "bounce_pct": round(bounce_pct, 2)},
                   f"OB at {round(ob_level,2)}")


# =============================================================================
# BLOCK D3 - S3 FVG QUALITY FILTER (/8)
# C1 strength: >0.8%+vol=4 / large no-vol=3 / 0.3-0.8%=2 / <0.3%=0(ignored)
# C2 OB confluence: full=2 / partial=1 / none=0 (standalone FVG -> IGNORED)
# C3 freshness: untested=2 / partial=1 / filled=-1 (negative -> INVALIDATE)
# =============================================================================
def score_s3_fvg(df: pd.DataFrame, ob_level: float | None = None, direction: str = "LONG") -> dict:
    cfg = config.S3_FVG
    if not _enough(df, 10):
        return _result("S3", 0, "ACTIVE", 3, "NT", notes="short history", dq="DEGRADED")
    look = df.tail(20).reset_index(drop=True)
    vol_avg = df["volume"].tail(20).mean()
    fvg = None  # (gap_low, gap_high, idx, gap_pct, vol_ok)
    for i in range(2, len(look)):
        if direction == "LONG":  # bullish FVG: low[i] > high[i-2]
            if look["low"].iloc[i] > look["high"].iloc[i - 2]:
                lo, hi = look["high"].iloc[i - 2], look["low"].iloc[i]
                gpct = (hi - lo) / lo * 100
                vol_ok = vol_avg and look["volume"].iloc[i - 1] > vol_avg
                fvg = (lo, hi, i, gpct, vol_ok)
        else:  # bearish FVG: high[i] < low[i-2]
            if look["high"].iloc[i] < look["low"].iloc[i - 2]:
                hi, lo = look["low"].iloc[i - 2], look["high"].iloc[i]
                gpct = (hi - lo) / hi * 100
                vol_ok = vol_avg and look["volume"].iloc[i - 1] > vol_avg
                fvg = (lo, hi, i, gpct, vol_ok)
    if fvg is None:
        return _result("S3", 0, "ACTIVE", 3, "NONE", notes="no FVG detected")

    lo, hi, i, gpct, vol_ok = fvg
    if gpct < cfg["min_gap_pct"]:
        return _result("S3", 0, "ACTIVE", 3, "IGNORED", {"gap_pct": round(gpct, 2)},
                       "small FVG ignored")
    strength = 4 if (gpct >= cfg["large_gap_pct"] and vol_ok) else 3 if gpct >= cfg["large_gap_pct"] else 2

    # Confluence with S2 order block.
    if ob_level is None:
        conf = 0
        standalone = True
    else:
        standalone = False
        if lo <= ob_level <= hi:
            conf = cfg["ob_confluence_bonus"]      # full overlap
        elif abs(ob_level - (lo + hi) / 2) / ob_level * 100 < 1.0:
            conf = 1                                # partial
        else:
            conf = 0

    # Freshness: has price traded back into the gap since it formed?
    after = look.iloc[i + 1:]
    if after.empty:
        fresh = cfg["freshness_untested"]
    elif (after["low"] <= hi).any() and (after["high"] >= lo).any():
        # touched: fully filled if crossed entirely, else partial
        fresh = cfg["freshness_filled"] if (after["low"] <= lo).any() else 1
    else:
        fresh = cfg["freshness_untested"]

    score = max(-1, min(cfg["max_score"], strength + conf + fresh))
    if standalone and conf == 0:
        return _result("S3", 0, "ACTIVE", 3, "IGNORED",
                       {"gap_pct": round(gpct, 2), "strength": strength},
                       "standalone FVG (no OB confluence) -> ignored")
    label = "INVALIDATE" if score < 0 else "OK"
    return _result("S3", max(0, score) if score >= 0 else score, "ACTIVE", 3, label,
                   {"strength": strength, "confluence": conf, "freshness": fresh,
                    "gap_pct": round(gpct, 2)},
                   "negative score invalidates setup" if score < 0 else "")


# =============================================================================
# BLOCK D4 - S4 LIQUIDITY SWEEP & STOP HUNT (/11)
# C1 ID(/3) swingH/L=3, equalH/L=2, trendline=1
# C2 status(/3) swept+reversed=3, swept no-rev=2, partial=1, NOT swept=0(WAIT)
# C3 depth(/3) deep>0.5%+wick=3, deep closed=2, shallow=1
# C4 inducement(/2) detected=2
# =============================================================================
def score_s4_sweep(df: pd.DataFrame, direction: str = "LONG") -> dict:
    cfg = config.S4_SWEEP
    if not _enough(df, 25):
        return _result("S4", 0, "ACTIVE", 2, "NT", notes="short history", dq="DEGRADED")
    sw = swing_points(df.tail(40).reset_index(drop=True))
    last = sw.iloc[-1]
    # Reference liquidity pool = most recent swing low (LONG) / high (SHORT) before last bar.
    pool_idx = None
    col = "swing_low" if direction == "LONG" else "swing_high"
    for i in range(len(sw) - 3, 0, -1):
        if sw[col].iloc[i]:
            pool_idx = i
            break
    if pool_idx is None:
        return _result("S4", 0, "ACTIVE", 2, "WAIT", notes="no liquidity pool identified")

    pool = sw["low"].iloc[pool_idx] if direction == "LONG" else sw["high"].iloc[pool_idx]
    c1_id = 3  # treat fractal swing as primary liquidity (swing H/L)

    if direction == "LONG":
        pierced = last["low"] < pool
        reversed_back = last["close"] > pool
        depth_pct = (pool - last["low"]) / pool * 100 if pierced else 0
        wick = (min(last["open"], last["close"]) - last["low"]) / max(last["high"] - last["low"], 1e-9)
    else:
        pierced = last["high"] > pool
        reversed_back = last["close"] < pool
        depth_pct = (last["high"] - pool) / pool * 100 if pierced else 0
        wick = (last["high"] - max(last["open"], last["close"])) / max(last["high"] - last["low"], 1e-9)

    if pierced and reversed_back:
        c2 = 3
    elif pierced:
        c2 = 2
    else:
        c2 = 0  # NOT swept -> WAIT condition

    if depth_pct >= cfg["deep_sweep_pct"] and wick >= 0.4:
        c3 = 3
    elif depth_pct >= cfg["deep_sweep_pct"]:
        c3 = 2
    elif depth_pct >= cfg["shallow_sweep_pct"]:
        c3 = 1
    else:
        c3 = 0

    # Inducement: a minor swing in the opposite direction just before the sweep.
    induce = 0
    window = sw.iloc[max(0, pool_idx - cfg["inducement_lookback"]):pool_idx]
    if direction == "LONG" and window["swing_high"].any():
        induce = 2
    if direction == "SHORT" and window["swing_low"].any():
        induce = 2

    score = min(cfg["max_score"], c1_id + c2 + c3 + induce)
    label = "WAIT" if c2 == 0 else "SWEPT"
    return _result("S4", score, "ACTIVE", 2, label,
                   {"id": c1_id, "status": c2, "depth": c3, "inducement": induce,
                    "depth_pct": round(depth_pct, 2), "pool": round(pool, 2)},
                   "unswept liquidity = WAIT (semi-gate)" if c2 == 0 else "")


# =============================================================================
# BLOCK D5 - S5 BOS & CHoCH SOFT GATE (/10)
# C1 shift(/4) CHoCH+vol=4, CHoCH=3, BOS=2, none=0
# C2 quality(/3) impulsive=3, gradual=2, wick=1, failed=-1(EXIT)
# C3 MTF(/3) all aligned=3, 2of3=2, LTF=1, conflict=0
# SOFT GATE: 0=HARD BLOCK ; 1-3 only with A+ S2(>=10) & S4(>=9) [enforced in composite]
# =============================================================================
def score_s5_bos(df: pd.DataFrame, direction: str = "LONG") -> dict:
    cfg = config.S5_BOS
    if not _enough(df, 30):
        return _result("S5", 0, "ACTIVE", 1, "INSUFFICIENT", notes="short history",
                       dq="DEGRADED", passed=False)
    sw = swing_points(df.tail(40).reset_index(drop=True))
    highs = sw[sw["swing_high"]]["high"].tail(3).tolist()
    lows = sw[sw["swing_low"]]["low"].tail(3).tolist()
    last_close = sw["close"].iloc[-1]
    vol_avg = df["volume"].tail(20).mean()
    vol_now = sw["volume"].iloc[-1]
    vol_strong = bool(vol_avg and vol_now > 1.3 * vol_avg)

    c1 = 0
    structure = "none"
    if direction == "LONG":
        if highs and last_close > max(highs):
            # break of prior high in uptrend = BOS; if it follows a downtrend = CHoCH
            chochs = bool(lows and len(lows) >= 2 and lows[-1] > lows[-2])
            c1 = (4 if vol_strong else 3) if chochs else 2
            structure = "CHoCH" if chochs else "BOS"
    else:
        if lows and last_close < min(lows):
            chochs = bool(highs and len(highs) >= 2 and highs[-1] < highs[-2])
            c1 = (4 if vol_strong else 3) if chochs else 2
            structure = "CHoCH" if chochs else "BOS"

    # Quality of the breaking move.
    body = abs(sw["close"].iloc[-1] - sw["open"].iloc[-1])
    rng = max(sw["high"].iloc[-1] - sw["low"].iloc[-1], 1e-9)
    body_ratio = body / rng
    if c1 == 0:
        c2 = 0
    elif body_ratio >= 0.6 and vol_strong:
        c2 = 3
    elif body_ratio >= 0.4:
        c2 = 2
    else:
        c2 = 1

    # MTF coherence proxy: agreement of short/medium/long EMAs slope.
    c = df["close"]
    slopes = [ema(c, 9).diff().iloc[-1], ema(c, 21).diff().iloc[-1], ema(c, 50).diff().iloc[-1]]
    agree = sum((s > 0) if direction == "LONG" else (s < 0) for s in slopes)
    c3 = {3: 3, 2: 2, 1: 1, 0: 0}[agree]

    score = max(-1, min(cfg["max_score"], c1 + c2 + c3))
    passed = score > cfg["hard_block_score"]
    return _result("S5", max(0, score), "ACTIVE", 1, structure.upper() or "NONE",
                   {"shift": c1, "quality": c2, "mtf": c3, "structure": structure},
                   "score 0 -> HARD BLOCK; 1-3 -> needs A+ S2 & strong S4",
                   passed=passed)


# =============================================================================
# BLOCK D6 - S6 VOLUME & DELIVERY WHALE FORMULA (/15)
# C1 vol vs 5/22/66/132 avgs(/3) | C2 delivery%(/3) | C3 pattern climax/dryup(/2)
# C4 ROC both rising(/3, delivery ROC x1.5) | C5 whale: trade-size + vol^/delval^/trades v (/4)
# =============================================================================
def score_s6_volume(df: pd.DataFrame) -> dict:
    cfg = config.S6_VOLUME
    if not _enough(df, 30):
        return _result("S6", 0, "ACTIVE", 2, "Hollow", notes="short history", dq="DEGRADED")
    vol = df["volume"]
    today_vol = vol.iloc[-1]
    avgs = {k: vol.tail(p).mean() for k, p in cfg["avg_periods"].items()}
    above = sum(today_vol > a for a in avgs.values() if a and not np.isnan(a))
    c1 = 3 if above == 4 else 2 if above == 3 else 1 if above == 2 else 0

    dq = "OK"
    deliv = df["deliv_pct"].iloc[-1] if "deliv_pct" in df and not pd.isna(df["deliv_pct"].iloc[-1]) else None
    if deliv is None:
        c2 = 0
        dq = "DEGRADED"
    else:
        c2 = (3 if deliv >= cfg["delivery_strong"] else 2 if deliv >= cfg["delivery_moderate"]
              else 1 if deliv >= cfg["delivery_weak"] else 0)

    vavg = avgs["1M"] or 1
    ratio = today_vol / vavg if vavg else 0
    c3 = 2 if ratio >= cfg["climax_threshold"] else 1 if ratio <= cfg["dryup_threshold"] else 0

    vol_roc = vol.iloc[-1] - vol.iloc[-1 - cfg["vol_roc_lookback"]] if len(vol) > cfg["vol_roc_lookback"] else 0
    if "deliv_qty" in df and df["deliv_qty"].notna().sum() > cfg["del_roc_lookback"]:
        dser = df["deliv_qty"].dropna()
        del_roc = (dser.iloc[-1] - dser.iloc[-1 - cfg["del_roc_lookback"]]) * cfg["del_roc_weight"]
    else:
        del_roc = 0
    both_rising = vol_roc > 0 and del_roc > 0
    c4 = 3 if both_rising else 2 if (vol_roc > 0 or del_roc > 0) else 0

    # C5 Whale formula: large average trade size + accumulation footprint.
    c5 = 0
    if "trades" in df and not pd.isna(df["trades"].iloc[-1]) and df["trades"].iloc[-1] > 0:
        ats_today = today_vol / df["trades"].iloc[-1]
        ats_avg = (vol.tail(22) / df["trades"].tail(22).replace(0, np.nan)).mean()
        if ats_avg and ats_today > cfg["avg_trade_size_multiplier"] * ats_avg:
            c5 += 2
        # vol^ + delivery-value^ + trades v  (classic quiet accumulation)
        if (vol_roc > 0 and del_roc > 0 and
                df["trades"].iloc[-1] < df["trades"].tail(5).mean()):
            c5 += 2

    score = min(cfg["max_score"], c1 + c2 + c3 + c4 + c5)
    tier = ("Whale" if score >= cfg["tier_whale"] else "Strong" if score >= cfg["tier_strong"]
            else "Moderate" if score >= cfg["tier_moderate"] else "Weak" if score >= cfg["tier_weak"]
            else "Hollow")
    return _result("S6", score, "ACTIVE", 2, tier,
                   {"vol_vs_avg": c1, "delivery": c2, "pattern": c3, "roc": c4, "whale": c5,
                    "deliv_pct": deliv, "vol_ratio": round(ratio, 2)},
                   dq=dq)


# =============================================================================
# BLOCK D7 - S7 FII/DII FLOW (/12)
# C1 FII net(/4) buy>2KCr=4 / sell>10KCr(extreme contrarian)=4 / sell>5KCr=3
# C2 DII absorption(/2) DII>=1.2x FII sell | C3 gross(/3) B/S>1.1 | C4 ROC+flip(/3)
# =============================================================================
def score_s7_fii(fii_dii: pd.DataFrame, history: pd.DataFrame | None = None) -> dict:
    if fii_dii is None or fii_dii.empty:
        return _result("S7", 0, "ACTIVE", 3, "NO_DATA", dq="MISSING")
    f = fii_dii[fii_dii["category"].astype(str).str.contains("FII|FPI", case=False, na=False)]
    d = fii_dii[fii_dii["category"].astype(str).str.contains("DII", case=False, na=False)]
    fii_net = float(f["net"].iloc[0]) if not f.empty and not pd.isna(f["net"].iloc[0]) else 0.0
    dii_net = float(d["net"].iloc[0]) if not d.empty and not pd.isna(d["net"].iloc[0]) else 0.0
    cfg = config.S7_FII

    if fii_net > 2000:
        c1 = 4
    elif fii_net <= cfg["extreme_sell_cr"]:
        c1 = 4  # extreme contrarian
    elif fii_net <= cfg["contrarian_trigger_cr"]:
        c1 = 3
    elif fii_net < 0:
        c1 = 1
    else:
        c1 = 2

    c2 = 2 if (fii_net < 0 and dii_net >= cfg["dii_absorption_ratio"] * abs(fii_net)) else 0

    fbuy = float(f["buy"].iloc[0]) if not f.empty and not pd.isna(f["buy"].iloc[0]) else 0.0
    fsell = float(f["sell"].iloc[0]) if not f.empty and not pd.isna(f["sell"].iloc[0]) else 0.0
    bs_ratio = fbuy / fsell if fsell else 0
    c3 = 3 if bs_ratio > 1.1 else 1 if bs_ratio > 1.0 else 0

    c4 = 0
    if history is not None and "fii_net" in history and len(history) >= cfg["accumulation_days"] + 1:
        recent = history["fii_net"].tail(cfg["accumulation_days"] + 1).tolist()
        if recent[0] < 0 and recent[-1] > 0:
            c4 = 3  # sell -> buy flip (strongest)
        elif all(x > 0 for x in recent[-cfg["accumulation_days"]:]):
            c4 = 2  # multi-day accumulation
    score = min(config.MAX_SCORES["S7"], c1 + c2 + c3 + c4)
    return _result("S7", score, "ACTIVE", 3, "FLOW",
                   {"fii_net": fii_net, "dii_net": dii_net, "c1": c1, "c2": c2, "c3": c3, "c4": c4},
                   "single-day API: ROC/flip limited" if c4 == 0 else "")


# =============================================================================
# BLOCK D8 - S10 MARKET BREADTH (/12)  [market-wide, computed once]
# A/D(/3) | NH-NL(/3) | breadth thrust %>20EMA(/3) | %>200EMA(/3)
# =============================================================================
def score_s10_breadth(equity_df: pd.DataFrame, prev_close_col: str | None = None) -> dict:
    cfg = config.S10_BREADTH
    if equity_df is None or equity_df.empty:
        return _result("S10", 0, "ACTIVE", 3, "NO_DATA", dq="MISSING")
    df = equity_df.copy()
    # Advances / declines need prev close. UDiFF carries PrvsClsgPric sometimes.
    if "prev_close" in df:
        df["chg"] = df["close"] - df["prev_close"]
    elif "open" in df:
        df["chg"] = df["close"] - df["open"]  # intraday proxy
    else:
        return _result("S10", 0, "ACTIVE", 3, "NO_DATA", dq="DEGRADED")
    adv = int((df["chg"] > 0).sum())
    dec = int((df["chg"] < 0).sum())
    ad_ratio = adv / dec if dec else float(adv)
    c1 = 3 if ad_ratio >= cfg["ad_strong"] else 2 if ad_ratio >= cfg["ad_moderate"] else 1 if ad_ratio > cfg["ad_weak"] else 0

    # NH-NL proxy: stocks up >4% vs down >4% (true NH/NL needs 52w history).
    nh = int((df["chg"] / df["close"].replace(0, np.nan) * 100 > 4).sum())
    nl = int((df["chg"] / df["close"].replace(0, np.nan) * 100 < -4).sum())
    c2 = 3 if nh >= cfg["nh_nl_bullish"] * max(nl, 1) else 2 if nh > nl else 0

    pct_adv = adv / max(adv + dec, 1)
    c3 = 3 if pct_adv >= cfg["thrust_threshold"] else 2 if pct_adv >= 0.55 else 0

    # %>200EMA needs history per stock -> approximate via thrust (flagged DEGRADED).
    c4 = 3 if pct_adv >= cfg["pct_above_200ema_strong"] / 100 else 2 if pct_adv >= cfg["pct_above_200ema_moderate"] / 100 else 0

    score = min(cfg["max_score"], c1 + c2 + c3 + c4)
    return _result("S10", score, "ACTIVE", 3, "BREADTH",
                   {"adv": adv, "dec": dec, "ad_ratio": round(ad_ratio, 2),
                    "nh": nh, "nl": nl, "pct_adv": round(pct_adv, 2)},
                   "NH-NL & %>200EMA approximated (need 52w/200d history)", dq="DEGRADED")


# =============================================================================
# BLOCK D9 - S8 SECTOR RS + ROTATION (/12)  [SHADOW - tracked, not used]
# =============================================================================
def score_s8_sector(stock_ret_22d: float | None, sector_ret_22d: float | None,
                    nifty_ret_22d: float | None) -> dict:
    cfg = config.S8_SECTOR
    if None in (sector_ret_22d, nifty_ret_22d):
        return _result("S8", 0, "SHADOW", 5, "NO_DATA", dq="MISSING")
    rs_sector = sector_ret_22d - nifty_ret_22d
    rs_stock = (stock_ret_22d - sector_ret_22d) if stock_ret_22d is not None else 0
    # Rotation quadrant (RRG-style).
    if rs_sector > 0 and rs_stock > 0:
        stage, pts = "Leading", 12
    elif rs_sector > 0:
        stage, pts = "Weakening", 8
    elif rs_sector <= 0 and rs_stock > 0:
        stage, pts = "Improving", 6
    else:
        stage, pts = "Lagging", 2
    return _result("S8", min(cfg["max_score"], pts), "SHADOW", 5, stage,
                   {"rs_sector": round(rs_sector, 2), "rs_stock": round(rs_stock, 2)},
                   "SHADOW: needs 60-session validation")


# =============================================================================
# BLOCK D10 - S11 RISK REGIME (/15)  [SHADOW]
# =============================================================================
def score_s11_risk(vix: float | None, drawdown_pct: float | None = None,
                   avg_correlation: float | None = None) -> dict:
    cfg = config.S11_RISK
    if vix is None:
        return _result("S11", 0, "SHADOW", 5, "NO_DATA", dq="MISSING")
    lo, hi = cfg["vix_normal"]
    if vix < cfg["vix_low"]:
        regime, pts = "complacency", 8
    elif lo <= vix <= hi:
        regime, pts = "ideal", 15
    elif vix <= cfg["vix_elevated"]:
        regime, pts = "elevated", 9
    elif vix >= cfg["vix_crisis"]:
        regime, pts = "crisis", 2
    else:
        regime, pts = "high", 5
    if drawdown_pct is not None and drawdown_pct <= cfg["dd_crisis"]:
        pts = max(0, pts - 4)
    if avg_correlation is not None and avg_correlation >= cfg["high_corr"]:
        pts = max(0, pts - 2)
    return _result("S11", min(cfg["max_score"], pts), "SHADOW", 5, regime,
                   {"vix": vix, "drawdown": drawdown_pct, "corr": avg_correlation},
                   "SHADOW: needs 60-session validation")


# =============================================================================
# BLOCK D11 - S9 EVENT & CATALYST (/12)
# major aligned=4 wait-> here scaled to /12; no event(clean)=hi; against/multiple penalise
# Also returns event_week flag used by S12 max-pain weighting (J5).
# =============================================================================
def score_s9_event(target: date, direction: str = "LONG") -> dict:
    cfg = config.S9_EVENTS
    events = cfg.get("upcoming_events", []) or []
    near = []
    for ev in events:
        try:
            ed = datetime.strptime(ev.get("date"), "%Y-%m-%d").date()
            if abs((ed - target).days) <= 5:
                near.append(ev)
        except Exception:
            continue
    if not near:
        # No event in window = clean tape (blueprint: "No event (clean)=3" -> scale up).
        return _result("S9", 9, "ACTIVE", 3, "CLEAN", {"event_week": False},
                       "no catalyst within 5 sessions")
    impact = sum(cfg["event_types"].get(ev.get("type", ""), 1) for ev in near)
    aligned = all(ev.get("bias", direction).upper() == direction for ev in near)
    if len(near) > 1:
        base = 12 - 2 * len(near)  # multiple conflicting catalysts penalised
    elif aligned:
        base = min(12, 6 + impact)
    else:
        base = 0
    return _result("S9", max(0, min(cfg["max_score"], base)), "ACTIVE", 3,
                   "ALIGNED" if aligned else "AGAINST",
                   {"event_week": True, "events": [e.get("type") for e in near], "impact": impact},
                   "event week -> S12 max-pain weight x0.5")


# =============================================================================
# BLOCK D12 - COMPOSITE STOCK SCORE + UNIVERSE SCAN
# WHAT: Run S1-S11, apply weight profile, return per-stock subtotal + gates.
# WHY:  Final 117-grade is assembled by the precedence engine (adds S12+S14+modifiers).
# IMPACT: composite_stock_score() is the primary per-stock product; score_universe loops.
# =============================================================================
# Stock-only active max = full active max minus the options/futures rules (S12,S14).
STOCK_ACTIVE_MAX = config.ACTIVE_MAX_SCORE - config.MAX_SCORES["S12"] - config.MAX_SCORES["S14"]  # = 92


def composite_stock_score(symbol: str, history: pd.DataFrame, context: dict | None = None) -> dict:
    """
    context may carry: fii_dii (DF), fii_history (DF), breadth (precomputed S10 dict),
    vix (float), sector_ret_22d / nifty_ret_22d / stock_ret_22d, target (date).
    """
    context = context or {}
    target = context.get("target", date.today())

    s1 = score_s1_gate(history)
    direction = s1.get("direction", "LONG") if s1.get("passed") else "LONG"

    s2 = score_s2_ob(history, direction)
    ob_level = None
    if s2["components"].get("ob_quality") is not None and "OB at" in (s2.get("notes") or ""):
        try:
            ob_level = float(s2["notes"].split("OB at")[1].strip())
        except Exception:
            ob_level = None
    s3 = score_s3_fvg(history, ob_level, direction)
    s4 = score_s4_sweep(history, direction)
    s5 = score_s5_bos(history, direction)
    s6 = score_s6_volume(history)
    s7 = score_s7_fii(context.get("fii_dii"), context.get("fii_history"))
    s10 = context.get("breadth") or score_s10_breadth(context.get("equity_df", pd.DataFrame()))
    s8 = score_s8_sector(context.get("stock_ret_22d"), context.get("sector_ret_22d"), context.get("nifty_ret_22d"))
    s11 = score_s11_risk(context.get("vix"))
    s9 = score_s9_event(target, direction)

    rules = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6,
             "S7": s7, "S8": s8, "S9": s9, "S10": s10, "S11": s11}

    # ---- Gates ----
    gate_block = False
    gate_reasons = []
    if not s1.get("passed"):
        gate_block = True
        gate_reasons.append("S1 trend gate FAIL")
    if s5["score"] <= config.S5_BOS["hard_block_score"]:
        # Soft gate: weak structure allowed only with A+ S2 (>=10) AND strong S4 (>=9).
        if not (s2["score"] >= config.S5_BOS["s2_override_min"] and s4["score"] >= config.S5_BOS["s4_override_min"]):
            gate_block = True
            gate_reasons.append("S5 soft-gate FAIL (no A+ S2 & S4 override)")

    # ---- Weighted stock subtotal (S5 + S2,S3,S4,S6,S7,S9,S10 active scoring) ----
    weights = config.get_active_weight_profile()
    stock_rules = ["S5", "S2", "S3", "S4", "S6", "S7", "S9", "S10"]
    weighted = 0.0
    weighted_max = 0.0
    for r in stock_rules:
        w = weights.get(r, 1.0)
        weighted += max(0, rules[r]["score"]) * w
        weighted_max += config.MAX_SCORES[r] * w
    stock_pct = (weighted / weighted_max) if weighted_max else 0.0

    return {
        "symbol": symbol,
        "direction": direction,
        "gate_block": gate_block,
        "gate_reasons": gate_reasons,
        "rules": rules,
        "stock_weighted": round(weighted, 2),
        "stock_weighted_max": round(weighted_max, 2),
        "stock_pct": round(stock_pct, 4),
        "event_week": s9["components"].get("event_week", False),
        "shadow": {"S8": s8, "S11": s11},
    }


def score_universe(watchlist: list[str] | None = None, context_builder=None) -> list[dict]:
    """
    Loop the watchlist, build each stock's history (via data_fetcher) and score it.
    context_builder(symbol)->dict lets the caller inject shared market context.
    """
    try:
        from . import data_fetcher
    except ImportError:
        import data_fetcher
    watchlist = watchlist or config.WATCHLIST
    results = []
    for sym in watchlist:
        hist = data_fetcher.build_stock_history(sym, lookback=250)
        ctx = context_builder(sym) if context_builder else {}
        if hist.empty:
            results.append({"symbol": sym, "gate_block": True,
                            "gate_reasons": ["no history"], "stock_pct": 0.0})
            continue
        results.append(composite_stock_score(sym, hist, ctx))
    return results
