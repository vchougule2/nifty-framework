"""
chart_plotter.py - Deep-Dive Inspection Charts (Blocks E1-E7)
=============================================================
WHAT:   On-demand, single-topic charts for drilling into one signal.
WHY:    The F-dashboards summarise; these E-plots let Vikram inspect the "why".
IMPACT: Same dark theme (config.CHART), saved to output/charts/. Headless 'Agg'.

Block map:
    E1 FII/DII flow | E2 delivery% trend | E3 whale (vol+delivery) | E4 sector RS
    E5 options OI ladder | E6 IV skew | E7 futures basis history
"""

from __future__ import annotations

import os
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

try:
    from . import config
except ImportError:
    import config

C = config.CHART


def _ax(fig, title):
    ax = fig.add_subplot(111)
    ax.set_facecolor(C["panel"])
    ax.tick_params(colors=C["white"], labelsize=8)
    for sp in ax.spines.values():
        sp.set_color(C["grey"])
    ax.set_title(title, color=C["gold"], fontsize=11, fontweight="bold")
    ax.grid(alpha=0.15, color=C["grey"])
    return ax


def _save(fig, name, on=None):
    config.ensure_directories()
    path = os.path.join(config.CHARTS_DIR, f"deep_{name}_{(on or date.today()).isoformat()}.png")
    fig.savefig(path, dpi=C["dpi"], facecolor=C["bg"], bbox_inches="tight")
    plt.close(fig)
    return path


# =============================================================================
# BLOCK E1 - FII / DII FLOW
# =============================================================================
def plot_fii_flow(fii_hist, on=None) -> str:
    fig = plt.figure(figsize=(11, 5), facecolor=C["bg"])
    ax = _ax(fig, "FII / DII NET FLOW (Rs Cr)")
    try:
        x = range(len(fii_hist))
        ax.bar([i - 0.2 for i in x], fii_hist.get("fii_net", []), width=0.4, color=C["cyan"], label="FII")
        ax.bar([i + 0.2 for i in x], fii_hist.get("dii_net", []), width=0.4, color=C["orange"], label="DII")
        ax.axhline(0, color=C["grey"], lw=0.8)
        ax.legend(facecolor=C["panel"], labelcolor=C["white"], fontsize=8)
    except Exception as exc:  # noqa: BLE001
        ax.text(0.5, 0.5, f"no flow data\n{exc}", color=C["white"], ha="center")
    return _save(fig, "fii_flow", on)


# =============================================================================
# BLOCK E2 - DELIVERY % TREND
# =============================================================================
def plot_delivery(history, symbol="", on=None) -> str:
    fig = plt.figure(figsize=(11, 5), facecolor=C["bg"])
    ax = _ax(fig, f"DELIVERY % TREND  {symbol}")
    if history is not None and "deliv_pct" in history:
        d = history["deliv_pct"].fillna(0)
        ax.plot(d.values, color=C["bull"], lw=1.4)
        ax.axhline(config.S6_VOLUME["delivery_strong"], color=C["gold"], ls="--", lw=0.8, label="Strong 65%")
        ax.axhline(config.S6_VOLUME["delivery_moderate"], color=C["orange"], ls=":", lw=0.8, label="Mod 50%")
        ax.legend(facecolor=C["panel"], labelcolor=C["white"], fontsize=8)
    else:
        ax.text(0.5, 0.5, "no delivery data", color=C["white"], ha="center")
    return _save(fig, "delivery", on)


# =============================================================================
# BLOCK E3 - WHALE (volume + delivery overlay)
# =============================================================================
def plot_whale(history, symbol="", on=None) -> str:
    fig = plt.figure(figsize=(11, 5), facecolor=C["bg"])
    ax = _ax(fig, f"WHALE FOOTPRINT  {symbol}")
    if history is not None and "volume" in history:
        ax.bar(range(len(history)), history["volume"].fillna(0).values, color=C["grey"], alpha=0.6, label="Volume")
        ax.set_ylabel("Volume", color=C["white"])
        if "deliv_pct" in history:
            ax2 = ax.twinx()
            ax2.plot(history["deliv_pct"].fillna(0).values, color=C["magenta"], lw=1.4, label="Delivery %")
            ax2.tick_params(colors=C["white"], labelsize=8)
            ax2.set_ylabel("Delivery %", color=C["magenta"])
        ax.legend(facecolor=C["panel"], labelcolor=C["white"], fontsize=8, loc="upper left")
    else:
        ax.text(0.5, 0.5, "no data", color=C["white"], ha="center")
    return _save(fig, "whale", on)


# =============================================================================
# BLOCK E4 - SECTOR RS
# =============================================================================
def plot_sector_rs(sector_scores: dict, on=None) -> str:
    fig = plt.figure(figsize=(10, 5), facecolor=C["bg"])
    ax = _ax(fig, "SECTOR RELATIVE STRENGTH")
    if sector_scores:
        names = list(sector_scores.keys())
        vals = [sector_scores[n] for n in names]
        ax.barh(names, vals, color=[C["bull"] if v >= 0 else C["bear"] for v in vals])
        ax.axvline(0, color=C["grey"], lw=0.8)
    else:
        ax.text(0.5, 0.5, "no sector data", color=C["white"], ha="center")
    return _save(fig, "sector_rs", on)


# =============================================================================
# BLOCK E5 - OPTIONS OI LADDER
# =============================================================================
def plot_oi_ladder(chain, spot=None, on=None) -> str:
    fig = plt.figure(figsize=(11, 6), facecolor=C["bg"])
    ax = _ax(fig, "OPTIONS OI LADDER (change in OI)")
    try:
        ce = chain[chain["type"] == "CE"].groupby("strikePrice")["changeinOpenInterest"].sum()
        pe = chain[chain["type"] == "PE"].groupby("strikePrice")["changeinOpenInterest"].sum()
        ax.barh(ce.index, ce.values, color=C["bear"], alpha=0.7, label="Call dOI")
        ax.barh(pe.index, -pe.values, color=C["bull"], alpha=0.7, label="Put dOI")
        if spot:
            ax.axhline(spot, color=C["gold"], ls="--", label=f"Spot {spot:.0f}")
        ax.legend(facecolor=C["panel"], labelcolor=C["white"], fontsize=8)
    except Exception as exc:  # noqa: BLE001
        ax.text(0.5, 0.5, f"no chain\n{exc}", color=C["white"], ha="center")
    return _save(fig, "oi_ladder", on)


# =============================================================================
# BLOCK E6 - IV SKEW (S13 - parked, still plottable for inspection)
# =============================================================================
def plot_iv_skew(chain, on=None) -> str:
    fig = plt.figure(figsize=(11, 5), facecolor=C["bg"])
    ax = _ax(fig, "IV SKEW (S13 parked - inspection only)")
    try:
        ce = chain[(chain["type"] == "CE") & (chain["impliedVolatility"] > 0)]
        pe = chain[(chain["type"] == "PE") & (chain["impliedVolatility"] > 0)]
        ax.plot(ce["strikePrice"], ce["impliedVolatility"], color=C["bear"], lw=1.2, label="Call IV")
        ax.plot(pe["strikePrice"], pe["impliedVolatility"], color=C["bull"], lw=1.2, label="Put IV")
        ax.set_xlabel("Strike", color=C["white"])
        ax.set_ylabel("IV %", color=C["white"])
        ax.legend(facecolor=C["panel"], labelcolor=C["white"], fontsize=8)
    except Exception as exc:  # noqa: BLE001
        ax.text(0.5, 0.5, f"no IV data\n{exc}", color=C["white"], ha="center")
    return _save(fig, "iv_skew", on)


# =============================================================================
# BLOCK E7 - FUTURES BASIS HISTORY (S14)
# =============================================================================
def plot_basis(basis_history, on=None) -> str:
    fig = plt.figure(figsize=(11, 5), facecolor=C["bg"])
    ax = _ax(fig, "FUTURES BASIS HISTORY (pts)")
    if basis_history:
        ax.plot(list(basis_history), color=C["cyan"], lw=1.4)
        ax.axhline(0, color=C["grey"], lw=0.8)
        ax.fill_between(range(len(basis_history)), list(basis_history), 0,
                        color=C["cyan"], alpha=0.15)
    else:
        ax.text(0.5, 0.5, "no basis history", color=C["white"], ha="center")
    return _save(fig, "basis", on)
