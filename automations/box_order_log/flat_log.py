"""The "Box Sales Log" tab — every BOX sale of the last 60 days, one flat table.

Carlos, 2026-09-05: "i want an order log created that sits in the vantura
maser sales with all of our box sales. i want a column that shows the
Weekending the sales fall under ... basically the box order log you post on
slack but i want one for all the sales and i want to be able to filter by
headers. i only need on tab and don't need separaters ... i don't want any of
this to change what you're sending in the b2b metrics tab."

So, deliberately different from the "Lucy Box Order Log" pair (sheet.py):

  * ONE tab, values only. No week dropdown, no COUNTIFS summary, no FILTER
    spill, no spacer rows — a real header-row basic filter instead, which is
    what "filter by headers" means in Sheets. Spacers would poison filtering,
    which is exactly why this is not a third view over the hidden data tab.
  * 60 DAYS by sale date, not six week-buckets.
  * Week Ending here is the MON-SUN week's SUNDAY — Carlos's sales-week
    ruling (2026-08-28: "Sales are Monday through Sunday"), NOT the log tab's
    legacy Sun-Sat Saturday. The column exists so he can filter a week; it
    should match how he counts one. The org's shared report_week.py already
    uses this convention.

Same sale set as everything else — clean.collapse with the TPV memory, called
from run.py's --sheet path right after the main push, same pull, same run. And
the same reason to MERGE rather than overwrite: the Tableau view is a rolling
~44-day window, so days 45-60 exist only on the tab itself. A blind rewrite
would silently shave the window to 44 days and no one would notice for weeks.
"""
from __future__ import annotations

import collections
import datetime as dt
from typing import Dict, List, Optional, Sequence

from . import clean
from .sheet import (_ensure_tab, _norm_id, _open, _retry, PROTECTED_TABS,
                    SHEET_ID)

TAB = "Box Sales Log"
DAYS_KEPT = 60

HEADERS = ("Week Ending", "Rep Name", "Sale Date", "Business Name",
           "Contract ID", "Account Id", "Status", "Contr. Sub-status",
           "Secondary Status", "Accepted Date", "BF Tier", "Term",
           "Complete Sales", "Sales (All) kWH+Therms", "Last Updated",
           "Notes", "Box Notes")

_COL_WEEK = HEADERS.index("Week Ending")
_COL_SALE = HEADERS.index("Sale Date")
_COL_CONTRACT = HEADERS.index("Contract ID")
_COL_ACCOUNT = HEADERS.index("Account Id")
_COL_STATUS = HEADERS.index("Status")
_COL_UPDATED = HEADERS.index("Last Updated")
_COL_NOTES = HEADERS.index("Notes")
_COL_BOX_NOTES = HEADERS.index("Box Notes")
_COL_SECONDARY = HEADERS.index("Secondary Status")


def week_ending_sunday(d: dt.date) -> dt.date:
    """The SUNDAY closing d's Mon-Sun week (a Sunday maps to itself)."""
    return d + dt.timedelta(days=6 - d.weekday())


def _fmt(d: Optional[dt.date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


def _key(row: Sequence[str]) -> tuple:
    def at(i):
        return _norm_id(row[i]) if len(row) > i else ""
    return (at(_COL_CONTRACT), at(_COL_ACCOUNT))


def _sale_row(s, stamp: str) -> List[str]:
    f = s.fields
    return [
        _fmt(week_ending_sunday(s.sale_date)) if s.sale_date else "",
        (f.get("Rep Name") or "").strip(),
        _fmt(s.sale_date),
        (f.get("Business Name") or "").strip(),
        (f.get("Contract ID") or "").strip(),
        (f.get("Account Id") or "").strip(),
        s.status,
        s.sub_status,
        s.secondary,
        (f.get("Accepted Date") or "").strip(),
        (f.get("BF Tier") or "").strip(),
        (f.get("Term") or "").strip(),
        (f.get("Complete Sales") or "").strip(),
        (f.get("Sales (All) kWH+Therms") or "").strip(),
        stamp,
        "",                                  # Notes — Carlos's, never ours
        "",                                  # Box Notes — the email sweep's
    ]


def merge(existing: Sequence[Sequence[str]], sales: Sequence, *,
          today: dt.date) -> Dict[str, object]:
    """Same contract as sheet.merge_rows, against the 60-day window.

    Kept-if-absent (the source forgets before we do), replaced-if-present,
    aged-out past 60 days by SALE date. Carried rows keep their TPV-passed
    immunity: a dead status alone doesn't purge a row here either — on this
    tab a row only ever leaves through the date window, which is Carlos's
    "unless we're past the date range" verbatim.
    """
    stamp = _fmt(today)
    merged: "collections.OrderedDict[tuple, List[str]]" = collections.OrderedDict()
    for row in existing:
        row = list(row) + [""] * (len(HEADERS) - len(row))
        if any(_key(row)):
            merged[_key(row)] = row

    oldest = today - dt.timedelta(days=DAYS_KEPT)
    added = changed = 0
    for s in sales:
        # A pulled sale already outside the window would be counted "added"
        # and then aged out two lines later — skip it up front so the run
        # log's numbers describe what actually landed on the tab.
        if s.sale_date and s.sale_date < oldest:
            continue
        fresh = _sale_row(s, stamp)
        prior = merged.get(_key(fresh))
        if prior is None:
            added += 1
        elif prior[_COL_STATUS].strip() == fresh[_COL_STATUS].strip():
            fresh[_COL_UPDATED] = prior[_COL_UPDATED] or stamp
        else:
            changed += 1
        # Carlos types into Notes by hand and the tab is CLEARED and rewritten
        # every run — the merge is the only thing keeping his words alive.
        # Carried by sale key, so a note follows its deal through re-sorts and
        # status changes, and dies only when the row ages off the window.
        if prior is not None and len(prior) > _COL_NOTES:
            fresh[_COL_NOTES] = prior[_COL_NOTES]
        # Box Notes is the EMAIL column — written from the mini by the
        # box-notes-email-sweep scheduled task (Lucy 2 has no Gmail), carried
        # here exactly like Carlos's Notes so the twice-daily rewrite can't
        # eat what the sweep wrote between runs.
        if prior is not None and len(prior) > _COL_BOX_NOTES:
            fresh[_COL_BOX_NOTES] = prior[_COL_BOX_NOTES]
        merged[_key(fresh)] = fresh

    kept, aged = [], 0
    for row in merged.values():
        sd = clean._parse_date(row[_COL_SALE])
        if sd and sd < oldest:
            aged += 1
            continue
        kept.append(row)

    kept.sort(key=lambda r: (
        -(clean._parse_date(r[_COL_SALE]) or dt.date.min).toordinal(),
        r[1], clean._status_rank(r[_COL_STATUS])))
    return {"rows": kept, "added": added, "changed": changed, "aged_out": aged}


def push(sales: Sequence, *, today: Optional[dt.date] = None,
         sheet_id: Optional[str] = None, log=print) -> Dict[str, object]:
    if TAB in PROTECTED_TABS:
        raise RuntimeError("refusing to write: target tab is protected")
    sh = _open(sheet_id)
    today = today or dt.date.today()

    ws = _ensure_tab(sh, TAB, cols=len(HEADERS))
    prior = _retry(lambda: ws.get_all_values())
    result = merge(prior[1:] if prior else [], sales, today=today)
    rows = result["rows"]
    if not rows:
        raise RuntimeError("flat log merge produced no rows — refusing to "
                           "blank the tab")

    body = [list(HEADERS)] + rows
    _retry(lambda: ws.resize(rows=max(1000, len(body) + 50), cols=len(HEADERS)))
    # IDs as TEXT before writing — they are the merge key (see sheet.py).
    _retry(lambda: sh.batch_update({"requests": [
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 1,
                      "startColumnIndex": c, "endColumnIndex": c + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
            "fields": "userEnteredFormat.numberFormat"}}
        for c in (_COL_CONTRACT, _COL_ACCOUNT)]}))
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(body, "A1", value_input_option="USER_ENTERED"))

    # Header look + frozen row + the actual point: a basic filter on the
    # headers. setBasicFilter replaces any existing one, so re-runs never
    # stack; it also survives (and re-scopes to) the new row count.
    _retry(lambda: sh.batch_update({"requests": [
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": len(HEADERS)},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 0.24, "green": 0.24, "blue": 0.24},
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True, "foregroundColor": {
                    "red": 1, "green": 1, "blue": 1}}}},
            "fields": ("userEnteredFormat(backgroundColor,"
                       "horizontalAlignment,textFormat)")}},
        {"updateSheetProperties": {
            "properties": {"sheetId": ws.id,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
        {"setBasicFilter": {"filter": {"range": {
            "sheetId": ws.id, "startRowIndex": 0,
            "endRowIndex": len(body), "startColumnIndex": 0,
            "endColumnIndex": len(HEADERS)}}}},
    ]}))
    # Status colors, same palette and meaning as the main log tab — derived
    # from clean.STATUS_COLORS so a ruling that recolors one recolors both
    # (a hardcoded copy went stale on the view tab once; see sheet.py).
    # Row-scoped CUSTOM_FORMULA rules; ours are cleared first so re-runs
    # never stack duplicates (same approach as sheet._clear_color_rules).
    from .sheet import _clear_color_rules, _rgb
    def col_letter(i):
        out = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            out = chr(65 + r) + out
        return out
    st = "$" + col_letter(_COL_STATUS) + "2"
    sec = "$" + col_letter(_COL_SECONDARY) + "2"
    was_submitted = 'ISNUMBER(SEARCH("{s}",{h}))'.format(s=clean.SUBMITTED, h=sec)
    rng = {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": len(body),
           "startColumnIndex": 0, "endColumnIndex": len(HEADERS)}
    specs = [
        (clean.STATUS_COLORS["Ready For Booking"],
         '={st}="Ready For Booking"'.format(st=st)),
        (clean.GREEN, '={st}="Accepted by Supplier"'.format(st=st)),
        (clean.RED_BRIGHT, '={st}="Incomplete"'.format(st=st)),
        (clean.RED, '=OR({st}="Cancelled by Broker",{st}="Rejected",'
                    '{st}="Dropped")'.format(st=st)),
        (clean.YELLOW, '=OR({st}="{sub}",AND({st}="Verification",{ws}))'
                       .format(st=st, sub=clean.SUBMITTED, ws=was_submitted)),
        (clean.ORANGE, '=AND({st}="Verification",NOT({ws}))'
                       .format(st=st, ws=was_submitted)),
    ]
    reqs = _clear_color_rules(sh, ws.id)
    for i, (hexv, formula) in enumerate(specs):
        reqs.append({"addConditionalFormatRule": {
            "index": i,
            "rule": {"ranges": [rng],
                     "booleanRule": {
                         "condition": {"type": "CUSTOM_FORMULA",
                                       "values": [{"userEnteredValue": formula}]},
                         "format": {"backgroundColor": _rgb(hexv)}}}}})
    # Notes column: readable width + wrap, so a sentence doesn't vanish.
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                  "startIndex": _COL_NOTES, "endIndex": _COL_BOX_NOTES + 1},
        "properties": {"pixelSize": 260}, "fields": "pixelSize"}})
    reqs.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 1,
                  "startColumnIndex": _COL_NOTES,
                  "endColumnIndex": _COL_BOX_NOTES + 1},
        "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat.wrapStrategy"}})
    # Bordering (Carlos 2026-09-08: "more lines"). Repainted every run like
    # the color rules — the clear+rewrite wipes cell borders, so they have to
    # ride the same batch. Grey grid on every cell, a heavier line under the
    # header and around the outside.
    grey = {"style": "SOLID", "color": _rgb("B7B7B7")}
    heavy = {"style": "SOLID_MEDIUM", "color": _rgb("3D3D3D")}
    body_rng = {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": len(body),
                "startColumnIndex": 0, "endColumnIndex": len(HEADERS)}
    reqs.append({"updateBorders": {
        "range": body_rng,
        "top": heavy, "bottom": heavy, "left": heavy, "right": heavy,
        "innerHorizontal": grey, "innerVertical": grey}})
    reqs.append({"updateBorders": {
        "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": len(HEADERS)},
        "bottom": heavy}})
    _retry(lambda: sh.batch_update({"requests": reqs}))

    log("  {} tab: {} rows ({} new, {} status changes, {} aged out past "
        "{} days)".format(TAB, len(rows), result["added"], result["changed"],
                          result["aged_out"], DAYS_KEPT))
    return result
