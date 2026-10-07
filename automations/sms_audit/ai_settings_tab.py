# -*- coding: utf-8 -*-
"""Carry the AI Settings pull back from Lucy 2.

The pull can only run where the AppStream session lives, which is Lucy 2,
and it writes its JSON to that machine's `output/`. Nothing copies those
files to anyone else, so every other machine read "AI Settings not pulled"
however often the job succeeded — the 2026-10-06 run finished clean at
12:48 and the audit still showed the page as unchecked.

The SMS log already solved this by also writing a tab on the control
sheet. This does the same for the AI Settings page, in one tab per office:

    row 1   when it was pulled, and from where
    row 2   section | key | value
    rows    office_info and preferences as plain key/value pairs, then one
            row per escalation with its fields as JSON

Writing is best-effort on purpose. The local JSON is written first, so a
sheet that is rate-limited costs a re-upload and never the pull.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import datetime as dt
import json

CONTROL_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB_PREFIX = "AI Settings"
COLUMNS = ("section", "key", "value")
CELL_CAP = 45000
ESC_FIELDS = ("name", "category", "description", "message", "routing")


def tab_for(office):
    return "{} {}".format(TAB_PREFIX, office)


def _client():
    from automations.recruiting_report import fill as _fill
    return _fill._client()


def write(office, info, prefs, rows, gc=None):
    """Push one office's pull to its tab. Returns (tab, rows) or (None, 0)."""
    body = [["pulled {} from AppStream p=1504".format(
        dt.datetime.now().isoformat(timespec="seconds"))] + [""] * 2,
        list(COLUMNS)]
    for key, val in sorted((info or {}).items()):
        body.append(["office_info", str(key), str(val)[:CELL_CAP]])
    for key, val in sorted((prefs or {}).items()):
        body.append(["preferences", str(key), str(val)[:CELL_CAP]])
    for r in (rows or []):
        body.append(["escalation", str(r.get("name") or ""),
                     json.dumps({k: r.get(k) for k in ESC_FIELDS},
                                ensure_ascii=False)[:CELL_CAP]])

    gc = gc or _client()
    sh = gc.open_by_key(CONTROL_SHEET_ID)
    tab = tab_for(office)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except Exception:  # noqa: BLE001  — gspread's missing-tab error varies
        ws = sh.add_worksheet(tab, rows=max(len(body) + 10, 60),
                              cols=len(COLUMNS))
    if ws.row_count < len(body) + 5:
        ws.resize(rows=len(body) + 5, cols=len(COLUMNS))
    ws.update(values=body, range_name="A1", raw=True)
    return tab, len(body)


def parse(values):
    """Rows off the tab -> (office_info, preferences, escalations).

    Returns (None, None, []) for an empty or header-only tab, so a tab that
    exists but holds nothing cannot read as a successful pull."""
    if not values or len(values) < 3:
        return None, None, []
    info, prefs, rows = {}, {}, []
    for raw in values[2:]:
        if not raw or not (raw[0] or "").strip():
            continue
        section = raw[0].strip()
        key = raw[1].strip() if len(raw) > 1 else ""
        val = raw[2] if len(raw) > 2 else ""
        if section == "office_info":
            info[key] = val
        elif section == "preferences":
            prefs[key] = val
        elif section == "escalation":
            try:
                rows.append(json.loads(val))
            except (ValueError, TypeError):
                rows.append({"name": key, "category": "", "description": "",
                             "message": "", "routing": ""})
    if not info and not prefs and not rows:
        return None, None, []
    return info, prefs, rows


def read(office, gc=None):
    """(office_info, preferences, escalations, source) — never raises.

    A sheet that is unreachable is the same as a pull that has not happened;
    the caller says "not pulled" either way, which is the honest answer."""
    try:
        gc = gc or _client()
        ws = gc.open_by_key(CONTROL_SHEET_ID).worksheet(tab_for(office))
        info, prefs, rows = parse(ws.get_all_values())
    except Exception:  # noqa: BLE001
        return None, None, [], None
    if info is None and not rows:
        return None, None, [], None
    return info, prefs, rows, "sheet tab '{}'".format(tab_for(office))
