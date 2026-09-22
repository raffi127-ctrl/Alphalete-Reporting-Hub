"""Hand this sweep's SaraPlus numbers to the LucyEco relay as Raf's feed.

Every other office's live board comes from its own LucyEco agent. Raf's
office has no agent — but it has THIS sweep, which already reads his office's
SaraPlus every five minutes, noon to midnight, with a 2am refresh (Megan
2026-09-22: "Raf has live sara alerts running somewhere though"). So the same
per-rep numbers the sweep writes to his Google sheet also go to the relay,
and his board, the morning check and the LucyEco list pick him up through the
path every other office uses. One read, two uses; nothing new logs in.

SALES ONLY. No credit checks are sent, and the office is not enrolled for
alerts in icd_alerts/offices.py — the poster ignores a relaying office that
is not enrolled ("relayed but is not enrolled/active — ignored"), so this can
never start an alert anywhere.

THE KEY is read off the 'Relay Keys' tab at send time (row 'rafael_hidalgo'),
never stored here. That office key is deliberately Raf's BOARD key: the board
keeps his saved roster (Team / Leadership / Status) under the same key it
reads the relay with, and 61 rows of it live under 'rafael_hidalgo'.

NEVER RAISES. The sweep's real job is his board sheet and the sale texts.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from typing import Dict, List

OFFICE_KEY = "rafael_hidalgo"
CAMPAIGN = "att"
# Honest about what is sending: this is not the ECO agent, and the LucyEco
# list reads a non-agent source as a house feed rather than an old agent.
SOURCE = "alphalete_sweep"

_KEY_CACHE: Dict[str, object] = {"at": 0.0, "key": ""}


def _relay_key() -> str:
    """This office's key off the Relay Keys tab, cached for ten minutes."""
    if _KEY_CACHE["key"] and time.time() - float(_KEY_CACHE["at"]) < 600:
        return str(_KEY_CACHE["key"])
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    rows = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet(
        "Relay Keys").get_all_values()[1:]
    for row in rows:
        if len(row) > 2 and row[0].strip().lower() == OFFICE_KEY:
            if row[2].strip().upper() not in ("TRUE", "YES", "Y"):
                return ""                      # switched off on purpose
            _KEY_CACHE.update(at=time.time(), key=row[1].strip())
            return row[1].strip()
    return ""


def sales_from(agents: List[Dict]) -> Dict[str, Dict[str, int]]:
    """{SARAPLUS NAME: {Int, Int Up, DTV, NL}} for every rep who sold.

    The same reading the ECO agents send (calc.metrics_for), keyed by the
    name as SaraPlus writes it, which is what the relay carries for everyone
    else."""
    from automations.alphalete_sales_board import calc
    out = {}
    for a in agents or []:
        name = str(a.get("name", "")).strip()
        m = calc.metrics_for(a)
        if name and any(m.values()):
            out[name] = m
    return out


def send(agents: List[Dict], day: dt.date, *, dry_run: bool = False,
         log=print) -> bool:
    """Relay one sweep's totals for `day`. True when it went over."""
    try:
        from automations.icd_alerts import offices as O
        from automations.icd_alerts import relay as R
        sales = sales_from(agents)
        if dry_run:
            # A preview touches nothing outside this machine — not even the
            # key lookup — so a test or a preview run can never reach a sheet.
            log("eco relay: dry run — would send %d rep(s) for %s"
                % (len(sales), day.isoformat()))
            return True
        key = _relay_key()
        if not key:
            log("eco relay: no active 'rafael_hidalgo' key on Relay Keys — "
                "skipped")
            return False
        rec = {"office_key": OFFICE_KEY, "relay_key": key,
               "relay_url": O.RELAY_URL, "campaign": CAMPAIGN}
        body = R.payload({}, day, rec, sales=sales)
        body["agent"] = SOURCE
        R._post(rec["relay_url"], json.dumps(body).encode("utf-8"))
        log("eco relay: %d rep(s) sent for %s" % (len(sales), day.isoformat()))
        return True
    except Exception as e:  # noqa: BLE001 — never cost the sweep its real work
        log("eco relay: skipped (%s: %s)" % (type(e).__name__, e))
        return False
