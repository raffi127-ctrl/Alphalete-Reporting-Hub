"""Ongoing 1st Round Recruiter Retention — weekly Hub report (Eve, Mondays).

Per recruiter, one 3-col block per week (Scheduled / Showed Up / Retention %)
on the '1st rd Recruiter %' tab. Weeks END on Sunday (Mon-Sun), labeled by the
ending Sunday. % = Showed / Scheduled.

AppStream's Retention Report is locked to Sun-Sat weeks, so we use the
"1-week-behind shift": the report column for the week ending Sunday D uses
AppStream's Sun-Sat week starting D-7 (summed). (Sundays are ~zero for
recruiting, so this ≈ the true Mon-Sun week; one pull per column.)

Active recruiters (scheduled an interview in the last 2 weeks) sort to the top
by latest-week retention desc; inactive go to the bottom as one contiguous
HIDDEN group. Retention % is color-coded: <45% red, 45-49.9% grey, >=50% green.

Each weekly run pulls just the AppStream week feeding the latest column and
reuses sheet history for the rest. --backfill re-pulls every week.

  python -m automations.recruiter_retention.run            # live, latest week
  python -m automations.recruiter_retention.run --dry-run
  python -m automations.recruiter_retention.run --backfill
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

# Emoji-safe on the Windows console (cp1252) — same guard the other reports use.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from patchright.sync_api import TimeoutError as PWTimeout
from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fetch_office as fo
from automations.recruiting_report.fill import open_by_key

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "1st rd Recruiter %"        # sheet tab (Hub card: "Ongoing 1st Round Recruiter Retention")
OFFICE_ID, OWNER = "11280", "Rafael Hidalgo"
REPORT_FIRST = dt.date(2026, 4, 12)   # first week-ENDING-Sunday column

# AppStream mainRow label (normalized) -> metric. (Booked dropped — % uses
# Showed/Scheduled, hide + the name-highlight key off Scheduled.)
SECTIONS = {"total first interviews": "Sch", "first interviews showed up": "SU"}

NAME_YELLOW = {"red": 1.0, "green": 0.898, "blue": 0.6}   # name highlight: scheduled in latest week
CHANNEL_BG = {"red": 0.85, "green": 0.82, "blue": 0.95}   # full-row tint for non-human channels
CHANNELS = {"ai messaging", "self scheduled"}             # interviews not booked by a person

BLOCK_W = 3                            # per week: Sch / SU / %
WE_ROW, SUB_ROW, FIRST_REC = 2, 4, 5
FIRST_BLOCK_COL = 2
HIDE_WINDOW = 2                        # hide if 0 SCHEDULED in last N weeks

CF_GREEN = {"red": 0.71, "green": 0.84, "blue": 0.66}
CF_GREY = {"red": 0.85, "green": 0.85, "blue": 0.85}
CF_RED = {"red": 0.96, "green": 0.78, "blue": 0.76}


# --------------------------------------------------------------------------- pull
def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _to_int(s):
    s = (s or "").strip().replace(",", "").rstrip("%").strip()
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return 0


def _rqst(page):
    m = re.search(r"rqst=([A-Za-z0-9_-]+)", page.url or "")
    if m:
        return m.group(1)
    try:
        m = re.search(r"rqst=([A-Za-z0-9_-]+)",
                      page.evaluate("() => document.documentElement.innerHTML") or "")
    except Exception:
        m = None
    return m.group(1) if m else None


def _admin_on(page):
    page.evaluate(
        """() => { const cb = Array.from(document.querySelectorAll("input[type=checkbox]"))
            .find(c => /admin|breakdown/i.test((c.name||'')+(c.id||'')+(c.parentElement?.innerText||'')));
            if (cb && !cb.checked) cb.click(); }""")


def _load_as_week(page, sunday):
    rqst = _rqst(page)
    if not rqst:
        return
    # AppStream's index.cfm responds slowly/intermittently, so a single
    # goto times out at random. Retry a few times with a lenient wait
    # ("commit" fires as soon as the response is received, decoupled from
    # the dead/slow 3rd-party resources — ga.js, socket.io, cdnjs). The
    # #weekStart wait below is the real readiness gate either way.
    url = f"https://applicantstream.com/index.cfm?rqst={rqst}&p=701"
    last_err = None
    for attempt in range(3):
        try:
            page.goto(url, wait_until="commit", timeout=40000)
            page.wait_for_selector("#weekStart", timeout=20000)
            last_err = None
            break
        except PWTimeout as e:
            last_err = e
            print(f"  [retry] week {sunday}: goto/#weekStart timeout "
                  f"(attempt {attempt + 1}/3)", flush=True)
            page.wait_for_timeout(2000)
    if last_err is not None:
        raise last_err
    _admin_on(page)
    try:
        fo._set_week_and_submit(page, sunday)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    if not page.evaluate("() => !!document.querySelector('tr.adminRow')"):
        _admin_on(page)
        try:
            with page.expect_navigation(timeout=12000, wait_until="load"):
                page.evaluate(
                    """() => { const b=[...document.querySelectorAll('input[type=submit],button,a')]
                        .find(e=>/get report/i.test(e.innerText||e.value||'')); if(b)b.click(); }""")
        except Exception:
            pass
        page.wait_for_timeout(1500)


def _parse(page):
    rows = page.evaluate(
        """() => { const t = [...document.querySelectorAll('table')]
            .sort((a,b)=>b.querySelectorAll('tr').length-a.querySelectorAll('tr').length)[0];
            if (!t) return [];
            return [...t.querySelectorAll('tr')].map(tr => ({cls: tr.className||'',
                texts: [...tr.querySelectorAll('th,td')].map(c=>(c.innerText||'').replace(/\\s+/g,' ').trim())})); }""")
    recs, cur = {}, None
    for r in rows:
        texts = r["texts"]
        if not texts:
            continue
        if "adminRow" in r["cls"]:
            if cur and texts[0]:
                vals = [_to_int(texts[i]) if i < len(texts) else 0 for i in range(1, 8)]
                recs.setdefault(texts[0], {}).setdefault(cur, [0]*7)
                recs[texts[0]][cur] = vals
        else:
            cur = SECTIONS.get(_norm(texts[0]))
    return recs


def pull_as_weeks(as_sundays, verbose=True):
    """Pull each AppStream Sun-Sat week. Returns {as_sunday: {rec: {Sch:[7],SU:[7]}}}."""
    out = {}
    with appstream_direct_session(verbose=verbose) as page:
        page.wait_for_timeout(3000)
        page.wait_for_selector("#searchMC", timeout=20000)
        if f"Office ID: {OFFICE_ID}" not in (page.evaluate("() => document.body.innerText || ''")):
            fo._switch_office(page, OFFICE_ID, OWNER)
            page.wait_for_timeout(1500)
        for sun in sorted(as_sundays):
            _load_as_week(page, sun)
            out[sun] = _parse(page)
            if verbose:
                sch = sum(sum(m.get("Sch", [0]*7)) for m in out[sun].values())
                print(f"  AS week {sun}: {len(out[sun])} recruiters, {sch} scheduled", flush=True)
    return out


# --------------------------------------------------------------------------- sheet
def _a1(c):
    s = ""
    while c > 0:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def _parse_we(s):
    for f in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime((s or "").strip(), f).date()
        except ValueError:
            pass
    return None


def _locate(values):
    """Find the header rows by content (never hard-coded) so inserting/removing
    rows at the top can't misalign the fill. Returns (we_row, sub_row, first_rec),
    all 1-indexed. we_row = the row with the WE-date headers; sub_row = the
    'NAME / Sch / SU / %' row; first_rec = the first recruiter row."""
    we_row = sub_row = None
    for i, row in enumerate(values):
        if we_row is None and sum(1 for c in row if _parse_we(c)) >= 2:
            we_row = i + 1
        if sub_row is None and row and row[0].strip().lower() == "name":
            sub_row = i + 1
    we_row = we_row or 2
    sub_row = sub_row or (we_row + 2)
    return we_row, sub_row, sub_row + 1


def _pct(su, sch):
    return f"{round(100*su/sch)}%" if sch else "0%"


def _report_week_index(D):
    return (D - REPORT_FIRST).days // 7


def _report_totals(as_data, report_weeks):
    """1-week-behind: report column ending Sunday D <- AppStream week starting
    D-7, summed Sun-Sat. Returns {D: {rec: {Sch,SU}}}."""
    out = {}
    for D in report_weeks:
        src = as_data.get(D - dt.timedelta(days=7), {})
        out[D] = {n: {"Sch": sum(m.get("Sch", [0]*7)), "SU": sum(m.get("SU", [0]*7))}
                  for n, m in src.items()}
    return out


def read_sheet_data(ws, blocks):
    """Read filled 3-col blocks back: {D: {rec: {Sch,SU}}}."""
    v = ws.get_all_values()
    out = {}
    for D, start in blocks.items():
        recs = {}
        for r in range(FIRST_REC - 1, len(v)):
            row = v[r]
            name = (row[0] if row else "").strip()
            if not name:
                continue
            def cell(i):
                idx = start - 1 + i
                return _to_int(row[idx]) if idx < len(row) else 0
            recs[name] = {"Sch": cell(0), "SU": cell(1)}
        out[D] = recs
    return out


def ensure_blocks(sh, ws, report_weeks, dry=False):
    v = ws.get_all_values()
    have = {}
    for i, c in enumerate(v[WE_ROW - 1] if len(v) >= WE_ROW else []):
        d = _parse_we(c)
        if d:
            have[d] = i + 1
    missing = [w for w in report_weeks if w not in have]
    if not missing or dry:
        if missing and dry:
            print(f"  (dry-run) would add {len(missing)} week column(s)")
        return have
    sid = ws.id
    src_even = next((have[d] for d in sorted(have) if _report_week_index(d) % 2 == 0), None)
    src_odd = next((have[d] for d in sorted(have) if _report_week_index(d) % 2 == 1), None)
    nxt = max(have.values()) + BLOCK_W if have else FIRST_BLOCK_COL
    reqs, dates = [], []
    for w in sorted(missing):
        src = (src_even if _report_week_index(w) % 2 == 0 else src_odd) or next(iter(have.values()))
        if ws.col_count < nxt + BLOCK_W - 1:
            ws.resize(rows=ws.row_count, cols=nxt + BLOCK_W - 1)
        reqs.append({"copyPaste": {
            "source": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 66,
                       "startColumnIndex": src - 1, "endColumnIndex": src - 1 + BLOCK_W},
            "destination": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 66,
                            "startColumnIndex": nxt - 1, "endColumnIndex": nxt - 1 + BLOCK_W},
            "pasteType": "PASTE_NORMAL"}})
        dates.append({"range": f"{TAB}!{_a1(nxt)}{WE_ROW}", "values": [[f"{w.month}/{w.day}/{w.year}"]]})
        have[w] = nxt
        nxt += BLOCK_W
    sh.batch_update({"requests": reqs})
    sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": dates})
    return have


def fill(sh, ws, report, blocks, dry=False):
    weeks_sorted = sorted(report)
    sort_wk = weeks_sorted[-1]
    recent = weeks_sorted[-HIDE_WINDOW:]
    names = {n for wk in report.values() for n in wk}

    def sched_recent(n):
        return sum(report[wk].get(n, {}).get("Sch", 0) for wk in recent)

    def sortkey(n):
        m = report[sort_wk].get(n, {})
        sch, su = m.get("Sch", 0), m.get("SU", 0)
        return (-(su/sch if sch else 0.0), -su, n.lower())

    active = sorted([n for n in names if sched_recent(n) > 0], key=sortkey)
    inactive = sorted([n for n in names if sched_recent(n) == 0], key=sortkey)
    roster = active + inactive
    last_row = FIRST_REC + len(roster) - 1
    print(f"  {len(roster)} recruiters: {len(active)} active / {len(inactive)} inactive(hidden)", flush=True)

    if dry:
        for n in roster[:8]:
            m = report[sort_wk].get(n, {})
            print(f"    {n[:24].ljust(24)} Sch={m.get('Sch',0)} SU={m.get('SU',0)} {_pct(m.get('SU',0),m.get('Sch',0))}")
        return

    ws.batch_clear([f"A{FIRST_REC}:A{max(last_row, FIRST_REC+60)}"])
    ws.update(range_name=f"A{FIRST_REC}:A{last_row}",
              values=[[n] for n in roster], value_input_option="USER_ENTERED")

    batch = []
    for D, start in sorted(blocks.items()):
        if D not in report:
            continue
        grid = [[report[D].get(n, {}).get("Sch", 0), report[D].get(n, {}).get("SU", 0),
                 _pct(report[D].get(n, {}).get("SU", 0), report[D].get(n, {}).get("Sch", 0))]
                for n in roster]
        batch.append({"range": f"{TAB}!{_a1(start)}{FIRST_REC}:{_a1(start+BLOCK_W-1)}{last_row}",
                      "values": grid})
    sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": batch})

    sid = ws.id
    last_col = max(blocks.values()) + BLOCK_W - 1
    reqs = []
    for start in blocks.values():
        reqs.append(_numfmt(sid, FIRST_REC-1, last_row, start-1, start+1, {"type": "NUMBER", "pattern": "0"}))
        reqs.append(_numfmt(sid, FIRST_REC-1, last_row, start+1, start+2, {"type": "PERCENT", "pattern": "0%"}))
    reqs += _band_filter(sid, sh, last_row, last_col)
    reqs += _cf_rules(sid, sh, [s + 2 for s in blocks.values()])
    sh.batch_update({"requests": reqs})

    # Highlights (re-applied every run since rows re-sort): clear all data-cell
    # backgrounds so the banding shows through, then (a) full-row tint the
    # non-human channels, (b) yellow the NAME of anyone who SCHEDULED an
    # interview in the latest week (active on the market that week).
    sched_now = {n for n in roster if report[sort_wk].get(n, {}).get("Sch", 0) > 0}
    hl = [{"repeatCell": {"range": {"sheetId": sid, "startRowIndex": FIRST_REC-1,
            "endRowIndex": last_row, "startColumnIndex": 0, "endColumnIndex": last_col},
            "cell": {"userEnteredFormat": {}}, "fields": "userEnteredFormat.backgroundColor"}}]
    for i, n in enumerate(roster):
        r0 = FIRST_REC - 1 + i
        if _norm(n) in CHANNELS:        # full-row lavender for AI Messaging / Self Scheduled
            hl.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r0+1,
                "startColumnIndex": 0, "endColumnIndex": last_col},
                "cell": {"userEnteredFormat": {"backgroundColor": CHANNEL_BG}},
                "fields": "userEnteredFormat.backgroundColor"}})
        elif n in sched_now:            # yellow name for current-week schedulers
            hl.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r0+1,
                "startColumnIndex": 0, "endColumnIndex": 1},
                "cell": {"userEnteredFormat": {"backgroundColor": NAME_YELLOW}},
                "fields": "userEnteredFormat.backgroundColor"}})
    sh.batch_update({"requests": hl})

    hreqs = [{"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": FIRST_REC-1+i, "endIndex": FIRST_REC+i},
        "properties": {"hiddenByUser": i >= len(active)}, "fields": "hiddenByUser"}}
        for i in range(len(roster))]
    sh.batch_update({"requests": hreqs})
    print(f"  shown rows {FIRST_REC}-{FIRST_REC+len(active)-1}; hidden {FIRST_REC+len(active)}-{last_row}", flush=True)


def _numfmt(sid, r0, r1, c0, c1, numfmt):
    return {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1+1,
            "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": {"numberFormat": numfmt}}, "fields": "userEnteredFormat.numberFormat"}}


def _band_filter(sid, sh, last_row, last_col):
    reqs = []
    meta = sh.fetch_sheet_metadata()
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sid:
            for b in s.get("bandedRanges", []):
                # Preserve the band's existing start (keeps Megan's parity +
                # any header styling); only EXTEND its end to cover all
                # recruiter rows + week columns.
                r = b.get("range", {})
                reqs.append({"updateBanding": {"bandedRange": {"bandedRangeId": b["bandedRangeId"],
                    "range": {"sheetId": sid,
                              "startRowIndex": r.get("startRowIndex", FIRST_REC - 1),
                              "endRowIndex": max(r.get("endRowIndex", 0), last_row),
                              "startColumnIndex": r.get("startColumnIndex", 0),
                              "endColumnIndex": max(r.get("endColumnIndex", 0), last_col)}},
                    "fields": "range"}})
                break
    reqs.append({"setBasicFilter": {"filter": {"range": {"sheetId": sid,
        "startRowIndex": SUB_ROW-1, "endRowIndex": last_row, "startColumnIndex": 1, "endColumnIndex": last_col}}}})
    return reqs


def _cf_rules(sid, sh, pct_cols):
    meta = sh.fetch_sheet_metadata()
    count = 0
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sid:
            count = len(s.get("conditionalFormats", []))
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}} for i in range(count - 1, -1, -1)]
    ranges = [{"sheetId": sid, "startRowIndex": FIRST_REC - 1, "endRowIndex": 200,
               "startColumnIndex": c - 1, "endColumnIndex": c} for c in pct_cols]

    def rule(idx, cond, val, color):
        return {"addConditionalFormatRule": {"index": idx, "rule": {"ranges": ranges,
            "booleanRule": {"condition": {"type": cond, "values": [{"userEnteredValue": str(val)}]},
                "format": {"backgroundColor": color}}}}}
    reqs += [rule(0, "NUMBER_GREATER_THAN_EQ", 0.5, CF_GREEN),
             rule(1, "NUMBER_GREATER_THAN_EQ", 0.45, CF_GREY),
             rule(2, "NUMBER_LESS", 0.45, CF_RED)]
    return reqs


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(prog="recruiter_retention")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--date", default=None, help="override today (YYYY-MM-DD)")
    ap.add_argument("--backfill", action="store_true",
                    help="re-pull every report week (REPORT_FIRST -> now); default = latest week only")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    cur_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)   # latest completed week-ending Sunday

    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB)
    v0 = ws.get_all_values()
    # Detect header rows by content (robust to rows inserted/removed at the top).
    global WE_ROW, SUB_ROW, FIRST_REC
    WE_ROW, SUB_ROW, FIRST_REC = _locate(v0)
    print(f"  layout: WE row {WE_ROW}, header row {SUB_ROW}, recruiters from row {FIRST_REC}", flush=True)
    blocks0 = {d: i + 1 for i, c in enumerate(v0[WE_ROW - 1] if len(v0) >= WE_ROW else [])
               if (d := _parse_we(c))}
    sheet0 = read_sheet_data(ws, blocks0)

    # Candidate report weeks = every week-ending Sunday from REPORT_FIRST..cur_sun.
    candidates, w = [], REPORT_FIRST
    while w <= cur_sun:
        candidates.append(w)
        w += dt.timedelta(days=7)

    if args.backfill:
        report_weeks = candidates                      # re-pull everything
    else:
        # SELF-HEALING: target any candidate week whose column is missing or
        # empty (catches up skipped weeks) + always refresh the current week.
        filled = {D for D in candidates if D in sheet0
                  and any((r.get("Sch") or r.get("SU")) for r in sheet0[D].values())}
        report_weeks = sorted((set(candidates) - filled) | {cur_sun})
    report_weeks = [d for d in report_weeks if d >= REPORT_FIRST] or [cur_sun]

    # 1-week-behind: each report column D needs AppStream week starting D-7.
    as_weeks = sorted({D - dt.timedelta(days=7) for D in report_weeks})
    print(f"=== 1st rd Recruiter % — {'BACKFILL ' if args.backfill else ''}"
          f"filling {len(report_weeks)} week(s): {[d.isoformat() for d in report_weeks]} "
          f"(AS weeks {as_weeks[0]}..{as_weeks[-1]}) {'DRY-RUN' if args.dry_run else 'LIVE'} ===", flush=True)
    print("Phase 1: pull AppStream (Raf office, admin breakdown)…", flush=True)
    as_data = pull_as_weeks(as_weeks)
    if not any(as_data.values()):
        print("⚠ No data pulled — aborting.", flush=True)
        return 1

    print("Phase 2: fill the tab (week-ending Sundays)…", flush=True)
    blocks = ensure_blocks(sh, ws, report_weeks, dry=args.dry_run)
    pulled = _report_totals(as_data, report_weeks)

    if args.dry_run:
        fill(sh, ws, pulled, blocks, dry=True)
        print("=== done (dry-run) ===", flush=True)
        return 0

    report = read_sheet_data(ws, blocks)    # history from the sheet (post-ensure)
    for D, recs in pulled.items():
        report[D] = recs                    # fresh data wins for the pulled column(s)
    fill(sh, ws, report, blocks, dry=False)

    # Cross-reference the recruiters on the tab against the 'Terminated ICDs'
    # tab + ALERT the runner about anyone terminated still listed (advisory —
    # prints to the run output + log, never removes a row). Names come from the
    # same set fill() builds: every recruiter across all report weeks.
    try:
        from automations.shared import terminated_icds as _ti
        _names = sorted({n for wk in report.values() for n in wk})
        _ti.alert_terminated(
            _names, report_label="the Ongoing 1st Round Recruiter Retention tab")
    except Exception:  # noqa: BLE001 — advisory must never fail the run
        pass

    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
