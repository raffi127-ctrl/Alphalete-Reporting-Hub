"""Which owner's 1st rounds run on each Zoom account -- read from Camila's
'all in one' workbook (Camila, 2026-10-01: "en la tab zooms tenés las API de
todo").

Tab ZOOMS INFO, one column per Zoom account:
    the MORNINGS block       -> owner whose 1st rounds run there in the morning
    the AFTERNOONS block     -> owner in the afternoon (empty = the morning
                                owner's cell is merged down: same owner all day)
    the row of logins        -> the account's email = Fathom's recorded_by.email
    the row under the passwords -> that account's Fathom API key

Rows are found by their column-A label / by the emails, never by number, so
Camila can add rows or Zoom columns. Read live every run -- she moves owners
between Zooms -- with the last good read kept as a fallback (a Sheets hiccup
shouldn't lose the owner line).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

WORKBOOK = "1hXSpfTM6u0D-_P0wMw3sa_z9Iw0vKTnfRyxkvAL96tE"     # ALL IN ONE (Camila)
TAB = "ZOOMS INFO"
# A recording that starts at or after this (CT) is the afternoon owner's: the
# last morning slot is 11:15, the first afternoon one 11:45 (Camila via Eve,
# 2026-10-01) -- split halfway, so one that opens a few minutes early or late
# still lands on the right owner.
AFTERNOON_FROM = dt.time(11, 30)
CACHE = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards" / "zooms.json"


def parse(rows: List[List[str]]) -> Dict[str, Dict[str, str]]:
    """{email: {"zoom", "morning", "afternoon", "key"}} from the tab's values."""
    def cell(r, c):
        return (rows[r][c] if r < len(rows) and c < len(rows[r]) else "").strip()

    label = {cell(r, 0).upper(): r for r in range(len(rows)) if cell(r, 0)}
    am, pm = label.get("MORNINGS"), label.get("AFTERNOONS")
    width = max((len(r) for r in rows), default=0)
    # the logins row: the one with the most emails in it
    logins = max(range(len(rows)), key=lambda r: sum("@" in cell(r, c) for c in range(width)),
                 default=None)
    if am is None or pm is None or logins is None:
        raise ValueError("ZOOMS INFO: no MORNINGS / AFTERNOONS / logins row")
    out = {}
    for c in range(1, width):
        email = cell(logins, c).lower()
        key = cell(logins + 2, c)                      # login, password, then the key
        if key.startswith("whsec_") or " " in key:     # a webhook secret / a note, not a key
            key = ""
        if "@" not in email:
            # no login typed in (Carlos' Zoom, 10/2) but a key: its recordings
            # are still known -- by the key that fetched them (zoom_of)
            if not key:
                continue
            email = "key:" + key[-12:]
        morning = next((cell(r, c) for r in range(am, pm) if cell(r, c)), "")
        afternoon = next((cell(r, c) for r in range(pm, logins - 1) if cell(r, c)), "")
        # the name row right above the logins ('ZOOM 4'), else the top header
        zoom = cell(logins - 1, c) or cell(0, c)
        out[email] = {"zoom": " ".join(zoom.split()), "morning": morning,
                      "afternoon": afternoon or morning, "key": key}
    return out


_accounts: Optional[Dict[str, Dict[str, str]]] = None


def accounts() -> Dict[str, Dict[str, str]]:
    global _accounts
    if _accounts is None:
        try:
            from automations.recruiting_report import fill
            rows = fill.open_by_key(WORKBOOK).worksheet(TAB).get_all_values()
            _accounts = parse(rows)
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(_accounts, indent=1), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"ZOOMS INFO not read ({type(exc).__name__}: {exc}) - last good copy")
            try:
                _accounts = json.loads(CACHE.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _accounts = {}
    return _accounts


def zoom_of(m: Dict) -> Dict[str, str]:
    email = ((m.get("recorded_by") or {}).get("email") or "").lower()
    acc = accounts()
    return (acc.get(email) or acc.get("key:" + (m.get("fathom_key_tail") or "-"))
            or {})


def owner(m: Dict, start_ct: dt.datetime) -> str:
    """The owner whose 1st round this was, by the account + time of day."""
    z = zoom_of(m)
    if not z:
        return ""
    return z["afternoon"] if start_ct.time() >= AFTERNOON_FROM else z["morning"]
