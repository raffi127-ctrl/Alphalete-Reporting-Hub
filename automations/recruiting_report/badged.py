"""Badged Reps + Badged % on the ATT Program - Focus Report (Raf, Loom 2026-10-07).

WHAT RAF ASKED. Two rows in every ICD tab's OPT section, right under
"New Start Retention" -- the same two rows he added to the owners' All-in-One
template:
  * Badged Reps  -- how many new starts got badged that week.
  * Badged %     -- Badged Reps / New Starts Showed, goal 50%. A formula, so it
                    follows whatever the recruiting run puts in New Starts Showed.
On the All-in-One the owner types Badged Reps by hand; HERE nobody does, we pull it.

WHERE THE NUMBER COMES FROM. OwnerVille -> CEO Dashboard (p=9197) -> Recruiting
-> Recruiting Pipeline -> ONBOARDING -> BADGED. That table is drawn from one JSON
call, which is what we read:

    v2.ownerville.com/components/prototypes/prototypes.cfc
        ?method=getRecruitOnboardingWeekly&officeId=<office>&rqst=<token>

-> {"data": {"weeks": [{"wk": "2026-09-27", "bobSched": 14, "bobShowed": 8,
                        "badged": 5, ...}, ...]}}

`bobSched`/`bobShowed`/`badged` are the table's NS SCHED / NS SHOWED / BADGED.
It takes any office id straight (no Office Access impersonation needed), and the
office id is the same one office-mapping.json carries for AppStream.

WEEK -> COLUMN. `wk` is the Sunday the week STARTS; the tab's row-1 header is
the Sunday AFTER it (WE), so OV's 9/27-10/3 lands in the 10/4 column. Checked
2026-10-08 on Marcellus Butler (22069): OV NS SHOWED 9/13=1, 9/20=4, 9/27=8 and
the sheet's New Starts Showed in the 9/20, 9/27, 10/4 columns is 1, 4, 8.

ALWAYS THE LAST 4 WEEKS. A new start badged late lands in the week they STARTED,
so last month's number keeps climbing (Raf: someone from the week of 9/19 who
badges today raises 9/19). Every run rewrites the last 4 closed weeks.

Run:
  python -m automations.recruiting_report.badged --only "Marcellus Butler" --dry-run
  python -m automations.recruiting_report.badged --only "Marcellus Butler"
  python -m automations.recruiting_report.badged            # every mapped tab
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.recruiting_report import fill

REPO = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO / "output"

BADGED_LABEL = "Badged Reps"
BADGED_PCT_LABEL = "Badged %"
BADGED_PCT_GOAL = 0.5
WEEKS_BACK = 4

ENDPOINT = ("https://v2.ownerville.com/components/prototypes/prototypes.cfc"
            "?method=getRecruitOnboardingWeekly&officeId={office}&rqst={rqst}")


# --- weeks ------------------------------------------------------------------

def _today_ct() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:
        return dt.date.today()


def weeks_to_write(today: Optional[dt.date] = None, n: int = WEEKS_BACK) -> List[dt.date]:
    """The last `n` CLOSED Sun-Sat weeks, oldest first, as their start Sunday.
    Thursday 10/8 -> 9/6, 9/13, 9/20, 9/27 (10/4 is still running)."""
    today = today or _today_ct()
    this_sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return [this_sunday - dt.timedelta(days=7 * k) for k in range(n, 0, -1)]


# --- OwnerVille -------------------------------------------------------------

def parse_weeks(payload: dict) -> Optional[Dict[dt.date, int]]:
    """{week start Sunday: badged} from one office's JSON. None = the office
    returned nothing at all (no access / unknown id) -- not the same as zeros."""
    weeks = ((payload or {}).get("data") or {}).get("weeks")
    if not weeks:
        return None
    out: Dict[dt.date, int] = {}
    for w in weeks:
        try:
            out[dt.date.fromisoformat(str(w["wk"])[:10])] = int(float(w.get("badged") or 0))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def fetch_live(office_ids: List[str], *, headless: bool = True) -> Dict[str, dict]:
    """Raw JSON per office, read through the machine's OwnerVille session."""
    from automations.b2b_dispositions.capture import capture_rqst
    from automations.shared.tableau_patchright import ownerville_session

    raw: Dict[str, dict] = {}
    with ownerville_session(headless=headless) as page:
        rqst = capture_rqst(page)
        for oid in office_ids:
            url = ENDPOINT.format(office=oid, rqst=rqst)
            try:
                raw[oid] = page.evaluate(
                    "async (u) => { const r = await fetch(u, {credentials: 'include'});"
                    " return r.ok ? await r.json() : {error: r.status}; }", url)
            except Exception as e:  # one office failing must not sink the rest
                raw[oid] = {"error": str(e)[:200]}
            print(f"  OV {oid}: {'ok' if parse_weeks(raw[oid]) else raw[oid].get('error', 'no data')}",
                  flush=True)
    return raw


# --- sheet layout -----------------------------------------------------------

def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def find_rows(col_b: List[str]) -> Dict[str, Optional[int]]:
    """1-indexed rows by column-B label. The OPT 'New Start Retention' is the
    one AFTER the 'OPT' section header (the recruiting block has its own)."""
    rows: Dict[str, Optional[int]] = {"ns_showed": None, "opt": None,
                                      "opt_nsr": None, "badged": None, "badged_pct": None}
    for i, v in enumerate(col_b, start=1):
        n = _norm(v)
        if n == "new starts showed" and rows["ns_showed"] is None:
            rows["ns_showed"] = i
        elif n == "opt" and rows["opt"] is None:
            rows["opt"] = i
        elif n == "new start retention" and rows["opt"] and rows["opt_nsr"] is None:
            rows["opt_nsr"] = i
        elif n == _norm(BADGED_LABEL) and rows["badged"] is None:
            rows["badged"] = i
        elif n == _norm(BADGED_PCT_LABEL) and rows["badged_pct"] is None:
            rows["badged_pct"] = i
    return rows


def sheet_col(cols: Dict[dt.date, int], ov_week: dt.date) -> Optional[int]:
    """0-based column for an OV week. The tab's header is the Sunday AFTER the
    week (WE), so OV's 9/27-10/3 week lives in the 10/4 column.
    `cols` is fill.find_sunday_columns output (1-indexed)."""
    c = cols.get(ov_week + dt.timedelta(days=7))
    return None if c is None else c - 1


def _col_letter(c0: int) -> str:
    s, c = "", c0 + 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def ensure_rows(sh, ws, *, dry_run: bool) -> Tuple[Optional[Dict[str, int]], str]:
    """Insert the two rows under OPT 'New Start Retention' if the tab doesn't
    have them yet. Inserting (never overwriting) keeps everyone's data; every
    report finds its rows by label, so the shift below is harmless."""
    col_b = fill._retry(ws.col_values, fill.LABEL_COLUMN)
    rows = find_rows(col_b)
    if rows["badged"] and rows["badged_pct"]:
        return rows, "rows already there"
    if not rows["ns_showed"] or not rows["opt_nsr"]:
        return None, "no 'New Starts Showed' / OPT 'New Start Retention' label -- not a Fiber layout"
    if rows["badged"] or rows["badged_pct"]:
        return None, "only one of the two Badged rows exists -- fix by hand"

    at = rows["opt_nsr"]                     # new rows land at at+1, at+2
    eow_row = at - 1                         # 'New Starts by EOW' -- count format
    header = fill._retry(ws.row_values, fill.HEADER_ROW)
    # find_sunday_columns is 1-indexed; everything below is 0-based
    week_cols = sorted(c - 1 for c in fill.find_sunday_columns([header]).values())
    if dry_run:
        return ({**rows, "badged": at + 1, "badged_pct": at + 2},
                f"WOULD insert rows {at + 1}-{at + 2} ({len(week_cols)} week columns)")

    sid = ws.id
    last_col = ws.col_count
    reqs = [
        {"insertDimension": {"range": {"sheetId": sid, "dimension": "ROWS",
                                       "startIndex": at, "endIndex": at + 2},
                             "inheritFromBefore": True}},
        # formats: counts like 'New Starts by EOW', % like 'New Start Retention'
        {"copyPaste": {"source": {"sheetId": sid, "startRowIndex": eow_row - 1, "endRowIndex": eow_row,
                                  "startColumnIndex": 0, "endColumnIndex": last_col},
                       "destination": {"sheetId": sid, "startRowIndex": at, "endRowIndex": at + 1,
                                       "startColumnIndex": 0, "endColumnIndex": last_col},
                       "pasteType": "PASTE_FORMAT"}},
        {"copyPaste": {"source": {"sheetId": sid, "startRowIndex": at - 1, "endRowIndex": at,
                                  "startColumnIndex": 0, "endColumnIndex": last_col},
                       "destination": {"sheetId": sid, "startRowIndex": at + 1, "endRowIndex": at + 2,
                                       "startColumnIndex": 0, "endColumnIndex": last_col},
                       "pasteType": "PASTE_FORMAT"}},
    ]
    fill._retry(sh.batch_update, {"requests": reqs})

    b, p, ns = at + 1, at + 2, rows["ns_showed"]
    data = [{"range": f"A{b}:B{p}", "values": [["", BADGED_LABEL], [BADGED_PCT_GOAL, BADGED_PCT_LABEL]]}]
    # Blank until a Badged number exists, so empty weeks don't read as a red 0%.
    for c in week_cols:
        L = _col_letter(c)
        data.append({"range": f"{L}{p}",
                     "values": [[f'=IF({L}{b}="","",IFERROR({L}{b}/{L}{ns},0))']]})
    fill._retry(ws.batch_update, data, value_input_option="USER_ENTERED")
    return {**rows, "badged": b, "badged_pct": p}, f"inserted rows {b}-{p}"


# --- main -------------------------------------------------------------------

def tabs_to_offices(mapping: dict) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for e in mapping.get("confirmed") or []:
        tab, oid = (e.get("sheet_tab") or "").strip(), str(e.get("office_id") or "").strip()
        if tab and oid and oid not in out.setdefault(tab, []):
            out[tab].append(oid)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", action="append", help="tab name (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="read + print, write nothing")
    ap.add_argument("--from-json", help="use a saved OV pull instead of logging in")
    ap.add_argument("--today", help="YYYY-MM-DD, for testing the 4-week window")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--all-weeks", action="store_true",
                    help="write every closed week OV has, not just the last 4")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.today) if args.today else None
    weeks = weeks_to_write(today)
    tab_offices = tabs_to_offices(fill.load_mapping())
    if args.only:
        want = {_norm(t) for t in args.only}
        tab_offices = {t: o for t, o in tab_offices.items() if _norm(t) in want}
        missing = want - {_norm(t) for t in tab_offices}
        if missing:
            print(f"not in office-mapping confirmed: {sorted(missing)}")
    tab_offices.pop(fill._CFG["master_tab"], None)  # Raf Hidalgo = 2-row-header master tab
    print(f"weeks: {', '.join(w.strftime('%m/%d') for w in weeks)} | tabs: {len(tab_offices)}")

    multi = {t: o for t, o in tab_offices.items() if len(o) > 1}
    office_ids = sorted({o[0] for t, o in tab_offices.items() if t not in multi})
    if args.from_json:
        raw = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        raw = fetch_live(office_ids, headless=not args.headed)
        OUTPUT_DIR.mkdir(exist_ok=True)
        (OUTPUT_DIR / f"badged_ov_{_today_ct().isoformat()}.json").write_text(
            json.dumps(raw), encoding="utf-8")

    sh = fill.open_sheet()
    result: List[Tuple[str, str]] = []
    for tab in sorted(tab_offices):
        if tab in multi:
            result.append((tab, f"SKIPPED: {len(multi[tab])} offices on one tab ({', '.join(multi[tab])})"))
            continue
        oid = tab_offices[tab][0]
        by_week = parse_weeks(raw.get(oid) or {})
        if by_week is None:
            result.append((tab, f"SKIPPED: no OwnerVille data for office {oid}"))
            continue
        try:
            ws = fill.worksheet_ci(sh, tab)
        except Exception:
            result.append((tab, "SKIPPED: tab not found"))
            continue
        rows, note = ensure_rows(sh, ws, dry_run=args.dry_run)
        if not rows:
            result.append((tab, f"SKIPPED: {note}"))
            continue
        header = fill._retry(ws.row_values, fill.HEADER_ROW)
        cols = fill.find_sunday_columns([header])
        data, shown = [], []
        # First time a tab gets the rows (or --all-weeks): every closed week OV
        # knows, so the row isn't blank behind the last 4. Before OV's first
        # week stays blank -- no source, and a 0 there would be a made-up number.
        tab_weeks = weeks
        if args.all_weeks or note.startswith("inserted"):
            tab_weeks = sorted(w for w in by_week if w <= weeks[-1])
        for w in tab_weeks:
            col = sheet_col(cols, w)
            if col is None:
                continue
            v = by_week.get(w, 0)
            data.append({"range": f"{_col_letter(col)}{rows['badged']}", "values": [[v]]})
            shown.append(f"{w.strftime('%m/%d')}={v}")
        if data and not args.dry_run:
            fill._retry(ws.batch_update, data, value_input_option="USER_ENTERED")
        verb = "would write" if args.dry_run else "wrote"
        result.append((tab, f"{note}; {verb} Badged (office {oid}) {' '.join(shown)}"))

    # the template too, so a tab duplicated from it is born with the two rows
    if not args.only:
        try:
            _, note = ensure_rows(sh, fill.worksheet_ci(sh, fill._CFG["template_tab"]),
                                  dry_run=args.dry_run)
            result.append((fill._CFG["template_tab"], note))
        except Exception as e:
            result.append((fill._CFG["template_tab"], f"SKIPPED: {e}"))

    for tab, msg in result:
        print(f"  {tab}: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
