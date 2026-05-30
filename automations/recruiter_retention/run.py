"""Ongoing 1st Round Recruiter Retention — weekly Hub report (Eve, Mondays).

Pulls AppStream's Retention Report (p=701, admin breakdown) for Raf's office
(11280) and fills the 'Ongoing 1st Round Recruiter Retention' tab: one 4-col
block per week = the WEEK TOTAL (Booked / Scheduled / Showed / %), WE = the
Sunday. % = Showed ÷ Scheduled. Counts incl. 0. Active recruiters (booked in
the last 2 weeks) sort to the top by latest-week retention desc; inactive go to
the bottom as one contiguous HIDDEN group (keeps the banding clean).
Alternating dark/blue week headers; banding + the row-4 filter are extended to
cover new weeks/recruiters. Each run pulls WE 4/05 → current week and re-fills.

(The Mon-Fri daily breakdown is a SEPARATE report on the 'Daily 1st Round
Recruiter Retention' tab — same pull, different fill.)

  python -m automations.recruiter_retention.run            # live, current week
  python -m automations.recruiter_retention.run --dry-run  # pull + preview only
  python -m automations.recruiter_retention.run --date 2026-05-24
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

# Make emoji / checkmarks safe on the Windows console (cp1252 default) —
# same guard every other report uses so the Hub can run this on Eve's machine.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fetch_office as fo
from automations.recruiting_report.fill import open_by_key

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "1st rd Recruiter %"        # sheet tab (Hub card is named "Ongoing 1st Round Recruiter Retention")
OFFICE_ID, OWNER = "11280", "Rafael Hidalgo"
FIRST_WEEK = dt.date(2026, 4, 5)        # WE 4/05 — report start (Sundays)

SECTIONS = {"interviews booked": "B",            # NOT "second interviews booked"
            "total first interviews": "Sch",
            "first interviews showed up": "SU"}

BLOCK_W = 4                              # per week: B / Sch / SU / %
WE_ROW, DAY_ROW, SUB_ROW, FIRST_REC = 2, 3, 4, 5
FIRST_BLOCK_COL = 2                      # col B (1-indexed)
HIDE_WINDOW = 2                          # hide if 0 booked in last N weeks

# Retention % color-coding (Raf): <45% red, 45–49.9% grey, >=50% green.
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


def _load_week(page, sunday):
    rqst = _rqst(page)
    if not rqst:
        return
    page.goto(f"https://applicantstream.com/index.cfm?rqst={rqst}&p=701",
              wait_until="load", timeout=25000)
    page.wait_for_selector("#weekStart", timeout=15000)
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


def pull_weeks(weeks, verbose=True):
    out = {}
    with appstream_direct_session(verbose=verbose) as page:
        page.wait_for_timeout(3000)
        page.wait_for_selector("#searchMC", timeout=20000)
        if f"Office ID: {OFFICE_ID}" not in (page.evaluate("() => document.body.innerText || ''")):
            fo._switch_office(page, OFFICE_ID, OWNER)
            page.wait_for_timeout(1500)
        for sun in weeks:
            _load_week(page, sun)
            out[sun] = _parse(page)
            if verbose:
                b = sum(sum(m.get("B", [0]*7)) for m in out[sun].values())
                print(f"  WE {sun}: {len(out[sun])} recruiters, {b} booked", flush=True)
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


def _pct(su, sch):
    return f"{round(100*su/sch)}%" if sch else "0%"


def _week_index(sun):
    return (sun - FIRST_WEEK).days // 7


def ensure_blocks(sh, ws, weeks, dry=False):
    """Make sure every week has a 4-col block; add missing ones by copyPaste
    from an existing SAME-PARITY (same-color) block, then set the WE date."""
    v = ws.get_all_values()
    have = {}
    for i, c in enumerate(v[WE_ROW - 1] if len(v) >= WE_ROW else []):
        d = _parse_we(c)
        if d:
            have[d] = i + 1
    missing = [w for w in weeks if w not in have]
    if not missing or dry:
        if missing and dry:
            print(f"  (dry-run) would add {len(missing)} week block(s)")
        return have
    sid = ws.id
    src_dark = next((have[d] for d in sorted(have) if _week_index(d) % 2 == 0), None)
    src_blue = next((have[d] for d in sorted(have) if _week_index(d) % 2 == 1), None)
    rightmost = max(have.values()) + BLOCK_W - 1 if have else FIRST_BLOCK_COL - 1
    reqs, dates, nxt = [], [], rightmost + 1
    for w in sorted(missing):
        src = (src_dark if _week_index(w) % 2 == 0 else src_blue) or next(iter(have.values()))
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


def _totals(per_day_recs):
    """{rec: {B:[7],Sch:[7],SU:[7]}} (per-day) -> {rec: {B,Sch,SU}} (week totals)."""
    return {n: {k: sum(v.get(k, [0]*7)) for k in ("B", "Sch", "SU")}
            for n, v in per_day_recs.items()}


def read_sheet_data(ws, blocks):
    """Read the already-filled week-total blocks back from the sheet so the
    weekly run can re-sort/re-hide without re-pulling old weeks. Returns
    {week: {recruiter: {B,Sch,SU}}}."""
    v = ws.get_all_values()
    out = {}
    for wk, start in blocks.items():
        recs = {}
        for r in range(FIRST_REC - 1, len(v)):
            row = v[r]
            name = (row[0] if row else "").strip()
            if not name:
                continue
            def cell(i):
                idx = start - 1 + i
                return _to_int(row[idx]) if idx < len(row) else 0
            recs[name] = {"B": cell(0), "Sch": cell(1), "SU": cell(2)}
        out[wk] = recs
    return out


def fill(sh, ws, data, blocks, dry=False):
    # `data` is week-TOTAL shaped: {week: {recruiter: {B,Sch,SU}}}.
    weeks_sorted = sorted(data)
    sort_wk = weeks_sorted[-1]
    recent = weeks_sorted[-HIDE_WINDOW:]
    names = {n for wk in data.values() for n in wk}

    def booked_recent(n):
        return sum(data[wk].get(n, {}).get("B", 0) for wk in recent)

    def sortkey(n):
        m = data[sort_wk].get(n, {})
        sch, su, b = m.get("Sch", 0), m.get("SU", 0), m.get("B", 0)
        return (-(su/sch if sch else 0.0), -b, n.lower())

    active = sorted([n for n in names if booked_recent(n) > 0], key=sortkey)
    inactive = sorted([n for n in names if booked_recent(n) == 0], key=sortkey)
    roster = active + inactive
    last_row = FIRST_REC + len(roster) - 1
    print(f"  {len(roster)} recruiters: {len(active)} active / {len(inactive)} inactive(hidden)", flush=True)

    if dry:
        for n in roster[:8]:
            m = data[sort_wk].get(n, {})
            b, s, u = m.get("B", 0), m.get("Sch", 0), m.get("SU", 0)
            print(f"    {n[:24].ljust(24)} {b}/{s}/{u}/{_pct(u, s)}")
        return

    ws.batch_clear([f"A{FIRST_REC}:A{max(last_row, FIRST_REC+60)}"])
    ws.update(range_name=f"A{FIRST_REC}:A{last_row}",
              values=[[n] for n in roster], value_input_option="USER_ENTERED")

    batch = []
    for w, start in sorted(blocks.items()):
        if w not in data:
            continue
        grid = []
        for n in roster:
            m = data[w].get(n, {})
            b, s, u = m.get("B", 0), m.get("Sch", 0), m.get("SU", 0)
            grid.append([b, s, u, _pct(u, s)])
        batch.append({"range": f"{TAB}!{_a1(start)}{FIRST_REC}:{_a1(start+BLOCK_W-1)}{last_row}",
                      "values": grid})
    sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": batch})

    sid = ws.id
    last_col = max(blocks.values()) + BLOCK_W - 1
    reqs = []
    for start in blocks.values():
        reqs.append(_numfmt(sid, FIRST_REC-1, last_row, start-1, start+2, {"type": "NUMBER", "pattern": "0"}))
        reqs.append(_numfmt(sid, FIRST_REC-1, last_row, start+2, start+3, {"type": "PERCENT", "pattern": "0%"}))
    reqs += _band_filter(sid, sh, last_row, last_col)
    reqs += _cf_rules(sid, sh, [s + 3 for s in blocks.values()])
    sh.batch_update({"requests": reqs})

    hreqs = [{"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": FIRST_REC-1+i, "endIndex": FIRST_REC+i},
        "properties": {"hiddenByUser": i >= len(active)}, "fields": "hiddenByUser"}}
        for i in range(len(roster))]
    sh.batch_update({"requests": hreqs})
    print(f"  shown rows {FIRST_REC}-{FIRST_REC+len(active)-1}; "
          f"hidden {FIRST_REC+len(active)}-{last_row}", flush=True)


def _numfmt(sid, r0, r1, c0, c1, numfmt):
    return {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1+1,
            "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": {"numberFormat": numfmt}},
            "fields": "userEnteredFormat.numberFormat"}}


def _band_filter(sid, sh, last_row, last_col):
    reqs = []
    meta = sh.fetch_sheet_metadata()
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sid:
            for b in s.get("bandedRanges", []):
                reqs.append({"updateBanding": {"bandedRange": {"bandedRangeId": b["bandedRangeId"],
                    "range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": last_row,
                              "startColumnIndex": 0, "endColumnIndex": last_col}}, "fields": "range"}})
                break
    reqs.append({"setBasicFilter": {"filter": {"range": {"sheetId": sid,
        "startRowIndex": SUB_ROW-1, "endRowIndex": last_row,
        "startColumnIndex": 1, "endColumnIndex": last_col}}}})
    return reqs


def _cf_rules(sid, sh, pct_cols):
    """Color the retention % cells (Raf): <45% red, 45-49.9% grey, >=50% green.
    Clears this tab's existing CF rules first (idempotent across runs; this tab
    is dedicated to the report), then adds the 3 ordered rules over every %
    column so it auto-extends as new weeks are added."""
    meta = sh.fetch_sheet_metadata()
    count = 0
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sid:
            count = len(s.get("conditionalFormats", []))
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sid, "index": i}}
            for i in range(count - 1, -1, -1)]
    ranges = [{"sheetId": sid, "startRowIndex": FIRST_REC - 1, "endRowIndex": 200,
               "startColumnIndex": c - 1, "endColumnIndex": c} for c in pct_cols]

    def rule(idx, cond, val, color):
        return {"addConditionalFormatRule": {"index": idx, "rule": {"ranges": ranges,
            "booleanRule": {"condition": {"type": cond,
                "values": [{"userEnteredValue": str(val)}]},
                "format": {"backgroundColor": color}}}}}
    # Order matters (first match wins): green >=0.5, then grey >=0.45, then red.
    reqs += [rule(0, "NUMBER_GREATER_THAN_EQ", 0.5, CF_GREEN),
             rule(1, "NUMBER_GREATER_THAN_EQ", 0.45, CF_GREY),
             rule(2, "NUMBER_LESS", 0.45, CF_RED)]
    return reqs


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(prog="recruiter_retention")
    ap.add_argument("--dry-run", action="store_true", help="pull + preview, no Sheet writes")
    ap.add_argument("--date", default=None, help="override today (YYYY-MM-DD)")
    ap.add_argument("--backfill", action="store_true",
                    help="pull EVERY week 4/05->current (one-time seed; default only "
                         "pulls the last completed week and reuses sheet history)")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    cur_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)   # current week's Sunday
    if args.backfill:
        weeks, w = [], FIRST_WEEK
        while w <= cur_sun:
            weeks.append(w)
            w += dt.timedelta(days=7)
    else:
        # weekly run: the last FULLY-completed week (the week before the current
        # one). On the Monday 8am schedule this lands on the just-finished week
        # — e.g. Mon 6/1 -> 5/24. (Megan, after weighing vs current-week.)
        weeks = [cur_sun - dt.timedelta(days=7)]

    print(f"=== Ongoing 1st Round Recruiter Retention — "
          f"{'BACKFILL ' if args.backfill else ''}pulling {len(weeks)} week(s) "
          f"({weeks[0]}..{weeks[-1]}) {'DRY-RUN' if args.dry_run else 'LIVE'} ===", flush=True)
    print("Phase 1: pull AppStream (Raf office, admin breakdown)…", flush=True)
    pulled = pull_weeks(weeks)
    if not any(pulled.values()):
        print("⚠ No data pulled — aborting.", flush=True)
        return 1

    print("Phase 2: fill the Ongoing tab (week totals)…", flush=True)
    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB)
    blocks = ensure_blocks(sh, ws, weeks, dry=args.dry_run)

    if args.dry_run:
        data = {wk: _totals(recs) for wk, recs in pulled.items()}
        fill(sh, ws, data, blocks, dry=True)
        print("=== done (dry-run) ===", flush=True)
        return 0

    # Merge: sheet history (all existing week blocks) + the freshly-pulled week(s).
    data = read_sheet_data(ws, blocks)
    for wk, recs in pulled.items():
        data[wk] = _totals(recs)        # fresh data wins for the pulled week(s)
    fill(sh, ws, data, blocks, dry=False)
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
