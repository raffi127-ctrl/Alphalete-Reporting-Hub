"""Captainship Activations — weekly per-owner grid on the Vantura board.

Carlos 2026-09-07: "a separate report for everyone in my captainship and all
of the activations that they have … by week ending: how many activations there
are for that week ending, and then below, total sales made that week …
separate it by my captainship and then by Atef's captainship … a new tab on
the Vantura Master Sales Board."

One tab, "Captainship Activations", four grids (rows = owners, cols = the
last 8 completed Mon-Sun weeks labelled by their Sunday):

    CARLOS'S CAPTAINSHIP - ACTIVATIONS
    CARLOS'S CAPTAINSHIP - TOTAL SALES
    ATEF'S CAPTAINSHIP   - ACTIVATIONS
    ATEF'S CAPTAINSHIP   - TOTAL SALES

COUNTING RULES (each deliberately matches a number Carlos already reads):
  * Activation = an ORDERLOG line whose DTR Status (enriched) is not
    Canceled/Disconnected and whose spe.dtr Posted Date (copy) falls in the
    week - the att_order_log.payout rule (the morning "Activation report
    overview"), except weeks here are Mon-Sun per the board's 8/28 ruling
    (payout's own pay-weeks are Sun-Sat). Counted per line; no product filter,
    and no Rep requirement (owner totals must not lose rep-less lines - the
    run logs how many those were).
  * Total sales = tracker apps: Unit Count summed over NEW INTERNET /
    WIRELESS / AIR-AWB by sp.Order Date (copy) week - the same
    counted-products rule as captainship_boards / pull_b2b (Carlos 9/7).

MEMBERSHIP IS DATED (Carlos 2026-09-07, this session). The captainship was
realigned on Monday 2026-08-17 (Atef promoted to captain - Raf's email on the
first "Atef's Captainship Report 8/17"; rosters confirmed from the daily
captainship-report recipient lists July->today):
  * Under Carlos the whole window: Carlos, Jamis Garay, George Hipolito,
    Kinsey Guenther, Joey Ramirez, Justin Wood, Gary Whitaker II, and
    Nicolas Lujan (brand-new ICD, DD ~8/22 - all his history counts).
  * Joined Carlos at the 8/17 realignment: Jackie LeRoy, Jeff Starr,
    Vincent Smith, Joshua Murphy. Nothing before 8/17 counts for them here.
  * Left Carlos at 8/17 (count for Carlos THROUGH WE 8/16, then off):
    Atef, Sabrina Alicea, Joe Eckhart ("disregard him after he leaves me"),
    Ryan Kabbes, Kevin Driggs. Ethan McKendree (left ~8/4) is excluded
    entirely ("mckendree don't").
  * Atef's captainship FROM WE 8/23: Atef, Sabrina Alicea, Dhyey Patel
    (Dhyey was never under Carlos - his pre-8/23 weeks appear nowhere).
A mover's line is bucketed by the date being counted (posted date for
activations, order date for sales), so one deal can legitimately credit
Carlos's section pre-cutover and Atef's after.

DATA: ATTTRACKER-B2B ORDERLOG direct .csv endpoint (order-date windowed),
pulled in <=31-day chunks (the export is ~120MB per 31 days) through the
shared CDP Chrome session, national scope (owner_prefix=None). The window
starts 5 weeks before the first reported week so late-posting orders still
land; an order older than that which posts in-window is missed (rare - the
program's activation window is ~30 days). Statuses drift daily, so chunks are
cached per as-of date and never reused across days.

    PYTHONPATH=. .venv/bin/python -m automations.b2b_captainship_activations.run --dry-run
    PYTHONPATH=. .venv/bin/python -m automations.b2b_captainship_activations.run --sheet
    ... --from-file a.csv --from-file b.csv    # skip the pull, parse these
    lucy rerun b2b_captainship_activations     # (base_args carry --sheet)

Writes ONLY its own tab; PROTECTED guard refuses anything else.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master Sales Board
TAB = "Captainship Activations"

CSV_URL = ("https://us-east-1.online.tableau.com/t/sci/views/"
           "ATTTRACKER-B2B/ORDERLOG.csv?:refresh=yes"
           "&Start%20Date={}&End%20Date={}")

CUTOVER = dt.date(2026, 8, 17)          # Monday the captainship split
N_WEEKS = 8
LOOKBACK_WEEKS = 5                      # posted-date slack before week 1
CHUNK_DAYS = 31                         # matches the daily pull's proven size

COUNTED_PRODUCTS = {"NEW INTERNET", "WIRELESS", "AIR/AWB"}
CANCEL_STATUSES = ("canceled", "cancelled", "disconnected")
POSTED_COL = "spe.dtr Posted Date (copy)"
ORDER_COL = "sp.Order Date (copy)"

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_captainship_activations"

_PAST = dt.date(2020, 1, 1)
_FUTURE = dt.date(2030, 1, 1)
_DAY_BEFORE_CUT = CUTOVER - dt.timedelta(days=1)


class Member:
    """One owner in one section. `alts` is a tuple of alternative token sets -
    the owner cell matches when EVERY token of ANY alternative appears in the
    normalised name line (handles 'GARY WHITAKER II' and Eckhart/Eckert)."""

    def __init__(self, display, alts, since=None, until=None, note=""):
        self.display = display
        self.alts = alts
        self.since = since or _PAST
        self.until = until or _FUTURE
        self.note = note

    def active(self, d: dt.date) -> bool:
        return self.since <= d <= self.until

    def matches(self, owner_uc: str) -> bool:
        toks = set(owner_uc.split())
        return any(all(t in toks for t in alt) for alt in self.alts)


def _m(display, alts, since=None, until=None, note=""):
    return Member(display, alts, since, until, note)


CARLOS_TEAM = [
    _m("Carlos Hidalgo",   ((u"CARLOS", u"HIDALGO"),)),
    _m("Jamis Garay",      ((u"JAMIS", u"GARAY"),)),
    _m("George Hipolito",  ((u"GEORGE", u"HIPOLITO"),)),
    _m("Kinsey Guenther",  ((u"KINSEY", u"GUENTHER"),)),
    _m("Joey Ramirez",     ((u"JOEY", u"RAMIREZ"),)),
    _m("Justin Wood",      ((u"JUSTIN", u"WOOD"),)),
    _m("Gary Whitaker II", ((u"GARY", u"WHITAKER"),)),
    _m("Nicolas Lujan",    ((u"LUJAN",),)),
    _m("Jackie LeRoy",     ((u"JACKIE", u"LEROY"),), since=CUTOVER,
       note="joined 8/17"),
    _m("Jeff Starr",       ((u"JEFFREY", u"STARR"), (u"JEFF", u"STARR")),
       since=CUTOVER, note="joined 8/17"),
    _m("Vincent Smith",    ((u"VINCENT", u"SMITH"),), since=CUTOVER,
       note="joined 8/17"),
    _m("Joshua Murphy",    ((u"JOSHUA", u"MURPHY"),), since=CUTOVER,
       note="joined 8/17"),
    _m("Atef Choudhury",   ((u"ATEF",),), until=_DAY_BEFORE_CUT,
       note="thru 8/16"),
    _m("Sabrina Alicea",   ((u"SABRINA", u"ALICEA"),), until=_DAY_BEFORE_CUT,
       note="thru 8/16"),
    _m("Joe Eckhart",      ((u"ECKHART",), (u"ECKERT",)), until=_DAY_BEFORE_CUT,
       note="thru 8/16"),
    _m("Ryan Kabbes",      ((u"KABBES",),), until=_DAY_BEFORE_CUT,
       note="thru 8/16"),
    _m("Kevin Driggs",     ((u"DRIGGS",),), until=_DAY_BEFORE_CUT,
       note="thru 8/16"),
]

ATEF_TEAM = [
    _m("Atef Choudhury",  ((u"ATEF",),), since=CUTOVER),
    _m("Sabrina Alicea",  ((u"SABRINA", u"ALICEA"),), since=CUTOVER),
    _m("Dhyey Patel",     ((u"DHYEY",),), since=CUTOVER),
]

SECTIONS = [("CARLOS'S CAPTAINSHIP", CARLOS_TEAM),
            ("ATEF'S CAPTAINSHIP (from WE 8/23)", ATEF_TEAM)]


# ---------------------------------------------------------------- weeks/dates

def completed_weeks(today: dt.date) -> List[Tuple[dt.date, dt.date]]:
    """The last N_WEEKS completed Mon-Sun weeks as (monday, sunday)."""
    this_monday = today - dt.timedelta(days=today.weekday())
    return [(this_monday - dt.timedelta(days=7 * k),
             this_monday - dt.timedelta(days=7 * k - 6))
            for k in range(N_WEEKS, 0, -1)]


def _parse_date(v) -> Optional[dt.date]:
    s = str(v or "").strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def _norm_owner(raw) -> str:
    """Owner & Office cell -> the person-name line, uppercased, no [company]."""
    line = str(raw or "").replace("\r", "\n").split("\n")[0]
    line = re.sub(r"\[[^\]]*\]", " ", line)
    return " ".join(line.split()).upper()


# --------------------------------------------------------------------- pull

def _chunks(start: dt.date, end: dt.date) -> List[Tuple[dt.date, dt.date]]:
    out, s = [], start
    while s <= end:
        e = min(s + dt.timedelta(days=CHUNK_DAYS - 1), end)
        out.append((s, e))
        s = e + dt.timedelta(days=1)
    return out


def pull_chunks(today: dt.date, start: dt.date, log=print) -> List[Path]:
    """Fetch every chunk missing from today's cache, ONE Chrome session for
    all of them. Same CDP mechanics as att_order_log._pull."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.att_order_log.run import _fetch_csv
    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = []
    for s, e in _chunks(start, today):
        dest = OUT_DIR / "orderlog_{}_{}_asof_{}.csv".format(
            s.isoformat(), e.isoformat(), today.isoformat())
        jobs.append((s, e, dest))
    missing = [(s, e, d) for s, e, d in jobs
               if not d.exists() or d.stat().st_size < 1000]
    if not missing:
        log("  [pull] all %d chunks already cached for %s" % (len(jobs), today))
        return [d for _, _, d in jobs]

    with cdp_pull._cdp_lock(label="b2b_captainship_activations", log=log):
        cdp_pull._kill_ours()
        proc = cdp_pull._launch()
        log("  [cdp] real Chrome pid=%s; waiting 20s" % proc.pid)
        time.sleep(20)
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(
                    "http://127.0.0.1:%s" % cdp_pull.CDP_PORT)
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                tp._ensure_tableau_authenticated(page, verbose=False,
                                                 allow_form_login=True)
                log("  [cdp] auth OK")
                for s, e, dest in missing:
                    log("  [pull] %s..%s -> %s" % (s, e, dest.name))
                    body = _fetch_csv(
                        page, CSV_URL.format(s.isoformat(), e.isoformat()),
                        log=log)
                    dest.write_bytes(body)
        finally:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            cdp_pull._kill_ours()
    return [d for _, _, d in jobs]


# --------------------------------------------------------------------- tally

def tally(paths: Sequence[Path], weeks, log=print):
    """-> (act, sales, seen_owners) where act/sales =
    {section title: {display: {monday: number}}}."""
    from automations.att_order_log import clean

    week_of: Dict[dt.date, dt.date] = {}
    for mon, sun in weeks:
        d = mon
        while d <= sun:
            week_of[d] = mon
            d += dt.timedelta(days=1)

    act: Dict[str, Dict[str, collections.Counter]] = {
        t: collections.defaultdict(collections.Counter) for t, _ in SECTIONS}
    sales: Dict[str, Dict[str, collections.Counter]] = {
        t: collections.defaultdict(collections.Counter) for t, _ in SECTIONS}
    seen: Dict[str, set] = collections.defaultdict(set)
    repless_activations = 0
    total_lines = 0

    for path in paths:
        lines = clean.load_rows(str(path), owner_prefix=None)
        total_lines += len(lines)
        log("  [tally] %s: %s lines" % (path.name, "{:,}".format(len(lines))))
        for ln in lines:
            owner = _norm_owner(ln.get("Owner & Office"))
            if not owner or owner == "ALL":
                continue
            status = str(ln.get("DTR Status (enriched)", "") or "").strip().lower()
            posted = _parse_date(ln.get(POSTED_COL))
            odate = _parse_date(ln.get(ORDER_COL))

            hit = None
            for title, team in SECTIONS:
                for mem in team:
                    if not mem.matches(owner):
                        continue
                    hit = mem
                    seen[mem.display].add(owner)
                    if (posted is not None and status not in CANCEL_STATUSES
                            and posted in week_of and mem.active(posted)):
                        act[title][mem.display][week_of[posted]] += 1
                        if not str(ln.get("Rep", "") or "").strip():
                            repless_activations += 1
                    if odate is not None and odate in week_of and mem.active(odate):
                        prod = " ".join(str(
                            ln.get("Product Type (Broken Out)", "") or "").split()).upper()
                        if prod in COUNTED_PRODUCTS:
                            try:
                                u = float(ln.get("Unit Count") or 0)
                            except (TypeError, ValueError):
                                u = 0
                            if u:
                                sales[title][mem.display][week_of[odate]] += u

    log("  [tally] %s lines total; %d activated lines had no Rep"
        % ("{:,}".format(total_lines), repless_activations))
    wanted = {m.display for _, team in SECTIONS for m in team}
    for disp in sorted(wanted):
        if seen.get(disp):
            log("  [owner] %-18s <- %s" % (disp, "; ".join(sorted(seen[disp]))))
        else:
            log("  [owner] %-18s <- !! NO ROWS MATCHED in the whole window"
                % disp)
    return act, sales


# -------------------------------------------------------------------- render

def _grid(title, team, data, weeks, metric_int=True):
    """One section grid -> list of value rows. '-' = not on this captainship
    that week; 0 = on it, nothing counted."""
    hdr = ["Owner"] + ["WE %d/%d" % (sun.month, sun.day) for _, sun in weeks] + ["TOTAL"]
    rows = [[title] + [""] * (len(hdr) - 1), hdr]
    totals = collections.Counter()
    for mem in team:
        label = mem.display + ((" (%s)" % mem.note) if mem.note else "")
        cells, tot = [], 0
        for mon, sun in weeks:
            if mem.until < mon or mem.since > sun:
                cells.append(u"—")
                continue
            v = data.get(mem.display, {}).get(mon, 0)
            v = int(v) if metric_int else v
            cells.append(v)
            tot += v
            totals[mon] += v
        rows.append([label] + cells + [tot])
    rows.append(["TOTAL"] + [int(totals[mon]) for mon, _ in weeks]
                + [int(sum(totals.values()))])
    return rows


def render(act, sales, weeks, today):
    """-> (values, meta) where meta marks row kinds for formatting:
    list of (row_index_1based, kind) with kind in
    {'title','note','section','header','total'}."""
    values: List[list] = []
    meta: List[Tuple[int, str]] = []

    def push(row, kind=None):
        values.append(row)
        if kind:
            meta.append((len(values), kind))

    ncol = len(weeks) + 2
    push(["CAPTAINSHIP ACTIVATIONS — BY WEEK ENDING"] + [""] * (ncol - 1), "title")
    push(["Mon–Sun weeks. Activated = posted & not canceled/disconnected, in its "
          "POSTED week (morning activation-report rule). Total Sales = tracker "
          "apps (New Internet + Wireless + AIR/AWB units) by ORDER week. "
          "Captainship split 8/17. — = not on this captainship that week. "
          "Updated %s." % today.strftime("%m/%d/%Y")] + [""] * (ncol - 1), "note")
    push([""] * ncol)

    for stitle, team in SECTIONS:
        for metric, data in (("ACTIVATIONS", act), ("TOTAL SALES", sales)):
            g = _grid("%s — %s" % (stitle, metric), team, data[stitle], weeks)
            push(g[0], "section")
            push(g[1], "header")
            for r in g[2:-1]:
                push(r)
            push(g[-1], "total")
            push([""] * ncol)
    return values, meta


# --------------------------------------------------------------------- sheet

def write_sheet(values, meta, log=print, sheet_id: str = SHEET_ID):
    import gspread  # noqa: F401  (via recruiting_report.fill)

    from automations.recruiting_report.fill import _retry, open_by_key

    sh = open_by_key(sheet_id)
    ncol = max(len(r) for r in values)
    nrow = len(values) + 4
    try:
        ws = sh.worksheet(TAB)
    except Exception:  # noqa: BLE001 — WorksheetNotFound
        ws = _retry(lambda: sh.add_worksheet(title=TAB, rows=nrow, cols=ncol + 2))
        log("  [sheet] created tab %r" % TAB)
    if ws.title != TAB:
        raise RuntimeError("PROTECTED: refusing to write tab %r" % ws.title)

    _retry(lambda: ws.resize(rows=max(nrow, 40), cols=max(ncol + 2, 12)))
    _retry(lambda: ws.clear())
    _retry(lambda: ws.update(values, "A1", raw=True))
    log("  [sheet] wrote %d rows x %d cols" % (len(values), ncol))

    sid = ws.id
    kinds = dict((i, k) for i, k in meta)
    reqs = [
        # base: centered, plain
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0,
                      "endRowIndex": len(values), "startColumnIndex": 0,
                      "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"fontSize": 10}}},
            "fields": ("userEnteredFormat(horizontalAlignment,"
                       "verticalAlignment,textFormat)")}},
        # owner column left-aligned
        {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": 0,
                      "endRowIndex": len(values), "startColumnIndex": 0,
                      "endColumnIndex": 1},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
            "fields": "userEnteredFormat.horizontalAlignment"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 210}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 1, "endIndex": ncol},
            "properties": {"pixelSize": 78}, "fields": "pixelSize"}},
    ]

    def _band(i0, color, fg=None, bold=True, size=None):
        fmt = {"backgroundColor": color,
               "textFormat": {"bold": bold}}
        if fg:
            fmt["textFormat"]["foregroundColor"] = fg
        if size:
            fmt["textFormat"]["fontSize"] = size
        return {"repeatCell": {
            "range": {"sheetId": sid, "startRowIndex": i0 - 1,
                      "endRowIndex": i0, "startColumnIndex": 0,
                      "endColumnIndex": ncol},
            "cell": {"userEnteredFormat": fmt},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"}}

    white = {"red": 1, "green": 1, "blue": 1}
    navy = {"red": 0.12, "green": 0.30, "blue": 0.47}
    slate = {"red": 0.85, "green": 0.88, "blue": 0.91}
    maroon = {"red": 0.45, "green": 0.12, "blue": 0.12}
    grey = {"red": 0.93, "green": 0.93, "blue": 0.93}

    atef_seen = False
    for i, kind in sorted(kinds.items()):
        row0 = values[i - 1][0] if values[i - 1] else ""
        if kind == "title":
            reqs.append(_band(i, white, bold=True, size=14))
        elif kind == "note":
            reqs.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": i - 1,
                          "endRowIndex": i, "startColumnIndex": 0,
                          "endColumnIndex": ncol},
                "cell": {"userEnteredFormat": {
                    "horizontalAlignment": "LEFT",
                    "textFormat": {"italic": True, "fontSize": 8},
                    "wrapStrategy": "OVERFLOW_CELL"}},
                "fields": ("userEnteredFormat(horizontalAlignment,"
                           "textFormat,wrapStrategy)")}})
        elif kind == "section":
            if "ATEF" in str(row0).upper():
                atef_seen = True
            reqs.append(_band(i, maroon if atef_seen else navy, fg=white))
        elif kind == "header":
            reqs.append(_band(i, slate))
        elif kind == "total":
            reqs.append(_band(i, grey))

    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid,
                       "gridProperties": {"frozenRowCount": 2}},
        "fields": "gridProperties.frozenRowCount"}})
    _retry(lambda: sh.batch_update({"requests": reqs}))
    log("  [sheet] formatted (%d requests)" % len(reqs))


# ---------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="b2b_captainship_activations")
    ap.add_argument("--sheet", action="store_true",
                    help="write the tab (default: compute + print only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="never write, even if --sheet was passed (rerun-safe)")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--from-file", action="append", default=None, metavar="CSV",
                    help="parse these exports instead of pulling (repeatable)")
    ap.add_argument("--sheet-id", default=SHEET_ID)
    args = ap.parse_args(argv)

    log = print
    today = (dt.date.fromisoformat(args.today) if args.today else dt.date.today())
    weeks = completed_weeks(today)
    log("Captainship Activations — %s  (weeks WE %s .. WE %s)"
        % (today, weeks[0][1].strftime("%m/%d"), weeks[-1][1].strftime("%m/%d")))

    if args.from_file:
        paths = [Path(p) for p in args.from_file]
    else:
        start = weeks[0][0] - dt.timedelta(weeks=LOOKBACK_WEEKS)
        paths = pull_chunks(today, start, log=log)

    act, sales = tally(paths, weeks, log=log)
    values, meta = render(act, sales, weeks, today)

    for row in values:
        log("  | " + " | ".join("%7s" % c for c in row[:len(weeks) + 2]))

    if args.sheet and not args.dry_run:
        write_sheet(values, meta, log=log, sheet_id=args.sheet_id)
        log("DONE — wrote %r on the Vantura Master Sales Board" % TAB)
    else:
        log("DRY RUN — no sheet write (pass --sheet to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
