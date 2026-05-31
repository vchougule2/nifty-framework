"""
chart_generator.py - Daily Dashboard Generator (Blocks F1-F7)
=============================================================
WHAT:   Renders the daily decision dashboards as dark-theme PNGs.
WHY:    A trader scans one image instead of a wall of numbers.
IMPACT: All output lands in output/charts/. Colours/DPI come from config.CHART so
        the whole system shares one professional dark theme.

Block map:
    F1 master dashboard | F2 score heatmap | F3 summary table | F4 sector rotation
    F5 max-pain / OI profile | F6 participant positioning | F7 intermarket panel

NOTE: Uses the non-interactive 'Agg' backend - safe on headless servers.
"""

from __future__ import annotations

import os
from datetime import date

import matplotlib
matplotlib.use("Agg")  # headless - never opens a window
import matplotlib.pyplot as plt
import numpy as np

try:
    from . import config
except ImportError:
    import config

C = config.CHART


def _style_ax(ax, title=""):
    ax.set_facecolor(C["panel"])
    ax.tick_params(colors=C["white"], labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(C["grey"])
    if title:
        ax.set_title(title, color=C["gold"], fontsize=11, fontweight="bold")
    ax.grid(alpha=0.15, color=C["grey"])


def _new_fig(w=12, h=8):
    fig = plt.figure(figsize=(w, h), facecolor=C["bg"])
    return fig


def _save(fig, name: str, on: date | None = None) -> str:
    config.ensure_directories()
    stamp = (on or date.today()).isoformat()
    path = os.path.join(config.CHARTS_DIR, f"{name}_{stamp}.png")
    fig.savefig(path, dpi=C["dpi"], facecolor=C["bg"], bbox_inches="tight")
    plt.close(fig)
    return path


def _grade_color(grade: str) -> str:
    return {"A+": C["bull"], "A": C["cyan"], "B": C["gold"],
            "C": C["orange"], "NT": C["bear"]}.get(grade, C["grey"])


# =============================================================================
# BLOCK F1 - MASTER DASHBOARD
# Top conviction setups + grade colour-coding + signal agreement.
# =============================================================================
def dashboard(decisions: list[dict], on: date | None = None) -> str:
    ranked = sorted([d for d in decisions if d],
                    key=lambda d: d.get("conviction_pct", 0), reverse=True)[:15]
    fig = _new_fig(12, 8)
    ax = fig.add_subplot(111)
    _style_ax(ax, f"INSTITUTIONAL DASHBOARD  -  {(on or date.today()).isoformat()}")
    if not ranked:
        ax.text(0.5, 0.5, "No setups", color=C["white"], ha="center")
        return _save(fig, "dashboard", on)
    names = [d["symbol"] for d in ranked][::-1]
    conv = [d.get("conviction_pct", 0) for d in ranked][::-1]
    colors = [_grade_color(d.get("grade", "NT")) for d in ranked][::-1]
    ax.barh(names, conv, color=colors)
    ax.axvline(85, color=C["bull"], ls="--", lw=0.8)
    ax.axvline(70, color=C["cyan"], ls="--", lw=0.8)
    ax.set_xlabel("Conviction %", color=C["white"])
    for i, d in enumerate(ranked[::-1]):
        ax.text(conv[i] + 1, i, f"{d.get('grade')} | {d.get('signal_agreement','')}",
                color=C["white"], va="center", fontsize=7)
    return _save(fig, "dashboard", on)


# =============================================================================
# BLOCK F2 - SCORE HEATMAP (rules x stocks)
# =============================================================================
def heatmap(decisions: list[dict], on: date | None = None) -> str:
    rules = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S9", "S10", "S12", "S14"]
    rows = [d for d in decisions if d and d.get("rule_scores")][:20]
    fig = _new_fig(12, max(4, len(rows) * 0.4 + 2))
    ax = fig.add_subplot(111)
    _style_ax(ax, "RULE SCORE HEATMAP (normalised)")
    if not rows:
        ax.text(0.5, 0.5, "No data", color=C["white"], ha="center")
        return _save(fig, "heatmap", on)
    mat = []
    for d in rows:
        rs = d.get("rule_scores", {})
        mat.append([(rs.get(r, 0) or 0) / (config.MAX_SCORES.get(r, 1) or 1) for r in rules])
    mat = np.array(mat)
    im = ax.imshow(mat, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
    ax.set_xticks(range(len(rules)))
    ax.set_xticklabels(rules, color=C["white"])
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([d["symbol"] for d in rows], color=C["white"])
    fig.colorbar(im, ax=ax, fraction=0.02)
    return _save(fig, "heatmap", on)


# =============================================================================
# BLOCK F3 - SUMMARY TABLE (grade / conviction / direction)
# =============================================================================
def summary_table(decisions: list[dict], on: date | None = None) -> str:
    ranked = sorted([d for d in decisions if d],
                    key=lambda d: d.get("conviction_pct", 0), reverse=True)[:18]
    fig = _new_fig(10, max(3, len(ranked) * 0.4 + 1.5))
    ax = fig.add_subplot(111)
    ax.axis("off")
    ax.set_title(f"DAILY SUMMARY  -  {(on or date.today()).isoformat()}",
                 color=C["gold"], fontweight="bold")
    cells, colors = [], []
    for d in ranked:
        cells.append([d["symbol"], d.get("direction", ""), d.get("grade", ""),
                      f"{d.get('conviction_pct',0):.1f}%", d.get("signal_agreement", "")])
        colors.append([C["panel"]] * 4 + [_grade_color(d.get("grade", "NT"))])
    if not cells:
        ax.text(0.5, 0.5, "No setups", color=C["white"], ha="center")
        return _save(fig, "summary", on)
    tbl = ax.table(cellText=cells, cellColours=colors,
                   colLabels=["Symbol", "Dir", "Grade", "Conviction", "Signal"],
                   loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    for (r, _c), cell in tbl.get_celld().items():
        cell.set_edgecolor(C["grey"])
        cell.get_text().set_color(C["white"] if r > 0 else C["gold"])
    return _save(fig, "summary", on)


# =============================================================================
# BLOCK F4 - SECTOR ROTATION (S8 shadow read)
# =============================================================================
def sector_rotation(sector_scores: dict, on: date | None = None) -> str:
    fig = _new_fig(9, 6)
    ax = fig.add_subplot(111)
    _style_ax(ax, "SECTOR RS / ROTATION (S8 shadow)")
    if not sector_scores:
        ax.text(0.5, 0.5, "No sector data", color=C["white"], ha="center")
        return _save(fig, "sector", on)
    names = list(sector_scores.keys())
    vals = [sector_scores[n] for n in names]
    ax.bar(names, vals, color=[C["bull"] if v >= 0 else C["bear"] for v in vals])
    ax.axhline(0, color=C["grey"], lw=0.8)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    ax.set_ylabel("RS vs Nifty (22d %)", color=C["white"])
    return _save(fig, "sector", on)


# =============================================================================
# BLOCK F5 - MAX-PAIN / OI PROFILE (S12)
# =============================================================================
def max_pain_profile(chain, spot=None, max_pain=None, on: date | None = None) -> str:
    fig = _new_fig(11, 6)
    ax = fig.add_subplot(111)
    _style_ax(ax, "OPTIONS OI PROFILE  (Call vs Put)")
    try:
        ce = chain[chain["type"] == "CE"].groupby("strikePrice")["openInterest"].sum()
        pe = chain[chain["type"] == "PE"].groupby("strikePrice")["openInterest"].sum()
        ax.bar(ce.index, ce.values, width=20, color=C["bear"], alpha=0.7, label="Call OI")
        ax.bar(pe.index, -pe.values, width=20, color=C["bull"], alpha=0.7, label="Put OI")
        if spot:
            ax.axvline(spot, color=C["gold"], ls="--", label=f"Spot {spot:.0f}")
        if max_pain:
            ax.axvline(max_pain, color=C["cyan"], ls=":", label=f"MaxPain {max_pain:.0f}")
        ax.legend(facecolor=C["panel"], labelcolor=C["white"], fontsize=8)
        ax.set_xlabel("Strike", color=C["white"])
    except Exception as exc:  # noqa: BLE001
        ax.text(0.5, 0.5, f"OI chart unavailable\n{exc}", color=C["white"], ha="center")
    return _save(fig, "max_pain", on)


# =============================================================================
# BLOCK F6 - PARTICIPANT POSITIONING (S15 shadow)
# =============================================================================
def participant_positioning(part_scores: dict, on: date | None = None) -> str:
    fig = _new_fig(9, 5)
    ax = fig.add_subplot(111)
    _style_ax(ax, "F&O PARTICIPANT POSITIONING (S15 shadow)")
    if not part_scores:
        ax.text(0.5, 0.5, "No participant data", color=C["white"], ha="center")
        return _save(fig, "participant", on)
    names = list(part_scores.keys())
    vals = [part_scores[n] for n in names]
    ax.bar(names, vals, color=[C["bull"] if v >= 0 else C["bear"] for v in vals])
    ax.axhline(0, color=C["grey"], lw=0.8)
    ax.set_ylabel("Net futures position", color=C["white"])
    return _save(fig, "participant", on)


# =============================================================================
# BLOCK F7 - INTERMARKET PANEL (S16/S17)
# =============================================================================
def intermarket_panel(im, on: date | None = None) -> str:
    cols = [c for c in ["BRENT", "DXY", "USDINR", "GOLD"] if im is not None and c in im]
    fig = _new_fig(11, 7)
    if im is None or im.empty or not cols:
        ax = fig.add_subplot(111)
        _style_ax(ax, "INTERMARKET")
        ax.text(0.5, 0.5, "No intermarket data", color=C["white"], ha="center")
        return _save(fig, "intermarket", on)
    for i, col in enumerate(cols, 1):
        ax = fig.add_subplot(2, 2, i)
        _style_ax(ax, col)
        ax.plot(im[col].values, color=C["cyan"], lw=1.2)
    fig.suptitle("INTERMARKET (S16/S17)", color=C["gold"], fontweight="bold")
    return _save(fig, "intermarket", on)


def generate_all(decisions, bundle, extras=None, on: date | None = None) -> dict:
    """Render every dashboard for the day; returns {name: path}. Never raises."""
    extras = extras or {}
    out = {}
    try:
        out["dashboard"] = dashboard(decisions, on)
        out["heatmap"] = heatmap(decisions, on)
        out["summary"] = summary_table(decisions, on)
        out["sector"] = sector_rotation(extras.get("sector_scores", {}), on)
        out["max_pain"] = max_pain_profile(bundle.get("options"),
                                           extras.get("spot"), extras.get("max_pain"), on)
        out["participant"] = participant_positioning(extras.get("participant_scores", {}), on)
        out["intermarket"] = intermarket_panel(bundle.get("intermarket"), on)
    except Exception as exc:  # noqa: BLE001 - charts must never crash the pipeline
        out["error"] = str(exc)
    return out
