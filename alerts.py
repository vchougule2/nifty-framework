"""
alerts.py - Notifications & Shadow Logging (Blocks G1-G4)
=========================================================
WHAT:   Pushes the day's high-conviction setups to Telegram / Google Sheets,
        formats derivatives alerts, and logs SHADOW-rule scores to CSV.
WHY:    Vikram executes manually - he needs a clean push + an audit trail for the
        shadow rules (S8/S11/S15) that are being validated over 60 sessions.
IMPACT: Every channel is OFF by default in config (B16). Disabled / missing libs
        => silent no-op, never a crash. send_daily_alerts() is the H6 entry point.

Block map:
    G1 Telegram | G2 Google Sheets | G3 derivatives alert formatter | G4 shadow logger
"""

from __future__ import annotations

import os
from datetime import date, datetime

import pandas as pd

try:
    from . import config
except ImportError:
    import config


# =============================================================================
# BLOCK G1 - TELEGRAM
# WHAT: Send a text message via the Bot API. WHY: instant phone push.
# IMPACT: No-op unless ALERTS.telegram.enabled and a valid token/chat_id.
# =============================================================================
def send_telegram(message: str) -> dict:
    tg = config.ALERTS["telegram"]
    if not tg.get("enabled"):
        return {"channel": "telegram", "status": "disabled"}
    if tg.get("bot_token", "").startswith("YOUR") or not tg.get("chat_id"):
        return {"channel": "telegram", "status": "missing_credentials"}
    try:
        import requests
        url = f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage"
        r = requests.post(url, data={"chat_id": tg["chat_id"], "text": message,
                                     "parse_mode": "HTML"}, timeout=15)
        r.raise_for_status()
        return {"channel": "telegram", "status": "sent"}
    except Exception as exc:  # noqa: BLE001
        return {"channel": "telegram", "status": "error", "error": str(exc)}


# =============================================================================
# BLOCK G2 - GOOGLE SHEETS
# WHAT: Append the daily scores to a sheet. WHY: lightweight cloud journal.
# IMPACT: No-op unless enabled + gspread + credentials.json present.
# =============================================================================
def append_to_sheet(rows: list[list]) -> dict:
    gs = config.ALERTS["google_sheets"]
    if not gs.get("enabled"):
        return {"channel": "sheets", "status": "disabled"}
    if gs.get("sheet_id", "").startswith("YOUR"):
        return {"channel": "sheets", "status": "missing_sheet_id"}
    try:
        import gspread
        creds = gs.get("creds", "credentials.json")
        if not os.path.exists(creds):
            return {"channel": "sheets", "status": "missing_credentials"}
        gc = gspread.service_account(filename=creds)
        sh = gc.open_by_key(gs["sheet_id"]).sheet1
        for row in rows:
            sh.append_row(row)
        return {"channel": "sheets", "status": "appended", "rows": len(rows)}
    except Exception as exc:  # noqa: BLE001
        return {"channel": "sheets", "status": "error", "error": str(exc)}


# =============================================================================
# BLOCK G3 - DERIVATIVES ALERT FORMATTER
# WHAT: Turn the precedence decisions into a readable alert string.
# WHY: Surfaces grade, conviction, signal agreement, and the options read.
# =============================================================================
def format_alert(decisions: list[dict], on: date | None = None,
                 min_grade: str = "A") -> str:
    order = {"A+": 5, "A": 4, "B": 3, "C": 2, "NT": 1}
    cutoff = order.get(min_grade, 4)
    top = [d for d in decisions if d and order.get(d.get("grade", "NT"), 0) >= cutoff]
    top = sorted(top, key=lambda d: d.get("conviction_pct", 0), reverse=True)
    head = f"<b>NIFTY FRAMEWORK v{config.FRAMEWORK_VERSION}</b>  {(on or date.today()).isoformat()}\n"
    if not top:
        return head + "No setups at/above grade " + min_grade + "."
    lines = [head]
    for d in top[:10]:
        lines.append(
            f"{d['symbol']} [{d.get('direction','')}] {d.get('grade')} "
            f"{d.get('conviction_pct',0):.0f}% | {d.get('signal_agreement','')} "
            f"| pos {int(d.get('position_pct',0)*100)}%")
    return "\n".join(lines)


def send_daily_alerts(decisions: list[dict], on: date | None = None,
                      min_grade: str = "A") -> dict:
    """H6 entry point: format once, fan out to enabled channels, log everything."""
    msg = format_alert(decisions, on, min_grade)
    report = {"telegram": send_telegram(msg)}
    rows = [[(on or date.today()).isoformat(), d["symbol"], d.get("direction"),
             d.get("grade"), d.get("conviction_pct"), d.get("signal_agreement")]
            for d in sorted([x for x in decisions if x],
                            key=lambda d: d.get("conviction_pct", 0), reverse=True)
            if d.get("grade") not in (None, "NT")]
    report["sheets"] = append_to_sheet(rows) if rows else {"channel": "sheets", "status": "no_rows"}
    report["message_preview"] = msg
    return report


# =============================================================================
# BLOCK G4 - SHADOW LOGGER
# WHAT: Persist SHADOW-rule scores (S8/S11/S15) to output/logs/shadow_log.csv.
# WHY:  These rules need 60-session (S8/S11) / 24-36 month (S15) validation
#       before promotion to ACTIVE - we must capture them every day.
# IMPACT: This is how a SHADOW rule earns its way to ACTIVE.
# =============================================================================
def log_shadow(decisions: list[dict], options_block: dict | None = None,
               on: date | None = None) -> str:
    config.ensure_directories()
    path = os.path.join(config.LOGS_DIR, "shadow_log.csv")
    stamp = (on or date.today()).isoformat()
    rows = []
    for d in decisions:
        if not d:
            continue
        sh = d.get("shadow", {})
        rows.append({
            "date": stamp, "symbol": d.get("symbol"),
            "S8": (sh.get("S8") or {}).get("score"),
            "S8_stage": (sh.get("S8") or {}).get("label"),
            "S11": (sh.get("S11") or {}).get("score"),
            "S11_regime": (sh.get("S11") or {}).get("label"),
        })
    if options_block and options_block.get("S15"):
        rows.append({"date": stamp, "symbol": "INDEX_S15",
                     "S8": None, "S8_stage": None,
                     "S11": options_block["S15"].get("score"),
                     "S11_regime": options_block["S15"].get("label")})
    if not rows:
        return path
    header = not os.path.exists(path)
    pd.DataFrame(rows).to_csv(path, mode="a", header=header, index=False)
    return path
