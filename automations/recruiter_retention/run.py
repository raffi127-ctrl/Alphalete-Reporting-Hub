"""Ongoing 1st Round Recruiter Retention — weekly Hub report (Eve, Mondays).

Pulls AppStream's Retention Report (p=701, admin breakdown) for Raf's office
(11280), per recruiter / per day, and fills the 'Ongoing 1st Round Recruiter
Retention' tab: one 24-col block per week (Mon-Fri B/Sch/SU/% + Week Total),
WE = the Sunday. % = Showed ÷ Scheduled. Counts incl. 0. Active recruiters
(booked in the last 2 weeks) sort to the top by latest-week retention desc;
inactive go to the bottom as one contiguous HIDDEN group (keeps the banding
clean). Alternating dark/blue week headers; banding + borders + the row-4
filter are extended to cover new weeks/recruiters.

Each run pulls WE 4/05 → the current week and re-fills (idempotent).

  python -m automations.recruiter_retention.run            # live, current week
  python -m automations.recruiter_retention.run --dry-run  # pull + preview only
  python -m automations.recruiter_retention.run --date 2026-05-24  # override today
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

from automations.shared.tableau_patchright import appstream_direct_session
from automations.recruiting_report import fetch_office as fo
from automations.recruiting_report.fill import open_by_key

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "Ongoing 1st Round Recruiter Retention"
OFFICE_ID, OWNER = "11280", "Rafael Hidalgo"
FIRST_WEEK = dt.date(2026, 4, 5)        # WE 4/05 — report start (Sundays)

# AppStream mainRow label (normalized) -> sheet metric key
SECTIONS = {"interviews booked": "B",            # NOT "second interviews booked"
            "total first interviews": "Sch",
            "first interviews showed up": "SU"}

# Sheet block geometry
BLOCK_W = 24
WE_ROW, DAY_ROW, SUB_ROW, FIRST_REC = 2, 3, 4, 5
FIRST_BLOCK_COL = 2                      # col B (1-indexed)
WEEKDAY_OFFS = [0, 4, 8, 12, 16]         # Mon..Fri within a block
WEEK_TOTAL_OFF = 20
DATA_DAYIDX = [1, 2, 3, 4, 5]            # Mon..Fri in the [Sun..Sat] arrays
HIDE_WINDOW = 2                          # hide if 0 booked in last N weeks

DARK = {"red": 0.1686, "green": 0.2431, "blue": 0.3098}
BLUE = {"red": 0.2902, "green": 0.5294, "blue": 0.9098}
WHITE = {"red": 1, "green": 1, "blue": 1}


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
        return False
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
    return True


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
    """Make sure every week has a 24-col block; add missing ones by copyPaste
    from an existing SAME-COLOR block (parity), set the WE date."""
    v = ws.get_all_values()
    have = {}
    for i, c in enumerate(v[WE_ROW - 1]):
        d = _parse_we(c)
        if d:
            have[d] = i + 1
    missing = [w for w in weeks if w not in have]
    if not missing:
        return have
    sid = ws.id
    rightmost = max(have.values()) + BLOCK_W - 1 if have else 1
    # pick a dark + a blue source block from existing
    src_dark = next((have[d] for d in sorted(have) if _week_index(d) % 2 == 0), None)
    src_blue = next((have[d] for d in sorted(have) if _week_index(d) % 2 == 1), None)
    reqs, dates, nxt = [], [], rightmost + 1
    for w in sorted(missing):
        even = _week_index(w) % 2 == 0
        src = (src_dark if even else src_blue) or next(iter(have.values()))
        d0 = nxt - 1
        if ws.col_count < nxt + BLOCK_W - 1:
            ws.resize(rows=ws.row_count, cols=nxt + BLOCK_W - 1)
        reqs.append({"copyPaste": {
            "source": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 66,
                       "startColumnIndex": src - 1, "endColumnIndex": src - 1 + BLOCK_W},
            "destination": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 66,
                            "startColumnIndex": d0, "endColumnIndex": d0 + BLOCK_W},
            "pasteType": "PASTE_NORMAL"}})
        dates.append({"range": f"{TAB}!{_a1(nxt)}{WE_ROW}",
                      "values": [[f"{w.month}/{w.day}/{w.year}"]]})
        have[w] = nxt
        nxt += BLOCK_W
    if dry:
        print(f"  (dry-run) would add {len(missing)} week block(s)")
        return have
    sh.batch_update({"requests": reqs})
    sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": dates})
    return have


def fill(sh, ws, data, blocks, dry=False):
    weeks_sorted = sorted(data)
    sort_wk = weeks_sorted[-1]
    recent = weeks_sorted[-HIDE_WINDOW:]
    names = {n for wk in data.values() for n in wk}

    def booked_recent(n):
        return sum(sum(data[wk].get(n, {}).get("B", [0]*7)) for wk in recent)

    def sortkey(n):
        m = data[sort_wk].get(n, {})
        sch, su, b = sum(m.get("Sch", [0]*7)), sum(m.get("SU", [0]*7)), sum(m.get("B", [0]*7))
        return (-(su/sch if sch else 0.0), -b, n.lower())

    active = sorted([n for n in names if booked_recent(n) > 0], key=sortkey)
    inactive = sorted([n for n in names if booked_recent(n) == 0], key=sortkey)
    roster = active + inactive
    last_row = FIRST_REC + len(roster) - 1
    print(f"  {len(roster)} recruiters: {len(active)} active / {len(inactive)} inactive(hidden)", flush=True)

    if dry:
        for n in roster[:8]:
            m = data[sort_wk].get(n, {})
            B, S, U = m.get("B", [0]*7), m.get("Sch", [0]*7), m.get("SU", [0]*7)
            print("   ", n[:22].ljust(22),
                  "  ".join(f"{B[i]}/{S[i]}/{U[i]}/{_pct(U[i],S[i])}" for i in DATA_DAYIDX))
        return

    # roster -> col A
    ws.batch_clear([f"A{FIRST_REC}:A{max(last_row, FIRST_REC+60)}"])
    ws.update(range_name=f"A{FIRST_REC}:A{last_row}",
              values=[[n] for n in roster], value_input_option="USER_ENTERED")

    # values per week block
    batch = []
    for w, start in sorted(blocks.items()):
        if w not in data:
            continue
        grid = []
        for n in roster:
            m = data[w].get(n, {})
            B, S, U = m.get("B", [0]*7), m.get("Sch", [0]*7), m.get("SU", [0]*7)
            row = [""] * BLOCK_W
            for di, off in zip(DATA_DAYIDX, WEEKDAY_OFFS):
                row[off:off+4] = [B[di], S[di], U[di], _pct(U[di], S[di])]
            row[20:24] = [sum(B), sum(S), sum(U), _pct(sum(U), sum(S))]
            grid.append(row)
        batch.append({"range": f"{TAB}!{_a1(start)}{FIRST_REC}:{_a1(start+BLOCK_W-1)}{last_row}",
                      "values": grid})
    sh.values_batch_update({"valueInputOption": "USER_ENTERED", "data": batch})

    sid = ws.id
    last_col = max(blocks.values()) + BLOCK_W - 1
    reqs = []
    # number formats per block: counts integer, % as 0%
    for start in blocks.values():
        for g in range(6):
            base = start - 1 + g*4
            reqs.append(_fmt(sid, FIRST_REC-1, last_row, base, base+3, {"type": "NUMBER", "pattern": "0"}))
            reqs.append(_fmt(sid, FIRST_REC-1, last_row, base+3, base+4, {"type": "PERCENT", "pattern": "0%"}))
    # extend banding + filter to cover all rows/cols
    reqs += _band_filter(sid, sh, ws, last_row, last_col)
    sh.batch_update({"requests": reqs})

    # hide the inactive (bottom) block as one contiguous group
    hreqs = []
    for i in range(len(roster)):
        hreqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "ROWS",
                      "startIndex": FIRST_REC-1+i, "endIndex": FIRST_REC+i},
            "properties": {"hiddenByUser": i >= len(active)}, "fields": "hiddenByUser"}})
    sh.batch_update({"requests": hreqs})
    print(f"  shown rows {FIRST_REC}-{FIRST_REC+len(active)-1}; "
          f"hidden {FIRST_REC+len(active)}-{last_row}", flush=True)


def _fmt(sid, r0, r1, c0, c1, numfmt):
    return {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1+1,
            "startColumnIndex": c0, "endColumnIndex": c1},
            "cell": {"userEnteredFormat": {"numberFormat": numfmt}},
            "fields": "userEnteredFormat.numberFormat"}}


def _band_filter(sid, sh, ws, last_row, last_col):
    reqs = []
    # extend the existing banded range (if any) to rows 3..last_row, cols 0..last_col
    meta = sh.fetch_sheet_metadata()
    band_id = None
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == sid:
            for b in s.get("bandedRanges", []):
                band_id = b.get("bandedRangeId")
                break
    if band_id is not None:
        reqs.append({"updateBanding": {"bandedRange": {"bandedRangeId": band_id,
            "range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": last_row,
                      "startColumnIndex": 0, "endColumnIndex": last_col}},
            "fields": "range"}})
    # re-anchor the basic filter: header row 4, through last_row, cols B..last_col
    reqs.append({"setBasicFilter": {"filter": {"range": {"sheetId": sid,
        "startRowIndex": SUB_ROW-1, "endRowIndex": last_row,
        "startColumnIndex": 1, "endColumnIndex": last_col}}}})
    return reqs


# --------------------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(prog="recruiter_retention")
    ap.add_argument("--dry-run", action="store_true", help="pull + preview, no Sheet writes")
    ap.add_argument("--date", default=None, help="override today (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    cur_sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    weeks = []
    w = FIRST_WEEK
    while w <= cur_sun:
        weeks.append(w)
        w += dt.timedelta(days=7)

    print(f"=== Recruiter Retention — {len(weeks)} weeks ({weeks[0]}..{weeks[-1]}) "
          f"{'DRY-RUN' if args.dry_run else 'LIVE'} ===", flush=True)
    print("Phase 1: pull AppStream (Raf office, admin breakdown)…", flush=True)
    data = pull_weeks(weeks)
    if not any(data.values()):
        print("⚠ No data pulled — aborting.", flush=True)
        return 1

    print("Phase 2: fill the Ongoing tab…", flush=True)
    sh = open_by_key(SHEET_ID)
    ws = sh.worksheet(TAB)
    blocks = ensure_blocks(sh, ws, weeks, dry=args.dry_run)
    fill(sh, ws, data, blocks, dry=args.dry_run)
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
