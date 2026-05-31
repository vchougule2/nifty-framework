"""
config.py - Master Configuration for Nifty Institutional Trading Framework
Version: 2.0.0
Date: 27 May 2026
Author: Vikram Chougule
Scope: B1-B22 blocks | Rules: S1-S19

Transcription note:
- Recreated from the scanned PDF `config.py.pdf`.
- A few heavily blurred characters were normalized into valid Python names/strings.
- Page 8 showed ACTIVE_MAX_SCORE as 117 even though S5 is listed as a gate;
  this file preserves that by adding S5 to the active max calculation.
"""

import os
from datetime import datetime, date

FRAMEWORK_VERSION = "2.0.0"
FRAMEWORK_DATE = "2026-05-27"

# =============================================================================
# BLOCK B1 - GENERAL SETTINGS
# WHAT:  Base paths, symbols, key levels
# WHY:   Centralized - change once, applies everywhere
# IMPACT: ALL files import paths from here
# =============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
CHARTS_DIR = os.path.join(OUTPUT_DIR, "charts")
LOGS_DIR = os.path.join(OUTPUT_DIR, "logs")
ML_DIR = os.path.join(BASE_DIR, "ml", "data")
EQUITY_DIR = os.path.join(DATA_DIR, "equity")
DELIVERY_DIR = os.path.join(DATA_DIR, "delivery")
FII_DIR = os.path.join(DATA_DIR, "fii_dii")
INDEX_DIR = os.path.join(DATA_DIR, "indices")
OPTIONS_DIR = os.path.join(DATA_DIR, "options")
FUTURES_DIR = os.path.join(DATA_DIR, "futures")
PARTICIPANT_DIR = os.path.join(DATA_DIR, "participant_oi")
INTERMARKET_DIR = os.path.join(DATA_DIR, "intermarket")

PRIMARY_INDEX = "NIFTY 50"

WATCHLIST = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC", "SBIN",
    "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
    "HCLTECH", "TITAN", "SUNPHARMA", "WIPRO", "ULTRACEMCO", "ONGC", "NTPC", "POWERGRID",
    "TATAMOTORS", "M&M", "TATASTEEL", "ADANIPORTS", "BAJAJFINSV", "TECHM", "NESTLEIND",
    "DIVISLAB", "GRASIM", "JSWSTEEL", "INDUSINDBK", "COALINDIA", "BPCL", "EICHERMOT",
    "DRREDDY", "CIPLA", "APOLLOHOSP", "HEROMOTOCO", "TATACONSUM", "SBILIFE", "BRITANNIA",
    "HINDALCO", "BAJAJ-AUTO", "BHEL", "SHRIRAMFIN", "DLF", "VEDL",
]

NIFTY_KEY_LEVELS = {
    "demand_zone": 22200,
    "supply_low": 26000,
    "supply_high": 26373,
    "52w_low": 22182.55,
    "ath": 26373.20,
}

# =============================================================================
# BLOCK B2 - NSE HOLIDAYS 2025-2026
# WHAT: Trading holiday list | WHY: Prevent 404 on backfill | IMPACT: Missing = failed downloads
# =============================================================================
NSE_HOLIDAYS_2025 = [
    "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10", "2025-04-14",
    "2025-04-18", "2025-05-01", "2025-08-15", "2025-08-27", "2025-10-02",
    "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
]

NSE_HOLIDAYS_2026 = [
    "2026-01-26", "2026-02-17", "2026-03-03", "2026-03-20", "2026-04-02",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-08-15", "2026-08-17",
    "2026-10-02", "2026-10-20", "2026-11-09", "2026-11-10", "2026-11-25",
    "2026-12-25",
]

NSE_HOLIDAYS = NSE_HOLIDAYS_2025 + NSE_HOLIDAYS_2026

# =============================================================================
# BLOCK B3 - S1 GATE: TREND FILTER
# WHAT: EMA alignment + ADX | WHY: HARD GATE | IMPACT: Blocks ~40% counter-trend setups
# =============================================================================
S1_GATE = {
    "ema_fast": 21,
    "ema_medium": 50,
    "ema_slow": 200,
    "adx_min": 20,
    "adx_strong": 30,
    "timeframes": ["daily", "weekly"],
}

# =============================================================================
# BLOCK B4 - S2: OB QUALITY + PA CONFIRMATION (/12)
# WHAT: Component A OB Quality(/7) + Component B PA Confirm(/5)
# WHY: Core SMC entry | IMPACT: Tier 2 Primary
# =============================================================================
S2_OB = {
    "max_score": 12,
    "ob_body_pct_min": 60,
    "ob_vol_multiplier": 1.5,
    "ob_freshness_max": 20,
    "pa_bounce_strong_pct": 1.0,
    "pa_bounce_moderate_pct": 0.5,
    "pa_wick_rejection_pct": 40,
    "grade_A_plus": 10,
    "grade_A": 8,
    "grade_B": 6,
    "grade_C": 4,
}

# =============================================================================
# BLOCK B5 - S3: FVG QUALITY FILTER (/8)
# WHAT: FVG Strength+Confluence+Freshness
# WHY: Entry refinement | IMPACT: Standalone FVG=IGNORED, negative=invalidate
# =============================================================================
S3_FVG = {
    "max_score": 8,
    "min_gap_pct": 0.3,
    "large_gap_pct": 0.8,
    "ob_confluence_bonus": 2,
    "freshness_untested": 2,
    "freshness_filled": -1,
    "small_candle_ignore": True,
}

# =============================================================================
# BLOCK B6 - S4: LIQUIDITY SWEEP & STOP HUNT (/11)
# WHAT: 4 components (ID/Sweep/Depth/Inducement)
# WHY: Deeper sweep=better R:R | IMPACT: Unswept=WAIT condition
# =============================================================================
S4_SWEEP = {
    "max_score": 11,
    "equal_hl_tolerance_pct": 0.15,
    "deep_sweep_pct": 0.5,
    "shallow_sweep_pct": 0.2,
    "inducement_lookback": 5,
    "unswept_wait": True,
}

# =============================================================================
# BLOCK B7 - S5: BOS & CHoCH SOFT GATE (/10)
# WHAT: Structure Shift+Quality+MTF Coherence
# WHY: 0=block, 1-3=need A+ S2+S4 | IMPACT: Failed BOS=EXIT
# =============================================================================
S5_BOS = {
    "max_score": 10,
    "hard_block_score": 0,
    "weak_zone_max": 3,
    "s2_override_min": 10,
    "s4_override_min": 9,
    "mtf_check": ["15min", "1H", "daily"],
    "failed_bos_exit": True,
}

# =============================================================================
# BLOCK B8 - S6: VOLUME & DELIVERY WHALE FORMULA (/15)
# WHAT: 5 components+block/bulk pre-filter+whale formula | WHY: Institutional proof
# IMPACT: Tiers: 13-15 Whale, 10-12 Strong, 7-9 Moderate, 4-6 Weak, 0-3 Hollow
# =============================================================================
S6_VOLUME = {
    "max_score": 15,
    "block_bulk_prefilter": True,
    "avg_periods": {"1W": 5, "1M": 22, "3M": 66, "6M": 132},
    "delivery_strong": 65,
    "delivery_moderate": 50,
    "delivery_weak": 35,
    "dryup_threshold": 0.5,
    "climax_threshold": 3.0,
    "vol_roc_lookback": 5,
    "del_roc_lookback": 5,
    "del_roc_weight": 1.5,
    "avg_trade_size_multiplier": 1.5,
    "whale_pattern": {"vol_up": True, "del_up": True, "value_up": True, "trades_down": True},
    "tier_whale": 13,
    "tier_strong": 10,
    "tier_moderate": 7,
    "tier_weak": 4,
    "tier_hollow": 0,
}

# =============================================================================
# BLOCK B9 - S7: FII/DII FLOW (/12)
# WHAT: Contrarian+Gross+ROC+Regime | WHY: FII sell>5KCr=68.2% bounce(119 sess)
# IMPACT: Tier 3
# =============================================================================
S7_FII = {
    "max_score": 12,
    "contrarian_trigger_cr": -5000,
    "extreme_sell_cr": -10000,
    "bounce_rate": 0.682,
    "dii_absorption_ratio": 1.2,
    "gross_spike": 1.5,
    "flow_roc_lookback": 5,
    "flip_detection": True,
    "accumulation_days": 3,
}

# =============================================================================
# BLOCK B10 - S8: SECTOR RS (/12) [SHADOW]
# WHAT: RS+Peer+Rotation | WHY: Needs 60-session validation | IMPACT: Scores tracked, not used
# =============================================================================
S8_SECTOR = {
    "max_score": 12,
    "mode": "SHADOW",
    "validation_needed": 60,
    "validation_done": 0,
    "rs_lookback": 22,
    "rs_outperform_pct": 2.0,
    "peer_group_size": 5,
    "rotation_stages": ["Leading", "Weakening", "Lagging", "Improving"],
}

# =============================================================================
# BLOCK B11 - S9: EVENT & CATALYST (/12)
# WHAT: Event types+impact scoring | WHY: Events break max pain(82%->34%)
# IMPACT: S12 C1 weight halved during events
# =============================================================================
S9_EVENTS = {
    "max_score": 12,
    "event_types": {
        "rbi_policy": 3,
        "budget": 4,
        "earnings": 2,
        "fo_expiry": 1,
        "fomc": 2,
        "geopolitical": 3,
    },
    "max_pain_event_weight": 0.5,
    "upcoming_events": [],
}

# =============================================================================
# BLOCK B12 - S10: MARKET BREADTH (/12)
# WHAT: A/D ratio+NH-NL+Thrust+%>200EMA | WHY: Broad participation confirms trend
# IMPACT: Tier 3
# =============================================================================
S10_BREADTH = {
    "max_score": 12,
    "ad_strong": 2.0,
    "ad_moderate": 1.5,
    "ad_weak": 0.6,
    "nh_nl_bullish": 2.0,
    "thrust_threshold": 0.7,
    "pct_above_200ema_strong": 70,
    "pct_above_200ema_moderate": 50,
}

# =============================================================================
# BLOCK B13 - S11: RISK REGIME (/15) [SHADOW]
# WHAT: VIX regime+Correlation+Drawdown | WHY: Needs 60-session validation | IMPACT: Shadow mode
# =============================================================================
S11_RISK = {
    "max_score": 15,
    "mode": "SHADOW",
    "validation_needed": 60,
    "vix_low": 13,
    "vix_normal": [14, 20],
    "vix_elevated": 22,
    "vix_crisis": 30,
    "high_corr": 0.8,
    "dd_alert": -5,
    "dd_crisis": -10,
}

# =============================================================================
# BLOCK B14 - SCORING TIERS & GRADES
# WHAT: Grade thresholds | WHY: Converts raw scores to actionable grades | IMPACT: Drives position sizing
# =============================================================================
GRADE_THRESHOLDS = {"A_PLUS": 0.85, "A": 0.70, "B": 0.55, "C": 0.40, "NO_TRADE": 0.0}

FRAMEWORK_GRADES = {
    "A+": (85, "Sniper Entry", 1.0),
    "A": (70, "Strong Setup", 0.75),
    "B": (55, "Moderate", 0.50),
    "C": (40, "Weak-Paper Only", 0.0),
    "NT": (0, "No Trade", 0.0),
}

# =============================================================================
# BLOCK B15 - CHART SETTINGS (Dark Theme)
# WHAT: Colors, fonts, DPI | WHY: Consistent professional dark theme | IMPACT: All charts use these
# =============================================================================
CHART = {
    "bg": "#1a1a2e",
    "panel": "#16213e",
    "bull": "#2ed573",
    "bear": "#ff4757",
    "gold": "#ffd700",
    "cyan": "#00d2d3",
    "grey": "#a4b0be",
    "orange": "#ffa502",
    "magenta": "#e056fd",
    "white": "#f1f2f6",
    "dpi": 120,
    "format": "png",
}

# =============================================================================
# BLOCK B16 - ALERT SETTINGS
# WHAT: Telegram+Google Sheets config | WHY: Auto notifications | IMPACT: Invalid tokens=silent failure
# =============================================================================
ALERTS = {
    "telegram": {
        "enabled": False,
        "bot_token": "YOUR_TOKEN",
        "chat_id": "YOUR_CHAT_ID",
        "max_per_day": 10,
    },
    "google_sheets": {
        "enabled": False,
        "sheet_id": "YOUR_SHEET_ID",
        "creds": "credentials.json",
    },
}

# =============================================================================
# BLOCK B17 - WEIGHT PROFILES
# WHAT: 3 profiles (Normal/Aggressive/Reversal) | WHY: Different market conditions
# IMPACT: Changes conviction scores
# =============================================================================
ACTIVE_WEIGHT_PROFILE = "NORMAL"

WEIGHT_PROFILES = {
    "NORMAL": {
        "S2": 1.0,
        "S3": 1.0,
        "S4": 1.0,
        "S5": 1.0,
        "S6": 1.0,
        "S7": 1.0,
        "S9": 1.0,
        "S10": 1.0,
        "S12": 1.0,
        "S14": 1.0,
    },
    "AGGRESSIVE": {
        "S2": 1.2,
        "S3": 1.0,
        "S4": 1.0,
        "S5": 1.0,
        "S6": 1.3,
        "S7": 0.8,
        "S9": 1.0,
        "S10": 0.8,
        "S12": 1.2,
        "S14": 1.0,
    },
    "REVERSAL_HUNTING": {
        "S2": 1.0,
        "S3": 0.8,
        "S4": 1.5,
        "S5": 1.3,
        "S6": 1.0,
        "S7": 1.5,
        "S9": 1.2,
        "S10": 0.7,
        "S12": 1.3,
        "S14": 1.0,
    },
}

# =============================================================================
# BLOCK B18 - ML MASTER SWITCH
# WHAT: ML ON/OFF + S13 control | WHY: ML needs 120+ days data
# IMPACT: ML1 always collects, ML4-6 only when enabled
# =============================================================================
ML_ENABLED = False
S13_ENABLED = False  # Parked until ML enabled (rule-based Sharpe only 0.12)

ML_CONFIG = {
    "min_days": 120,
    "retrain_days": 30,
    "collector_always_on": True,
    "model": "gradient_boosting",
    "validation_split": 0.2,
}

# =============================================================================
# BLOCK B19 - S12: OPTIONS CHAIN INTELLIGENCE (/15) [NEW]
# WHAT: Max Pain+PCR+OI Walls+Buildup | WHY: 82% event-free accuracy
# IMPACT: VIX gate(<18) + S9 event cross-check are MANDATORY
# =============================================================================
S12_OPTIONS = {
    "max_score": 15,
    "mode": "ACTIVE",
    # C1: Max Pain (/4) - VIX gated + S9 cross-checked
    "max_pain_tolerance_pts": 200,
    "max_pain_close_pts": 100,
    "max_pain_extended_pct": 2.0,
    "pain_asymmetry_bullish": 1.5,
    "pain_asymmetry_bearish": 0.7,
    "vix_gate": 18,
    "vix_high_score_cap": 2,
    "event_week_multiplier": 0.5,
    # C2: PCR (/3)
    "pcr_strong_bullish": 1.2,
    "pcr_bullish": 1.0,
    "pcr_bearish": 0.8,
    "pcr_strong_bearish": 0.7,
    "pcr_contrarian_high": 1.5,
    "pcr_contrarian_low": 0.6,
    "pcr_reversal_rate": 0.72,
    "pcr_5d_change_threshold": 0.1,
    "all_expiry_pcr_bullish": 1.0,
    "all_expiry_pcr_bearish": 0.7,
    # C3: OI Walls (/4)
    "oi_wall_zone_pct": 2.0,
    "support_wall_ratio": 1.5,
    "resistance_wall_ratio": 0.7,
    "oi_change_significant_pct": 50,
    "oi_change_explosive_pct": 200,
    # C4: OI Buildup (/4) - Short Covering reduced to 2 (backtest: 55% vs 78%)
    "buildup": {
        "long_buildup": 4,
        "short_covering": 2,
        "long_unwinding": 1,
        "short_buildup": 0,
    },
    "continuation_rates": {
        "long_buildup": 0.78,
        "short_covering": 0.55,
        "long_unwinding": 0.60,
        "short_buildup": 0.74,
    },
}

# =============================================================================
# BLOCK B20 - S14: FUTURES BASIS & ROLLOVER (/10) [NEW]
# WHAT: Basis vs FairValue+ROC+Rollover+TermStructure | WHY: 80%+ when basis+OI align
# IMPACT: Tier 3
# =============================================================================
S14_BASIS = {
    "max_score": 10,
    "mode": "ACTIVE",
    "risk_free_rate": 6.5,
    "div_yield": 1.2,
    "excess_basis_significant": 20,
    "excess_basis_mild": 5,
    "discount_threshold": -5,
    "basis_roc_lookback": 5,
    "basis_expanding_threshold": 3,
    "rollover_high": 80,
    "rollover_normal": 65,
    "rollover_low": 60,
    "rollover_last_n_days": 3,
    "contango_threshold_pts": 10,
    "backwardation_threshold_pts": -10,
}

# =============================================================================
# BLOCK B21 - S15: F&O PARTICIPANT POSITIONING (/12) [NEW-SHADOW]
# WHAT: FII Futures (PRIMARY)+Options+Client Contrarian+Pro/DII
# WHY: FII flip=500-1000pt move
# IMPACT: SHADOW - collecting data, needs 24-36 months before refining thresholds
# =============================================================================
S15_PARTICIPANT = {
    "max_score": 12,
    "mode": "SHADOW",
    "data_collection": True,
    "min_months": 24,
    "months_collected": 0,
    "fii_adding_longs_days": 3,
    "client_extreme_sigma": 2.0,
    "client_lookback": 30,
    "contrarian_cash_trigger_cr": 50000,
    "pro_dii_alignment_bonus": 2,
}

# =============================================================================
# BLOCK B22 - S16+S17: INTERMARKET & MACRO [NEW-MODIFIERS]
# WHAT: S16 Crude/DXY/Bonds/Global (/10) + S17 Currency/RBI/Gold (modifier)
# WHY: Macro drives sectors | IMPACT: S16>=8 -> +5% boost, S16<=4 -> -5% penalty
# =============================================================================
S16_INTERMARKET = {
    "max_score": 10,
    "mode": "MODIFIER",
    "boost_threshold": 8,
    "penalty_threshold": 4,
    "boost_pct": 0.05,
    "penalty_pct": -0.05,
    "crude_weekly_roc_bullish": -3.0,
    "crude_weekly_roc_bearish": 3.0,
    "dxy_monthly_roc_bearish_em": 2.0,
    "dxy_monthly_roc_bullish_em": -2.0,
    "yield_change_bullish_bps": -20,
    "yield_change_bearish_bps": 20,
    "yield_lookback": 10,
    "global_indices": ["SPX", "NI225", "HSI"],
}

S17_MACRO = {
    "mode": "MODIFIER",
    "usdinr_weak_threshold": 1.0,
    "usdinr_strong_threshold": -0.5,
    "rbi_stance": "accommodative",
    "gold_risk_off_roc": 3.0,
    "inr_weak_boost": ["TCS", "INFY", "HCLTECH", "WIPRO", "SUNPHARMA", "DRREDDY", "CIPLA"],
    "inr_strong_boost": ["HDFCBANK", "ICICIBANK", "SBIN", "MARUTI", "BAJFINANCE", "HINDUNILVR"],
    "crude_crash_boost": ["BPCL", "MARUTI", "TATAMOTORS", "ASIANPAINT"],
    "sector_override_bonus": 3,
}

# =============================================================================
# FRAMEWORK ARCHITECTURE - PRECEDENCE + MODES + SIGNAL AGREEMENT
# =============================================================================
TIER_PRECEDENCE = {
    "S1": {"tier": 1, "type": "GATE"},
    "S5": {"tier": 1, "type": "GATE"},
    "S2": {"tier": 2, "type": "SCORING"},
    "S4": {"tier": 2, "type": "SCORING"},
    "S6": {"tier": 2, "type": "SCORING"},
    "S12": {"tier": 2, "type": "SCORING"},
    "S3": {"tier": 3, "type": "SCORING"},
    "S7": {"tier": 3, "type": "SCORING"},
    "S9": {"tier": 3, "type": "SCORING"},
    "S10": {"tier": 3, "type": "SCORING"},
    "S14": {"tier": 3, "type": "SCORING"},
    "S16": {"tier": 4, "type": "MODIFIER"},
    "S17": {"tier": 4, "type": "MODIFIER"},
    "S8": {"tier": 5, "type": "SHADOW"},
    "S11": {"tier": 5, "type": "SHADOW"},
    "S15": {"tier": 5, "type": "SHADOW"},
    "S13": {"tier": 6, "type": "PARKED"},
    "S19": {"tier": 6, "type": "PARKED"},
}

GATE_RULES = ["S1", "S5"]
TIER2_PRIMARY = ["S2", "S4", "S6", "S12"]
TIER3_CONFIRMATION = ["S3", "S7", "S9", "S10", "S14"]
ACTIVE_SCORING_RULES = TIER2_PRIMARY + TIER3_CONFIRMATION
SHADOW_RULES = ["S8", "S11", "S15"]
MODIFIER_RULES = ["S16", "S17"]
PARKED_RULES = ["S13", "S19"]
ALL_RULES = GATE_RULES + ACTIVE_SCORING_RULES + MODIFIER_RULES + SHADOW_RULES + PARKED_RULES

RULE_MODES = {
    "S1": "ACTIVE",
    "S2": "ACTIVE",
    "S3": "ACTIVE",
    "S4": "ACTIVE",
    "S5": "ACTIVE",
    "S6": "ACTIVE",
    "S7": "ACTIVE",
    "S8": "SHADOW",
    "S9": "ACTIVE",
    "S10": "ACTIVE",
    "S11": "SHADOW",
    "S12": "ACTIVE",
    "S13": "PARKED",
    "S14": "ACTIVE",
    "S15": "SHADOW",
    "S16": "MODIFIER",
    "S17": "MODIFIER",
    "S18": "AUTO",
    "S19": "PARKED",
}

MAX_SCORES = {
    "S2": 12,
    "S3": 8,
    "S4": 11,
    "S5": 10,
    "S6": 15,
    "S7": 12,
    "S8": 12,
    "S9": 12,
    "S10": 12,
    "S11": 15,
    "S12": 15,
    "S14": 10,
    "S15": 12,
    "S16": 10,
}

# The screenshot states Active Max Score = 117. That equals active scoring rules (107) + S5 gate (10).
ACTIVE_MAX_SCORE = sum(MAX_SCORES[r] for r in ACTIVE_SCORING_RULES if r in MAX_SCORES) + MAX_SCORES.get("S5", 0)

SIGNAL_AGREEMENT = {
    "high": {"tier1": "ALL_PASS", "tier2_min": 3, "position_pct": 100},
    "moderate": {"tier1": "ALL_PASS", "tier2_min": 2, "tier3_min": 2, "position_pct": 75},
    "low": {"tier1": "ALL_PASS", "tier2_min": 1, "position_pct": 50},
    "no_trade": {"conditions": ["Tier1_FAIL", "OR_all_Tier2_negative"], "position_pct": 0},
}

# =============================================================================
# Convenience helpers
# =============================================================================
def ensure_directories() -> None:
    """Create the standard directory tree used by the framework."""
    for path in [
        DATA_DIR,
        OUTPUT_DIR,
        CHARTS_DIR,
        LOGS_DIR,
        ML_DIR,
        EQUITY_DIR,
        DELIVERY_DIR,
        FII_DIR,
        INDEX_DIR,
        OPTIONS_DIR,
        FUTURES_DIR,
        PARTICIPANT_DIR,
        INTERMARKET_DIR,
    ]:
        os.makedirs(path, exist_ok=True)


def get_active_weight_profile() -> dict:
    """Return the configured active weight profile."""
    return WEIGHT_PROFILES[ACTIVE_WEIGHT_PROFILE]


# =============================================================================
# END OF config.py - 22 Blocks (B1-B22)
# Active: S1-S7,S9-S10,S12,S14 | Shadow: S8,S11,S15 | Parked: S13,S19
# Active Max Score: 117 | Modifiers: S16,S17 | Auto: S18
# =============================================================================
