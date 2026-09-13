"""Settled per-day production for every ICD, from Tableau.

SARAPLUS IS LIVE, TABLEAU IS SETTLED (Megan 2026-09-13). The ICD agent reads
SaraPlus intraday, which is the only way to know what happened an hour ago —
but orders land late and get corrected, so an intraday reading of a CLOSED day
runs light. Measured on Cyrus's Saturday 2026-09-12: the relay's 5pm sweep had
16 units, Tableau the next morning had 19. New Internet (4), Wireless (8) and
Video (1) matched EXACTLY; the whole gap was AIR, 3 at 5pm against 6 settled.

So the board takes closed days from here and only today from the relay.

IT ALSO SOLVES COVERAGE. One pull carries every owner on the campaign — all of
them, per day, per product — so history for ~52 offices does not wait on ~52
laptops each having the agent installed and awake. The agent buys LIVE
numbers, not coverage.

THE VIEW is the same one the org sales board already pulls: ATTTRACKER2_1-D2D
→ AllproductsRafsteam, worksheet 'Sales By ICD (Weekly View)', week-pinned.
Its crosstab is one row per owner per product type, with a column per weekday:

    Owner Name | Product Type (Broken Out) | Monday … Sunday | Product Total

UTF-16, tab separated — Tableau's crosstab export always is, and opening it as
utf-8 dies on the BOM.

HEADED, NOT HEADLESS. The ownerville SSO hop fails its Cloudflare check under
`headless=True` ("no rqst after driving the form"); the headed self-heal walks
the form and passes. Do not "optimise" this back to headless.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
from pathlib import Path

# Tableau's product types -> the four columns a board keeps. VOICE is excluded
# by the view itself and reads 0 where it appears at all, so it is not mapped:
# a product nobody sells must not silently become an Int.
PRODUCT_TO_MEASURE = {
    "NEW INTERNET": "Int",
    "AIR": "Int Up",        # AT&T Internet Air — what SaraPlus counts as AIA
    "VIDEO": "DTV",
    "WIRELESS": "NL",
}
MEASURES = ["Int", "Int Up", "DTV", "NL"]

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]

# The row Tableau puts at the top for the whole campaign. It is not an owner.
_TOTAL_ROW = "sales total"

DEFAULT_PATH = Path("output") / "org_sales_board_fiber_byday.csv"


def _int(v) -> int:
    s = str(v or "").strip().replace(",", "")
    try:
        return int(float(s)) if s else 0
    except ValueError:
        return 0


def parse(path=DEFAULT_PATH, week_ending: dt.date | None = None) -> dict:
    """{owner: {date: {Int, Int Up, DTV, NL}}} from a pulled crosstab.

    `week_ending` is the Sunday the pull was pinned to; weekday columns are
    dated backwards from it. Passing the wrong week silently dates every row
    wrong, so the caller that PULLED the file is the one that should say.

    A missing file returns {} rather than raising: a board that cannot reach
    settled numbers should fall back to the live ones, not break."""
    path = Path(path)
    if not path.exists():
        return {}
    week_ending = week_ending or _this_sunday()
    monday = week_ending - dt.timedelta(days=6)
    day_of = {name: monday + dt.timedelta(days=i)
              for i, name in enumerate(_WEEKDAYS)}

    out: dict = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {m: 0 for m in MEASURES}))
    with open(path, encoding="utf-16") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            owner = str(row.get("Owner Name") or "").strip()
            if not owner or owner.lower() == _TOTAL_ROW:
                continue
            product = str(row.get("Product Type (Broken Out)")
                          or "").strip().upper()
            # 'Total' is Tableau's own per-owner subtotal. Adding it to the
            # measures would double every number on the board.
            measure = PRODUCT_TO_MEASURE.get(product)
            if measure is None:
                continue
            for name, day in day_of.items():
                n = _int(row.get(name))
                if n:
                    out[owner][day][measure] += n
    return {o: dict(days) for o, days in out.items()}


def _this_sunday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return today + dt.timedelta(days=(6 - today.weekday()) % 7)


def pull(week_ending: dt.date | None = None, out_dir=Path("output"),
         log=print) -> Path:
    """Pull the week-pinned crosstab and return its path.

    Runs a REAL browser through the ownerville SSO hop, so this belongs in a
    scheduled job, never in a page render."""
    from automations.org_sales_board import section_pull as SP
    from automations.shared.tableau_patchright import tableau_session

    week_ending = week_ending or _this_sunday()
    spec = SP.SPECS["fiber"]
    log(f"pulling {spec.section_label} for week ending {week_ending}…")
    with tableau_session(headless=False, verbose=False) as page:
        return SP.pull_section_byday(spec, Path(out_dir), page,
                                     today=week_ending)


def for_owner(owner: str, path=DEFAULT_PATH,
              week_ending: dt.date | None = None) -> dict:
    """{date: {Int, Int Up, DTV, NL}} for one owner — office TOTALS per day.

    Tableau's weekly view is per OWNER, not per rep, so this cannot fill a
    rep-level board on its own. It settles the office's daily totals; the
    relay is still what names who sold."""
    everyone = parse(path, week_ending)
    want = (owner or "").strip().lower()
    for name, days in everyone.items():
        if name.strip().lower() == want:
            return days
    return {}


# --------------------------------------------------------------- the store
# Where settled days live so a PAGE can read them. The crosstab itself lands
# on whichever machine ran the harvest (the mini), and the site may run
# somewhere else entirely, so the parsed rows go to a sheet — the same shape
# knocks_log uses for the same reason.
SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"   # AUTOMATION MASTER
TAB = "Board Days"
COLUMNS = ["Date", "Owner"] + MEASURES + ["Total", "Source"]


def log_days(path=DEFAULT_PATH, week_ending: dt.date | None = None,
             sheet_id: str = SHEET_ID, log=print) -> int:
    """Write a pulled crosstab's settled days to the sheet. Returns rows written.

    IDEMPOTENT per owner+day: a day already stored is REPLACED, not appended.
    The harvest re-runs and the same week gets pulled again at 14:30 catch-up,
    and a day that settles further has to be able to correct itself.

    NEVER FATAL. This hangs off a harvest whose real job is filling the org
    board; a logging problem must not take that down. Every failure returns 0
    and says why.
    """
    try:
        from automations.recruiting_report.fill import open_by_key, _retry

        by_owner = parse(path, week_ending)
        if not by_owner:
            log("  board days: nothing parsed (no crosstab?)")
            return 0

        sh = open_by_key(sheet_id)
        try:
            ws = sh.worksheet(TAB)
        except Exception:
            ws = sh.add_worksheet(title=TAB, rows=2000, cols=len(COLUMNS))
            ws.update("A1", [COLUMNS])

        grid = _retry(ws.get_all_values) or []
        header = [str(h).strip() for h in grid[0]] if grid else COLUMNS
        idx = {name: header.index(name) for name in COLUMNS if name in header}

        # TODAY IS NOT SETTLED. Only closed days are stored, or the first
        # write of the morning would freeze a part-day as final.
        today = dt.date.today()
        merged = {}
        for row in grid[1:] if grid else []:
            if len(row) <= max(idx.get("Owner", 1), idx.get("Date", 0)):
                continue
            merged[(str(row[idx["Date"]]).strip()[:10],
                    str(row[idx["Owner"]]).strip().lower())] = list(row)

        wrote = 0
        for owner, days in by_owner.items():
            for day, vals in days.items():
                if day >= today:
                    continue
                merged[(day.isoformat(), owner.strip().lower())] = (
                    [day.isoformat(), owner]
                    + [vals[m] for m in MEASURES]
                    + [sum(vals.values()), "tableau"])
                wrote += 1

        # ONE WRITE, NOT ONE PER ROW. Updating each row on its own took 84
        # calls for a single week and ran for minutes; a write loop like that
        # is also exactly what trips the Sheets 429 quota for whatever runs
        # next. The whole tab is rewritten in a single call instead, which is
        # idempotent by construction — re-running a day replaces it.
        body = [COLUMNS] + [merged[k] for k in sorted(merged)]
        _retry(ws.clear)
        _retry(ws.update, "A1", body, value_input_option="USER_ENTERED")
        log(f"  board days: {wrote} settled day-rows stored "
            f"({len(merged)} in the tab)")
        return wrote
    except Exception as e:   # noqa: BLE001 — never take the harvest down
        log(f"  board days: SKIPPED ({type(e).__name__}: {e})")
        return 0


def stored_days(owner: str = "", sheet_id: str = SHEET_ID) -> dict:
    """{owner: {date: {measures}}} straight from the sheet — no Tableau, no
    browser, safe to call from a page."""
    from automations.recruiting_report.fill import open_by_key

    grid = open_by_key(sheet_id).worksheet(TAB).get_all_values()
    if not grid:
        return {}
    header = [str(h).strip() for h in grid[0]]
    want = (owner or "").strip().lower()
    out: dict = collections.defaultdict(dict)
    for row in grid[1:]:
        rec = dict(zip(header, row))
        name = str(rec.get("Owner") or "").strip()
        if not name or (want and name.lower() != want):
            continue
        try:
            day = dt.date.fromisoformat(str(rec.get("Date") or "")[:10])
        except ValueError:
            continue
        out[name][day] = {m: _int(rec.get(m)) for m in MEASURES}
    return dict(out)
