"""Recruiter Stats — per-admin weekly funnel boxes on the Alphalete Recruiting
Dashboard (Carlos 2026-09-05; one-time build, may become an automation).

For Carlos (11580), Atef (23467) and Raf (11280): scrape the AppStream p=701
Retention Details report with the admin breakdown ON for every Sun-Sat week of
the current year, then build ONE visible 'Recruiter Stats' tab with an office
DROPDOWN (B1) that mirrors hidden per-office storage tabs ("RS Data - <name>")
via a spilled INDIRECT. Per office: one box per admin — Week | Interviews
Booked | Retention Call List | Total First Interviews | 1st Showed Up |
1st Retention — weeks NEWEST FIRST plus a YTD TOTAL row.

Color logic lives in conditional-formatting FORMULAS on the visible tab so it
follows the dropdown live: the top data row (the row right under a "Week"
header) is graded against the AVERAGE of the 4 cells below it (that SAME
person's prior 4 weeks): GREEN at/above, YELLOW within 5% below, RED more than
5% below. Person-title rows blue, "Week" header rows grey, YTD rows grey.

Retention Call List per person = that person's interviews booked ÷ the
office's Sent to Call List for the week (AppStream reports it office-wide).
Week labels use the STARTING Sunday of the AppStream Sun-Sat week.

Runs wholly on Lucy 2 (live AppStream session + writes the Recruiting
Dashboard already, via ad_sales_board). Raw scrape is cached to
output/recruiter_stats_raw.json so layout re-runs skip the ~20-min pull.

  lucy rerun recruiter_stats                    # pull + build
  ... run.py --no-pull                          # rebuild tabs from cached raw
  ... run.py --dry-run                          # pull, print summary, no write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.recruiting_report import fetch_office as fo
from automations.recruiting_report import fill as _fill
from automations.recruiter_retention.run import _admin_on, _rqst

DASHBOARD_ID = "111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA"
TAB = "Recruiter Stats"
DATA_PREFIX = "RS Data - "
RAW_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "recruiter_stats_raw.json"

OFFICES = [("11580", "Carlos Hidalgo"),
           ("23467", "Atef Choudhury"),
           ("11280", "Rafael Hidalgo")]

# Only these report sections are kept (payload + relevance)
KEEP = ["Interviews Booked", "Sent to Call List", "Total First Interviews",
        "First Interviews Showed Up", "Retention First Interviews",
        "Retention Call List"]

HEADER = ["Week", "Interviews Booked", "Retention Call List",
          "Total First Interviews", "1st Showed Up", "1st Retention"]
BOX_COLS = 6

GREEN = {"red": 0.71, "green": 0.84, "blue": 0.66}
YELL = {"red": 1.0, "green": 0.9, "blue": 0.55}
RED = {"red": 0.96, "green": 0.78, "blue": 0.76}
BLUE = {"red": 0.82, "green": 0.88, "blue": 0.97}
GREYBG = {"red": 0.9, "green": 0.9, "blue": 0.9}


# ------------------------------------------------------------------ scrape
def _load_week(page, sunday):
    rqst = _rqst(page)
    url = f"https://applicantstream.com/index.cfm?rqst={rqst}&p=701"
    last_err = None
    for attempt in range(3):
        try:
            page.goto(url, wait_until="commit", timeout=40000)
            page.wait_for_selector("#weekStart", timeout=20000)
            last_err = None
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            page.wait_for_timeout(2000)
    if last_err is not None:
        raise last_err
    _admin_on(page)
    try:
        fo._set_week_and_submit(page, sunday)
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] week set {sunday}: {e}", flush=True)
    page.wait_for_timeout(1200)
    if not page.evaluate("() => !!document.querySelector('tr.adminRow')"):
        _admin_on(page)
        try:
            with page.expect_navigation(timeout=12000, wait_until="load"):
                page.evaluate(
                    """() => { const b=[...document.querySelectorAll('input[type=submit],button,a')]
                        .find(e=>/get report/i.test(e.innerText||e.value||'')); if(b)b.click(); }""")
        except Exception:
            pass
        page.wait_for_timeout(1200)


def _parse(page):
    rows = page.evaluate(
        """() => { const t = [...document.querySelectorAll('table')]
            .sort((a,b)=>b.querySelectorAll('tr').length-a.querySelectorAll('tr').length)[0];
            if (!t) return [];
            return [...t.querySelectorAll('tr')].map(tr => ({cls: tr.className||'',
                texts: [...tr.querySelectorAll('th,td')].map(c=>(c.innerText||'').replace(/\\s+/g,' ').trim())})); }""")
    out, cur = {}, None
    for r in rows:
        texts = r["texts"]
        if not texts or not texts[0]:
            continue
        if "adminRow" in r["cls"]:
            if cur is not None:
                cur["admins"][texts[0]] = texts[1:9]
        else:
            label = texts[0]
            match = next((k for k in KEEP if label == k or label.startswith(k)), None)
            if match:
                cur = {"cells": texts[1:9], "admins": {}}
                out[match] = cur
            else:
                cur = None
    return out


def year_weeks(today):
    """Every Sun-Sat week's starting Sunday from the first Sunday of the year
    through the current week's Sunday, oldest first."""
    cur_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    d = dt.date(today.year, 1, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)     # first Sunday of the year
    out = []
    while d <= cur_sun:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def pull(weeks, offices, verbose=True):
    from automations.shared.tableau_patchright import appstream_direct_session
    raw = {oid: {} for oid, _ in offices}
    with appstream_direct_session(verbose=verbose) as page:
        page.wait_for_timeout(3000)
        page.wait_for_selector("#searchMC", timeout=20000)
        for oid, owner in offices:
            if not fo._switch_office(page, oid, owner, confirm_denial=True):
                print(f"⚠ cannot reach office {oid} ({owner}) — skipped", flush=True)
                continue
            page.wait_for_timeout(1200)
            for sun in weeks:
                _load_week(page, sun)
                raw[oid][sun.isoformat()] = _parse(page)
                if verbose:
                    n = sum(len(s["admins"]) for s in raw[oid][sun.isoformat()].values())
                    print(f"  {owner} {sun}: {n} admin rows", flush=True)
            RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
            RAW_PATH.write_text(json.dumps(raw))       # checkpoint per office
    return raw


# ------------------------------------------------------------------ build
def _num(s):
    s = (s or "").strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _wk_val(offraw, wk, label, person):
    sec = offraw.get(wk, {}).get(label)
    if not sec:
        return None
    row = sec["cells"] if person is None else sec["admins"].get(person, [])
    return _num(row[7]) if len(row) > 7 else None


def _metrics(offraw, wk, person):
    booked = _wk_val(offraw, wk, "Interviews Booked", person)
    sent = _wk_val(offraw, wk, "Sent to Call List", None) or 0
    first = _wk_val(offraw, wk, "Total First Interviews", person)
    showed = _wk_val(offraw, wk, "First Interviews Showed Up", person)
    ret_cl = (booked / sent) if sent and booked is not None else None
    ret = (showed or 0) / first if first else None
    return booked, ret_cl, first, showed, ret


def _roster(offraw, weeks_iso):
    """Anyone with any booked/first/showed value this year, by year booked desc."""
    people = {}
    for wk in weeks_iso:
        for label in ("Interviews Booked", "Total First Interviews",
                      "First Interviews Showed Up"):
            sec = offraw.get(wk, {}).get(label)
            for name, cells in (sec or {"admins": {}})["admins"].items():
                v = _num(cells[7]) if len(cells) > 7 else None
                if v:
                    people[name] = people.get(name, 0) + (
                        v if label == "Interviews Booked" else 0)
    return sorted(people, key=lambda n: -people[n])


def office_rows(offraw, weeks_iso, roster):
    """Stacked per-admin boxes: title / header / weeks newest-first / YTD."""
    rows = []
    for person in roster:
        rows.append([person, "", "", "", "", ""])
        rows.append(HEADER[:])
        tb = ts = tf = tsh = 0
        for wk in reversed(weeks_iso):
            d = dt.date.fromisoformat(wk)
            booked, ret_cl, first, showed, ret = _metrics(offraw, wk, person)
            rows.append([f"{d.month}/{d.day}",
                         "" if booked is None else booked,
                         "" if ret_cl is None else round(ret_cl, 4),
                         "" if first is None else first,
                         "" if showed is None else showed,
                         "" if ret is None else round(ret, 4)])
            tb += booked or 0
            if booked is not None:
                ts += _wk_val(offraw, wk, "Sent to Call List", None) or 0
            tf += first or 0
            tsh += showed or 0
        rows.append(["YTD TOTAL", tb,
                     round(tb / ts, 4) if ts else "", tf, tsh,
                     round(tsh / tf, 4) if tf else ""])
        rows.append(["", "", "", "", "", ""])
    return rows


def _rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _fmt(sid, r0, r1, c0, c1, f):
    return {"repeatCell": {"range": _rng(sid, r0, r1, c0, c1),
                           "cell": {"userEnteredFormat": f},
                           "fields": "userEnteredFormat("
                                     + ",".join(f.keys()) + ")"}}


def _ensure_tab(sh, title, rows, cols):
    try:
        ws = sh.worksheet(title)
        if ws.row_count < rows or ws.col_count < cols:
            ws.resize(rows=max(ws.row_count, rows), cols=max(ws.col_count, cols))
        return ws
    except Exception:  # noqa: BLE001 — first build creates the tab
        return sh.add_worksheet(title=title, rows=rows, cols=cols)


def _cf_rules(sid, end_row):
    """CF formulas anchored at row 2 (first spilled row on the visible tab).
    Row/col refs are RELATIVE except the $A column lock, so each rule grades
    every box wherever the dropdown lands it."""
    full = [_rng(sid, 1, end_row, 0, BOX_COLS)]
    data = [_rng(sid, 1, end_row, 1, BOX_COLS)]

    def rule(ranges, formula, color, bold=False):
        fmt = {"backgroundColor": color}
        if bold:
            fmt["textFormat"] = {"bold": True}
        return {"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": ranges,
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                          "values": [{"userEnteredValue": formula}]},
                            "format": fmt}}}}

    # Listed lowest-precedence first; each insert at index 0 pushes earlier
    # ones down, so the FINAL order is: header grey, YTD grey, title blue,
    # then green > yellow > red on the newest-week data row.
    return [
        rule(data, '=AND(ISNUMBER(B2),$A1="Week",B2<0.95*AVERAGE(B3:B6))', RED),
        rule(data, '=AND(ISNUMBER(B2),$A1="Week",B2>=0.95*AVERAGE(B3:B6))', YELL),
        rule(data, '=AND(ISNUMBER(B2),$A1="Week",B2>=AVERAGE(B3:B6))', GREEN),
        rule(full, '=AND($A2<>"",$B2="",$C2="",$D2="",$E2="",$F2="",$A2<>"YTD TOTAL")',
             BLUE, bold=True),
        rule(full, '=$A2="YTD TOTAL"', GREYBG, bold=True),
        rule(full, '=$A2="Week"', GREYBG, bold=True),
    ]


def build(raw, weeks, offices, dry=False):
    weeks_iso = [w.isoformat() for w in weeks]

    grids = {}
    for oid, owner in offices:
        offraw = raw.get(oid, {})
        roster = _roster(offraw, weeks_iso)
        print(f"{owner}: {len(roster)} admins — {roster}", flush=True)
        grids[owner] = office_rows(offraw, weeks_iso, roster)
    if dry:
        print("(dry-run) no writes", flush=True)
        return

    sh = _fill.open_by_key(DASHBOARD_ID)
    max_rows = max((len(g) for g in grids.values()), default=0)
    end_row = max_rows + 1                      # spill starts at visible row 2
    store_rows = max(max_rows + 20, 200)

    # ---- hidden per-office storage tabs
    hide_reqs = []
    for oid, owner in offices:
        ws = _ensure_tab(sh, DATA_PREFIX + owner, store_rows, BOX_COLS + 2)
        ws.clear()
        grid = grids[owner]
        if grid:
            ws.update(range_name="A1", values=grid, value_input_option="RAW")
        hide_reqs.append({"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "hidden": True},
            "fields": "hidden"}})

    # ---- visible dropdown tab
    vt = _ensure_tab(sh, TAB, end_row + 6, BOX_COLS + 2)
    vt.clear()
    sid = vt.id
    meta = sh.fetch_sheet_metadata()
    cf_count = 0
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sid:
            cf_count = len(s.get("conditionalFormats", []))
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
            for i in range(cf_count - 1, -1, -1)]

    vt.update(range_name="A1", values=[["Office:"]], value_input_option="RAW")
    vt.update(range_name="B1",
              values=[[offices[0][1]]], value_input_option="RAW")
    vt.update(range_name="A2",
              values=[[f'=INDIRECT("\'{DATA_PREFIX}"&$B$1&"\'!A1:F{max_rows}")']],
              value_input_option="USER_ENTERED")

    reqs += hide_reqs
    reqs.append({"setDataValidation": {
        "range": _rng(sid, 0, 1, 1, 2),
        "rule": {"condition": {"type": "ONE_OF_LIST",
                               "values": [{"userEnteredValue": o[1]} for o in offices]},
                 "showCustomUi": True, "strict": True}}})
    reqs += [
        _fmt(sid, 0, 1, 0, 1, {"textFormat": {"bold": True, "fontSize": 11},
                               "horizontalAlignment": "RIGHT"}),
        _fmt(sid, 0, 1, 1, 2, {"textFormat": {"bold": True, "fontSize": 11},
                               "backgroundColor": BLUE,
                               "horizontalAlignment": "CENTER"}),
        # C/F are the two pct columns in every box; text cells ignore numfmt
        _fmt(sid, 1, end_row, 2, 3,
             {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}),
        _fmt(sid, 1, end_row, 5, 6,
             {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}),
        _fmt(sid, 1, end_row, 0, BOX_COLS,
             {"horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"}),
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 90}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": BOX_COLS},
            "properties": {"pixelSize": 118}, "fields": "pixelSize"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sid,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"}},
    ]
    reqs += _cf_rules(sid, end_row)
    sh.batch_update({"requests": reqs})

    newest = weeks[-1]
    note = (f"Pick an office in B1. Top row of each box (week of "
            f"{newest.month}/{newest.day}) is graded vs that SAME person's "
            "prior-4-week average: GREEN at/above · YELLOW within 5% below · "
            "RED more than 5% below. Retention Call List per person = their "
            "interviews booked ÷ the office's Sent to Call List for the week "
            "(AppStream reports it office-wide). Weeks are labeled by their "
            "starting Sunday.")
    vt.update(range_name=f"A{end_row + 2}", values=[[note]],
              value_input_option="RAW")
    sh.batch_update({"requests": [
        _fmt(sid, end_row + 1, end_row + 2, 0, BOX_COLS,
             {"textFormat": {"italic": True, "fontSize": 9},
              "horizontalAlignment": "LEFT", "wrapStrategy": "WRAP"})]})
    print(f"built '{TAB}' (+{len(offices)} hidden {DATA_PREFIX}* tabs) — "
          f"{max_rows} data rows", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="recruiter_stats")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-pull", action="store_true",
                    help="rebuild the tabs from output/recruiter_stats_raw.json")
    ap.add_argument("--date", default=None, help="override today (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    weeks = year_weeks(today)
    print(f"=== Recruiter Stats — {len(weeks)} weeks "
          f"({weeks[0]}..{weeks[-1]}), {len(OFFICES)} offices ===", flush=True)

    if args.no_pull and RAW_PATH.exists():
        raw = json.loads(RAW_PATH.read_text())
    else:
        raw = pull(weeks, OFFICES)
    build(raw, weeks, OFFICES, dry=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
