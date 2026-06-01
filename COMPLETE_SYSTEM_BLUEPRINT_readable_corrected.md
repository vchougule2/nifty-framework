# COMPLETE SYSTEM BLUEPRINT - Institutional Trading Framework v2.0

**Author:** Vikram Chougule  
**Date:** 27 May 2026  
**Version:** 2.0.0  
**Purpose:** Everything needed to build the system from scratch on any machine.

> **Conversion note:** Converted from a scanned, image-only PDF. Scan line numbers and visual artifacts were removed. I was able to read all 11 pages; arrows and punctuation were normalized for Markdown readability.

---

# PART 1: SYSTEM OVERVIEW

## Architecture - 4 Levels

```text
LEVEL 1: MARKET-WIDE -> Nifty Processor (G1-G4, N1-N18) + S10 + S12 + S14
LEVEL 2: SECTOR ROTATION -> S8 + S16 + S17
LEVEL 3: STOCK ANALYSIS -> All 19 rules scored per stock
LEVEL 4: ENTRY TIMING -> Precedence Engine (H9) -> Grade + Conviction
```

## Daily Pipeline

```text
H1: Init -> H2: Download(A1-A12) -> H3: Load(C1-C10) -> H4: Score S1-S11
-> H7: Score S12-S15 -> H8: Score S16-S18 -> H9: PRECEDENCE ENGINE
-> H5: Charts -> H6: Alerts -> ML1: Collect data
```

---

# PART 2: NIFTY PROCESSOR (ALL APPROVED)

- **G1-G4:** Gates (trend, VIX, hours, data quality)
- **N1-N3:** Trend (75% WR, 54-session) | **N4-N6:** Structure
- **N7-N9:** Volume & Breadth | **N10:** OI | **N11:** FII/DII (66.7% WR)
- **N12-N15:** Momentum/RSI/MTAL | **N16:** VIX (level + percentile + ROC)
- **N17:** Cross-Segment Flow | **N18:** =G2 (no duplication)

---

# PART 3: ALL 19 STOCK RULES (Complete Scoring Logic)

| Rule | Name | Max | Mode | Tier |
|---|---|---:|---|---:|
| S1 | Gate (Trend Filter) | Gate | ACTIVE | 1 |
| S2 | OB Quality + PA Confirmation | /12 | ACTIVE | 2 |
| S3 | FVG Quality Filter | /8 | ACTIVE | 3 |
| S4 | Liquidity Sweep & Stop Hunt | /11 | ACTIVE | 2 |
| S5 | BOS & CHoCH (Soft Gate) | /10 | ACTIVE | 1 |
| S6 | Volume & Delivery (Whale) | /15 | ACTIVE | 2 |
| S7 | FII/DII Flow Analysis | /12 | ACTIVE | 3 |
| S8 | Sector RS + Peer + Rotation | /12 | SHADOW | 5 |
| S9 | Event & Catalyst | /12 | ACTIVE | 3 |
| S10 | Market Breadth | /12 | ACTIVE | 3 |
| S11 | Risk Regime & Positioning | /15 | SHADOW | 5 |
| S12 | Options Chain Intelligence | /15 | ACTIVE | 2 |
| S13 | IV & Volatility | /10 | PARKED | 6 |
| S14 | Futures Basis & Rollover | /10 | ACTIVE | 3 |
| S15 | F&O Participant Positioning | /12 | SHADOW | 5 |
| S16 | Intermarket & Global | /10 | MODIFIER | 4 |
| S17 | Currency & Macro | /8 | MODIFIER | 4 |
| S18 | Composite Aggregator | Auto | AUTO | - |
| S19 | ML Signal Output | Reserved | PARKED | 6 |

**ACTIVE MAX SCORE = 117**

## S1: GATE - TREND FILTER

**Type:** HARD GATE (Tier 1) | Pass/Fail

- EMA 21 > 50 > 200 AND ADX > 20 -> PASS (bullish)
- EMA 21 < 50 < 200 AND ADX > 20 -> PASS (bearish/short)
- Else -> FAIL + HARD BLOCK (no trade)
- Timeframes: Daily + Weekly | Blocks ~40% of counter-trend setups

## S2: OB QUALITY + PA CONFIRMATION (/12)

**Type:** Tier 2 PRIMARY

- **Component A: OB Quality (/7):** OB Type (extreme=3, decisive=2, normal=1) + Freshness (0-5 sessions=2, 6-10=1, >10=0) + Volume > 1.5x avg=1 + Weekly level=1
- **Component B: PA Confirm (/5):** Bounce > 1%=3, 0.5-1%=2, <0.5%=1 + Wick rejection=1 + Engulfing=1
- **Grades:** A+ (>=10), A (>=8), B (>=6), C (>=4), NT (<4)

## S3: FVG QUALITY FILTER (/8)

**Type:** Tier 3 CONFIRMATION

- **C1 FVG Strength (/4):** Large > 0.8% + vol=4, Large no vol=3, Medium=2, Small=0 (IGNORED)
- **C2 FVG-OB Confluence (/2):** Full overlap=2, Partial=1, None=0
- **C3 Freshness (/2):** Untested=2, Partial filled=1, Fully filled=-1 (penalty)
- **Rules:** Standalone FVG=IGNORED. Negative score=INVALIDATE setup.

## S4: LIQUIDITY SWEEP & STOP HUNT (/11)

**Type:** Tier 2 PRIMARY

- **C1 Identification (/3):** Swing H/L=3, Equal H/L=2, Trendline=1
- **C2 Sweep Status (/3):** Swept + reversed=3, Swept no reversal=2, Partial=1, NOT swept=0 (WAIT!)
- **C3 Sweep Depth (/3):** Deep > 0.5% + wick=3, Deep closed beyond=2, Shallow=1
- **C4 Inducement (/2):** Detected=2, None=0
- **KEY:** Unswept liquidity = SEMI-GATE (WAIT condition). Deeper sweep = better R:R.

## S5: BOS & CHoCH - SOFT GATE (/10)

**Type:** Tier 1 GATE (Soft)

- **C1 Structure Shift (/4):** CHoCH + vol=4, CHoCH no vol=3, BOS=2, None=0
- **C2 Quality (/3):** Impulsive=3, Gradual=2, Wick only=1, Failed=-1 (EXIT SIGNAL!)
- **C3 MTF Coherence (/3):** All TF aligned=3, 2 of 3=2, LTF only=1, Conflicting=0
- **SOFT GATE:** Score 0=HARD BLOCK. Score 1-3=only with A+ S2 (>=10) AND S4 (>=9).

## S6: VOLUME & DELIVERY - WHALE FORMULA (/15)

**Type:** Tier 2 PRIMARY | MANDATORY block/bulk deal pre-filter

- **C1 Vol vs Averages (/3):** Above all 4 TFs (5d/22d/66d/132d)=3, 3 of 4=2, 2 of 4=1, below all=0
- **C2 Delivery% (/3):** >65%=3, 50-65%=2, 35-50%=1, <35%=0
- **C3 Vol Pattern (/2):** Climax (>3x)=2, Dry-up (<0.5x)=1, Normal=0
- **C4 ROC (/3):** Both rising=3, One rising=2, Both declining=0. Delivery ROC weighted 1.5x.
- **C5 WHALE FORMULA (/4):** AvgTradeSize > 1.5x 1M avg=2 + Vol↑DelValue↑Trades↓=2
- **Tiers:** 13-15=Whale, 10-12=Strong, 7-9=Moderate, 4-6=Weak, 0-3=Hollow

## S7: FII/DII FLOW (/12)

**Type:** Tier 3 | Backtest: 119 sessions, 68.2% contrarian bounce

- **C1 FII Net Direction (/4):** Buy > 2KCr=4, Sell > 10KCr (extreme contrarian)=4, Sell > 5KCr=3
- **C2 DII Absorption (/2):** DII >= 1.2x FII sell=2
- **C3 Gross Flow (/3):** B/S ratio > 1.1 + high turnover=3
- **C4 ROC + Flip (/3):** FII sell -> buy flip=3 (STRONGEST), Accumulation 3d=2

## S8: SECTOR RS + PEER + ROTATION (/12) [SHADOW]

Needs 60-session validation. RS lookback 22d. Rotation stages: Leading/Weakening/Lagging/Improving.

Peer comparison: Top 5 by market cap within sector.

## S9: EVENT & CATALYST (/12)

**Types:** RBI(3), Budget(4), Earnings(2), Expiry(1), FOMC(2), Geopolitical(3)

- Major catalyst aligned=4, No event (clean)=3, Minor aligned=2, Against=0, Multiple=-2
- **CRITICAL:** S12 max pain weight halved during event weeks (82% -> 34% accuracy)

## S10: MARKET BREADTH (/12)

- **A/D Ratio (/3):** >2.0=3, 1.5-2=2, <0.6=0
- **NH-NL (/3):** NH > 2x NL=3
- **Breadth Thrust (/3):** >70% above 20-EMA=3
- **% > 200 EMA (/3):** >70%=3, 50-70%=2

## S11: RISK REGIME (/15) [SHADOW]

Needs 60-session validation. VIX regimes: <13=complacency, 14-17=ideal, 17-22=elevated, >30=crisis.

Correlation regime, drawdown tracking.

## S12: OPTIONS CHAIN INTELLIGENCE (/15) - KEY RULE

**Type:** Tier 2 PRIMARY | Backtest: 82% event-free, 72% PCR extremes

**MANDATORY:** VIX gate (<18) + S9 event cross-check

- **C1 Max Pain (/4):** Below MP 2%=4, 1-2%=3, At MP=2, Above 1-2%=1, Above 2%=0, Trap=-1
  - VIX > 18 -> max score capped at 2. Event week -> weight x 0.5
  - Pain Asymmetry: >1.5=bullish skew, <0.7=bearish skew
- **C2 PCR (/3):** All bullish (current >1.2 + all >1.0 + rising)=3, Mixed=1, All bearish=0
  - CONTRARIAN: PCR > 1.5 or <0.6 = 72% reversal
- **C3 OI Walls (/4):** Put floor + Call ceiling weakening=4, Put floor=3, Balanced=2
  - OI Change% MORE important than absolute OI
- **C4 OI Buildup (/4):** Long Build Up=4 (78%), Short Covering=2 (55%), Long Unwinding=1, Short Buildup=0 (74%)

## S13: IV & VOLATILITY (/10) [PARKED]

PARKED until ML enabled. Rule-based Sharpe only 0.12. ML-enhanced: 0.78.

Components when active: IV Skew Direction, Term Structure, IV Rank, VIX-Stock Divergence.

## S14: FUTURES BASIS & ROLLOVER (/10)

**Type:** Tier 3 | Backtest: ~80%+ basis + OI alignment

- **C1 Basis vs FairValue (/3):** FV = Spot x (RFR - DivY) x (DTE/365), RFR=6.5%, DY=1.2%
  - Excess >20pts=3, 5-20=2, +/-5=1, <-5=0, <-20=-1
- **C2 Basis ROC (/3):** Expanding + price up=3, Stable + up=2, Contracting + up=1 (WEAK)
- **C3 Rollover% (/2):** >80%=2, 65-80%=1, <60%=0. Only last 3 sessions of expiry.
- **C4 Term Structure (/2):** Contango widening=2, Flat=1, Backwardation=0

## S15: F&O PARTICIPANT POSITIONING (/12) [SHADOW]

Collecting data 24-36 months. FII Futures = PRIMARY signal.

- **C1 FII Index Futures NET (/4):** Long + adding=4, Short but covering=3, Short + adding=0
- **C2 FII Index Options (/3):** Writing puts=3 (bullish), Writing calls=0 (bearish)
- **C3 Client Contrarian (/3):** Client extreme long + FII short=3 (BEST contrarian)
- **C4 Pro/DII Confirm (/2):** Aligned with FII=2

## S16: INTERMARKET (/10 MODIFIER)

S16 >= 5 = +5% conviction boost, S16 <= 4 = -5% penalty

- **C1 Crude (weekly ROC):** Falling >3%=3 (bullish India), Rising >3%=0
- **C2 DXY (monthly ROC):** Falling=3, Rising >2%=0
- **C3 India 10Y Yield (2-week Δ):** Falling >20bps=2, Rising >20bps=0
- **C4 Global Markets:** All positive=2
- **Override:** Crude crash >5% + OMC/Auto stocks +3 bonus

## S17: CURRENCY & MACRO (MODIFIER)

Weakest evidence (6/10). Sector boost/penalty only.

- INR weak -> boost IT/Pharma exporters
- INR strong -> boost Banking/Auto/FMCG domestic
- Crude crash -> boost OMC/Auto. Gold rising = risk-off.
- RBI stance: Accommodative=positive, Tightening=caution

## S18: COMPOSITE AGGREGATOR (AUTO)

Auto-combines S12+S14. S13 (weight=0 parked), S15 (weight=0 shadow).

## S19: ML RESERVED (PARKED)

Activates when `ML_ENABLED=True`. ML1 data collector always runs.

---

# PART 4: PRECEDENCE HIERARCHY

| Tier | Role | Rules | Action |
|---:|---|---|---|
| 1 | GATES | S1, S5 | HARD BLOCK if fail |
| 2 | PRIMARY | S2, S4, S6, S12 | DECIDE trade, need 3/4 positive |
| 3 | CONFIRMATION | S3, S7, S9, S10, S14 | Boost/reduce confidence |
| 4 | MODIFIERS | S16, S17 | +/-5% conviction |
| 5 | SHADOW | S8, S11, S15 | Track only |
| 6 | PARKED | S13, S19 | Disabled |

**Conflict:** Tier 2 wins over Tier 3.

**Signal Agreement:** HIGH = T1 pass + 3/4 T2 (100%), MOD = T1 + 2/4 T2 + 2 T3 (75%), LOW = T1 + 1/4 T2 (50%), NO TRADE = T1 fail or 0 T2

---

# PART 5: SCORING & GRADING

Active Max Score = **117**  
(S2:12 + S3:8 + S4:11 + S5:10 + S6:15 + S7:12 + S9:12 + S10:12 + S12:15 + S14:10)

**Grades:** A+ (>=85%) = Full Position, A (>=70%) = 75%, B (>=55%) = 50%, C (>=40%) = Paper, NT (<40%) = Blocked

## Weight Profiles

| Rule | NORMAL | AGGRESSIVE | REVERSAL |
|---|---:|---:|---:|
| S2 | 1.0 | 1.2 | 1.0 |
| S4 | 1.0 | 1.0 | **1.5** |
| S6 | 1.0 | **1.3** | 1.0 |
| S7 | 1.0 | 0.8 | **1.5** |
| S12 | 1.0 | 1.2 | **1.3** |

---

# PART 6: DATA SOURCES

## NSE Endpoints (Block A2)

- Equity Bhavcopy -> S1-S6 | Delivery Data -> S6
- FII/DII Cash -> S7 | Index Data -> S10, N-rules | Sectoral Indices -> S8
- Options Chain: `/api/option-chain-indices?symbol=NIFTY` -> S12
- Participant OI: `/api/reports` (F&O archives) -> S15
- F&O Bhav Copy -> S14 | India VIX -> N16, S12 gate

## Intermarket (Yahoo Finance)

- Brent Crude (`BZ=F`) -> S16 C1 | DXY (`DX-Y.NYB`) -> S16 C2
- India 10Y (`IN10Y`) -> S16 C3 | USD/INR (`USDINR=X`) -> S17 C1
- Gold (`GC=F`) -> S17 C4 | SPX, Nikkei, HSI -> S16 C4

## Add New Source (6 Steps)

1. `config.py` B1 -> Register URL, columns needed
2. `smart_data_fetcher.py` -> New A-block download function
3. `data_fetcher.py` -> New C-block: load CSV, SELECT only needed columns
4. `rule_engine` -> Use in scoring (enhance existing or create new rule)
5. `main_pipeline.py` -> Wire: download -> load -> score (3 lines)
6. `config.py` -> Add thresholds, mode=SHADOW, tier, weight

---

# PART 7: PYTHON ARCHITECTURE (12 Files, 111 Blocks)

| File | Blocks | Purpose |
|---|---|---|
| `config.py` | B1-B22 | ALL thresholds; generated |
| `smart_data_fetcher.py` | A1-A12 | NSE downloads + logging |
| `data_fetcher.py` | C1-C10 | Load CSV -> DataFrames |
| `rule_engine_stock.py` | D1-D12 | S1-S11 scoring |
| `rule_engine_options.py` | J1-J13 | S12-S15 scoring |
| `rule_engine_macro.py` | K1-K9 | S16-S18 + Precedence |
| `chart_generator.py` | F1-F7 | Auto dashboard PNGs |
| `chart_plotter.py` | E1-E7 | Interactive charts |
| `alerts.py` | G1-G4 | Telegram + Sheets |
| `main_pipeline.py` | H1-H9 | Orchestrator |
| `ml/ml_optimizer.py` | ML1-ML3 | Data collector (always ON) |
| `ml/ml_predictor.py` | ML4-ML6 | Predictor (OFF) |

**Block Standard:** WHAT / WHY / IMPACT in every block.

---

# PART 8: CORRELATION & BACKTESTING

## How to Calculate Correlation

```python
import pandas as pd

# Load all parameters + target (5-day forward return)
df = pd.DataFrame({...all parameters + nifty_return_5d...})

# Pearson correlation
corr = df.corr()["nifty_return_5d"].sort_values(ascending=False)

# Lag analysis (does parameter LEAD?)
for lag in [1, 2, 3, 5, 10]:
    r = df["fii_net"].shift(lag).corr(df["nifty_return_5d"])

# Rolling correlation (regime changes)
rolling = df["param"].rolling(30).corr(df["nifty_return_5d"])
```

## Parameters to Correlate

FII Net Flow (S7) -> Nifty 5d | PCR (S12) -> Nifty 1d | Max Pain dist (S12) -> Expiry close  
Futures Basis (S14) -> Nifty 3d | Delivery% (S6) -> Stock 5d | VIX (N16) -> Nifty 5d  
Crude ROC (S16) -> OMC returns | DXY (S16) -> FII flow | USD/INR (S17) -> IT returns  
OI Buildup (S12) -> Nifty 1d | FII Futures NET (S15) -> Nifty 10d

## Completed Backtests

| Test | Result | Source |
|---|---|---|
| N1+N3 trend (54 sess) | 75% WR | Own |
| Framework full (56 sess) | 59% WR | Own |
| S7 FII contrarian (119 sess) | 68.2% bounce | NSE |
| S12 Max Pain event-free | 82% | BankNiftyOptions |
| S12 PCR extremes | 72% reversal | NiftyTrader |
| S12 Long Build Up | 78% continuation | NiftyDesk |
| S12 Short Covering | 55% (WEAK - score reduced) | NiftyDesk |
| S14 Basis + OI | ~80%+ | NiftyDesk |
| S13 IV rule-based | Sharpe 0.12 | Anand 2025 |
| S13 IV ML-enhanced | Sharpe 0.78 | Anand 2025 |

---

# PART 9: DATA QUALITY & FAULT TOLERANCE

## 4-Level Resilience

1. **CHECK:** Holiday/weekend validation before download
2. **TRY-EXCEPT:** Every download wrapped - never crash
3. **FALLBACK:** Use previous trading day (up to 3 days back)
4. **FLAG:** Mark data quality + adjust scoring denominator

## Adjusted Scoring

`score_pct = total / available_max_score` (exclude missing rules)

- **Critical Rules:** S1 (Gate), S2, S4, S6 - pipeline waits if missing
- **Important:** S12, S7 - continue with lower confidence
- **Optional:** S16, S17 - neutral if missing

## Download Log

`output/logs/download_log.csv`

```text
timestamp_ist, trading_date, source, status(SUCCESS|FAILED|FALLBACK), error, fallback_date
```

---

# PART 10: MACHINE SETUP GUIDE

## Prerequisites

Python 3.10+, VS Code, Git

## `requirements.txt`

```text
pandas>=2.0, numpy>=1.24, matplotlib>=3.7, requests>=2.31, yfinance>=0.2.28,
openpyxl>=3.1, gspread>=5.10, python-telegram-bot>=20.4, scipy>=1.11,
scikit-learn>=1.3, xgboost>=1.7(ML phase)
```

## Directory Structure

```text
nifty_framework/
├── config.py, smart_data_fetcher.py, data_fetcher.py
├── rule_engine_stock.py, rule_engine_options.py, rule_engine_macro.py
├── chart_generator.py, chart_plotter.py, alerts.py, main_pipeline.py
├── ml/ (ml_optimizer.py, ml_predictor.py, data/)
├── data/ (equity/, delivery/, fii_dii/, indices/, options/, futures/, participant_oi/, intermarket/)
├── output/ (charts/, logs/, daily_scores/, exports/)
└── credentials.json, requirements.txt, CHANGELOG.md
```

## First Run

1. `git clone <repo>` -> 2. `python -m venv venv` -> 3. `pip install -r requirements.txt`
4. Edit `config.py` (tokens, sheet IDs) -> 5. `python smart_data_fetcher.py --mode historical`
6. `python main_pipeline.py --date 2026-05-27` -> 7. Check `output/`

---

# PART 11: HOW TO MODIFY

## Change Thresholds

`config.py` -> change number -> save -> re-run

## Change Weights

`config.py` B17 -> `ACTIVE_WEIGHT_PROFILE = "REVERSAL_HUNTING"`

## Add Data Source

6-step process (see Part 6)

## Add New Rule

1. Define logic -> 2. `config.py` new B-block -> 3. `rule_engine` new block
4. Add to `RULE_MODES`, `TIER_PRECEDENCE`, `MAX_SCORES` -> 5. Add to `WEIGHT_PROFILES`
6. Wire in `main_pipeline.py` -> 7. Start SHADOW mode -> 8. Validate 60 sessions -> ACTIVE

## Move SHADOW -> ACTIVE

```python
RULE_MODES["S8"] = "ACTIVE"
# Then update tier + add to ACTIVE_SCORING_RULES + recalc max score
```

---

# PART 12: KEY LEVELS & PREFERENCES

**Nifty:** 22,200 (SNIPER demand), 26,000-26,373 (ATH supply). Thesis: Flush -> 22,200 -> 26,000

**Stocks:** BHEL (350-370 entry), ADANIENSOL (broke 1464), DIXON (needs 13,700+), EXIDE (near 431), AMARA RAJA (testing 200DMA)

## Vikram's Rules

- Verify one by one before changes. NSE primary. Manual SL/entry/exit.
- Framework guides, Vikram executes. Block-labeled code.
- ML disabled until 120+ days. Dark theme charts. VS Code primary.
- Local CSV primary, Sheets optional. GitHub private repo, sync.
- WHAT/WHY/IMPACT comments. New rules start SHADOW (60-session validation).

---

# END OF BLUEPRINT

This document + `config.py` = Everything to rebuild the system from scratch.
