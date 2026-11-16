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

BUT "costs a re-upload" was costing a RED TICKET (Megan 2026-11-16). This
writes to AUTOMATION MASTER, the 115-tab workbook every Lucy job, every queue
tab and all three ICD forms share one per-user quota on, so a bare
`open_by_key` / `clear` / `update` on it is a coin flip at a busy minute. At
15:46 that minute arrived: 11580's write came back APIError, pull_ai_settings
counted the office as a failed part, and `drop-sms_ai_settings` opened asking
a person to act on a rate limit that had already passed. A re-run at 16:08
wrote the same tab first try.

So every call here now goes through `shared.sheets_retry`, which exists for
this exact workbook — 6 tries, 1+2+4+8+16s, spanning most of a 60-second
quota window, and failing fast on 403/404/401 where retrying only adds delay.
The pull is still never at risk: the local JSON is written before this runs,
and a write that genuinely cannot land still raises to the caller.
[[reference_sheets_write_quota_429]] [[reference_sheets_per_user_read_cap]]
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


def write(office, info, prefs, rows, gc=None, hours=None):
    """Push one office's pull to its tab. Returns (tab, rows) or (None, 0).
    `hours` is ai_settings.parse_hours' {weekday: [slots]} — one row per
    weekday, section "hours" (older readers skip sections they don't know)."""
    body = [["pulled {} from AppStream p=1504".format(
        dt.datetime.now().isoformat(timespec="seconds"))] + [""] * 2,
        list(COLUMNS)]
    for key, val in sorted((info or {}).items()):
        body.append(["office_info", str(key), str(val)[:CELL_CAP]])
    for key, val in sorted((prefs or {}).items()):
        body.append(["preferences", str(key), str(val)[:CELL_CAP]])
    for day, slots in (hours or {}).items():
        body.append(["hours", str(day), json.dumps(slots)[:CELL_CAP]])
    for r in (rows or []):
        body.append(["escalation", str(r.get("name") or ""),
                     json.dumps({k: r.get(k) for k in ESC_FIELDS},
                                ensure_ascii=False)[:CELL_CAP]])

    from automations.shared import sheets_retry as _retry

    # 6 tries (1+2+4+8+16s) rather than the default 4 (~7s): the quota here is
    # per MINUTE, and nobody is watching this run, so it can afford to wait it
    # out instead of handing back a ticket.
    def _try(fn, *args, **kwargs):
        return _retry.call(fn, *args, tries=6, **kwargs)

    gc = gc or _client()
    sh = _retry.open_sheet(gc, CONTROL_SHEET_ID, tries=6)
    tab = tab_for(office)
    try:
        ws = _try(sh.worksheet, tab)
        _try(ws.clear)
    except Exception as e:  # noqa: BLE001  — gspread's missing-tab error varies
        # A 429 is NOT a missing tab. Letting it land here used to create a
        # second tab of the same name on a rate-limited minute, or fail the
        # add as well; the retry above has already spent its window, so a
        # retryable error at this point is a real failure, not a new tab.
        if _retry.is_retryable(e):
            raise
        ws = _try(sh.add_worksheet, tab, rows=max(len(body) + 10, 60),
                  cols=len(COLUMNS))
    if ws.row_count < len(body) + 5:
        _try(ws.resize, rows=len(body) + 5, cols=len(COLUMNS))
    _try(ws.update, values=body, range_name="A1", raw=True)
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


def parse_hours(values):
    """{weekday: [slots]} off the tab's "hours" rows, or {}."""
    out = {}
    for raw in (values or [])[2:]:
        if raw and (raw[0] or "").strip() == "hours" and len(raw) > 2:
            try:
                out[raw[1].strip()] = json.loads(raw[2])
            except (ValueError, TypeError):
                continue
    return out


def read_hours(office, gc=None):
    """({weekday: [slots]}, pulled-line) or (None, None) — never raises."""
    try:
        gc = gc or _client()
        values = gc.open_by_key(CONTROL_SHEET_ID).worksheet(
            tab_for(office)).get_all_values()
    except Exception:  # noqa: BLE001
        return None, None
    hours = parse_hours(values)
    if not hours:
        return None, None
    return hours, (values[0][0] if values and values[0] else None)
