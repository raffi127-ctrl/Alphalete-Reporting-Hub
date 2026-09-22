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


def _pinned_sunday(week_ending):
    """The Sunday ending the week a pinned view ACTUALLY returns for a date.

    The crosstab carries weekday NAMES and no dates, so every number is dated
    backwards from this Sunday. The org board's 2am pull was handing in the
    run date instead — on six days of seven that stamped each weekday a few
    days off and replaced good rows (Raf's settled week read 537 apps against
    253 on his own sheet, Sundays showing weekday volume; 2026-09-22). This
    maps any date to the same week pinned_view_url pins, so the parse and the
    pull cannot disagree. A Sunday maps to itself, so callers that already pass
    one are unchanged."""
    from automations.org_sales_board import week as _wk
    return _wk.reporting_sunday(week_ending or dt.date.today())


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
    week_ending = _pinned_sunday(week_ending)
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


# THE REP-LEVEL VIEW (Megan pointed at it, 2026-09-13). Same workbook as the
# office view, different dashboard: ALLICDSALLREPSBD — "all ICDs, all reps".
# Its crosstab carries a Rep column the office view does not:
#
#   Owner Name | Rep | Product Type (Broken Out) | Monday … Sunday | Product Total
#
# That is the whole board, for every office, without any laptop: 516 rows and
# 19 reps for Cyrus alone. WEEK-PINNED like everything else here — the bare
# URL returns whatever week the view defaults to, which read 177 units for
# Cyrus against 157 for the week actually being looked at.
REP_VIEW = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "ATTTRACKER2_1-D2D/PRODUCTSALESSUMMARY4WK/"
            "7ea543c9-3d5a-462e-9cc1-ccbfd4f8e953/ALLICDSALLREPSBD")
REP_SHEET = "Sales By ICD (Weekly View)"
REP_PATH = Path("output") / "icd_board_reps_byday.csv"


def rep_spec():
    """A ScrapeSpec for the rep view, borrowing the office spec's pinning so
    both read the SAME week rather than two views drifting apart."""
    import dataclasses
    from automations.org_sales_board import section_pull as SP
    # dataclasses.replace, not _replace — ScrapeSpec is a dataclass, not a
    # namedtuple, and the two spell this differently.
    return dataclasses.replace(
        SP.FIBER_SPEC,
        section_label="ICD board — all reps",
        view_url=REP_VIEW,
        crosstab_sheet=REP_SHEET,
        out_name=REP_PATH.name)


def pull_reps_with(page, week_ending: dt.date | None = None,
                   out_dir=Path("output"), log=print) -> Path:
    """Pull the rep crosstab onto an ALREADY-OPEN Tableau page.

    The harvest holds a live session; opening a second one would be a second
    login against an access budget that is watched."""
    from automations.org_sales_board import section_pull as SP
    from automations.shared.tableau_patchright import (
        download_crosstab_patchright)

    week_ending = _pinned_sunday(week_ending)
    url = SP.pinned_view_url(rep_spec(), week_ending, logfn=log)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out = Path(out_dir) / REP_PATH.name
    download_crosstab_patchright(url, REP_SHEET, out, page=page, verbose=False)
    log(f"  saved {out}")
    return out


def pull_reps(week_ending: dt.date | None = None, out_dir=Path("output"),
              log=print) -> Path:
    """Pull the rep-level crosstab, week-pinned. Headed browser — scheduled
    jobs only, never a page render."""
    from automations.org_sales_board import section_pull as SP
    from automations.shared.tableau_patchright import (
        tableau_session, download_crosstab_patchright)

    week_ending = _pinned_sunday(week_ending)
    url = SP.pinned_view_url(rep_spec(), week_ending, logfn=log)
    out = Path(out_dir) / REP_PATH.name
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # Downloading DIRECTLY rather than through pull_section_byday: routed
    # through that wrapper this view dies every time on "Download.save_as:
    # Target page ... has been closed", and downloads first try when called
    # straight. Not worth chasing — the wrapper adds nothing here but a
    # day-behind branch this view does not need.
    with tableau_session(headless=False, verbose=False) as page:
        download_crosstab_patchright(url, REP_SHEET, out, page=page,
                                     verbose=False)
    log(f"  saved {out}")
    return out


def parse_reps(path=REP_PATH, week_ending: dt.date | None = None) -> dict:
    """{owner: {rep: {date: {Int, Int Up, DTV, NL}}}}.

    Tableau's own subtotal rows carry Rep 'Total' or Product 'Total'; both are
    skipped, or every number would be counted twice."""
    path = Path(path)
    if not path.exists():
        return {}
    week_ending = _pinned_sunday(week_ending)
    monday = week_ending - dt.timedelta(days=6)
    day_of = {name: monday + dt.timedelta(days=i)
              for i, name in enumerate(_WEEKDAYS)}

    out: dict = collections.defaultdict(lambda: collections.defaultdict(dict))
    with open(path, encoding="utf-16") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            owner = str(row.get("Owner Name") or "").strip()
            rep = str(row.get("Rep") or "").strip()
            product = str(row.get("Product Type (Broken Out)")
                          or "").strip().upper()
            if (not owner or owner.lower() == _TOTAL_ROW
                    or not rep or rep.lower() == "total"):
                continue
            measure = PRODUCT_TO_MEASURE.get(product)
            if measure is None:
                continue
            for name, day in day_of.items():
                n = _int(row.get(name))
                if not n:
                    continue
                cell = out[owner][rep].setdefault(
                    day, {m: 0 for m in MEASURES})
                cell[measure] += n
    return {o: dict(reps) for o, reps in out.items()}


def pull(week_ending: dt.date | None = None, out_dir=Path("output"),
         log=print) -> Path:
    """Pull the week-pinned crosstab and return its path.

    Runs a REAL browser through the ownerville SSO hop, so this belongs in a
    scheduled job, never in a page render."""
    from automations.org_sales_board import section_pull as SP
    from automations.shared.tableau_patchright import tableau_session

    week_ending = _pinned_sunday(week_ending)
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


# Rep rows get their OWN tab rather than a Rep column on the office one: the
# office totals are already stored and read, and adding a column would mean
# migrating them for no gain. Same write discipline — one call, whole tab.
REP_TAB = "Board Rep Days"
REP_COLUMNS = ["Date", "Owner", "Rep"] + MEASURES + ["Total", "Source"]


def log_rep_days(path=REP_PATH, week_ending: dt.date | None = None,
                 sheet_id: str = SHEET_ID, log=print) -> int:
    """Store settled per-REP days. Idempotent, never fatal — see log_days."""
    try:
        from automations.recruiting_report.fill import open_by_key, _retry

        by_owner = parse_reps(path, week_ending)
        if not by_owner:
            log("  board rep days: nothing parsed (no crosstab?)")
            return 0

        sh = open_by_key(sheet_id)
        try:
            ws = sh.worksheet(REP_TAB)
        except Exception:
            ws = sh.add_worksheet(title=REP_TAB, rows=4000,
                                  cols=len(REP_COLUMNS))

        grid = _retry(ws.get_all_values) or []
        header = [str(h).strip() for h in grid[0]] if grid else REP_COLUMNS
        idx = {n: header.index(n) for n in REP_COLUMNS if n in header}

        merged = {}
        for row in grid[1:] if grid else []:
            if len(row) <= max(idx.get("Rep", 2), idx.get("Date", 0)):
                continue
            merged[(str(row[idx["Date"]]).strip()[:10],
                    str(row[idx["Owner"]]).strip().lower(),
                    str(row[idx["Rep"]]).strip().lower())] = list(row)

        today = dt.date.today()
        wrote = 0
        for owner, reps in by_owner.items():
            for rep, days in reps.items():
                for day, vals in days.items():
                    if day >= today:          # today is not settled
                        continue
                    merged[(day.isoformat(), owner.strip().lower(),
                            rep.strip().lower())] = (
                        [day.isoformat(), owner, rep]
                        + [vals[m] for m in MEASURES]
                        + [sum(vals.values()), "tableau"])
                    wrote += 1

        body = [REP_COLUMNS] + [merged[k] for k in sorted(merged)]
        _retry(ws.clear)
        _retry(ws.update, "A1", body, value_input_option="USER_ENTERED")
        log(f"  board rep days: {wrote} stored ({len(merged)} in the tab)")
        return wrote
    except Exception as e:   # noqa: BLE001
        log(f"  board rep days: SKIPPED ({type(e).__name__}: {e})")
        return 0


def stored_rep_days(owner: str, sheet_id: str = SHEET_ID) -> dict:
    """{rep: {date: {measures}}} for one owner, straight from the sheet."""
    from automations.recruiting_report.fill import open_by_key

    grid = open_by_key(sheet_id).worksheet(REP_TAB).get_all_values()
    if not grid:
        return {}
    header = [str(h).strip() for h in grid[0]]
    want = (owner or "").strip().lower()
    out: dict = collections.defaultdict(dict)
    for row in grid[1:]:
        rec = dict(zip(header, row))
        if str(rec.get("Owner") or "").strip().lower() != want:
            continue
        rep = str(rec.get("Rep") or "").strip()
        try:
            day = dt.date.fromisoformat(str(rec.get("Date") or "")[:10])
        except ValueError:
            continue
        if rep:
            out[rep][day] = {m: _int(rec.get(m)) for m in MEASURES}
    return dict(out)


# HOW FAR BACK THE PIN CAN BE TRUSTED. One week. Pinning two and three weeks
# back (2026-09-13) returned something that was NOT the requested week, and
# nothing in the download says otherwise — see backfill()'s warning.
MAX_BACKFILL_WEEKS = 1


def backfill(week_ending: dt.date, out_dir=Path("output"),
             force: bool = False, log=print) -> int:
    """Pull and store ONE past week, office totals and per-rep days.

    REFUSES TO REACH FURTHER BACK THAN ONE WEEK, and that limit is the whole
    point of this function having a guard.

    The crosstab has WEEKDAY-NAME columns and no dates in it — parse() assigns
    dates from the week_ending you pass. So if the download is not actually
    the week that was pinned, every number is stamped with wrong dates and
    log_*_days replaces good rows with them. There is nothing in the file to
    catch it with.

    That is not hypothetical: on 2026-09-14 a backfill pinned to 09-06 and
    08-30 wrote numbers that inflated Raf's settled week from 343 apps to
    518 — his own board says 365 — and shifted the office series a day. Both
    tabs had to be cleared and the single verifiable week re-pulled.

    One week back the pin demonstrably holds: it is what the nightly harvest
    does. Further back it silently does not. `force` exists for somebody who
    has re-verified the view, and should be used with a number to check
    against."""
    if not force:
        limit = _this_sunday() - dt.timedelta(days=7 * MAX_BACKFILL_WEEKS)
        if week_ending < limit:
            log(f"  refusing {week_ending}: more than {MAX_BACKFILL_WEEKS} "
                f"week(s) back, where the view has returned the WRONG week "
                f"and there is no date in the file to catch it. Re-verify the "
                f"pinned view first, then pass force.")
            return 0
    rows = 0
    try:
        path = pull(week_ending=week_ending, out_dir=out_dir, log=log)
        rows += log_days(path, week_ending=week_ending, log=log)
    except Exception as e:   # noqa: BLE001 — one half is not the run
        log(f"  office days: FAILED ({type(e).__name__}: {e})")
    try:
        rpath = pull_reps(week_ending=week_ending, out_dir=out_dir, log=log)
        rows += log_rep_days(rpath, week_ending=week_ending, log=log)
    except Exception as e:   # noqa: BLE001
        log(f"  rep days: FAILED ({type(e).__name__}: {e})")
    return rows


def main(argv=None) -> int:
    """Backfill settled board days for past weeks.

        lucy rerun icd_board_backfill                  # last week
        lucy rerun icd_board_backfill --weeks 4        # the last four

    Runs a HEADED browser through the ownerville SSO hop, so it belongs on a
    machine that holds a Tableau session — never in a page render."""
    import argparse

    ap = argparse.ArgumentParser(prog="icd_board_backfill")
    ap.add_argument("--week-ending", default="",
                    help="Sunday to pull, YYYY-MM-DD. Default: last week.")
    ap.add_argument("--weeks", type=int, default=1,
                    help="How many weeks back from there, inclusive.")
    ap.add_argument("--force", action="store_true",
                    help="Store a week older than the pin is trusted for. "
                         "Only after re-verifying the view returns it.")
    a = ap.parse_args(argv)

    end = (dt.date.fromisoformat(a.week_ending) if a.week_ending
           else _this_sunday() - dt.timedelta(days=7))
    total = 0
    for i in range(max(1, a.weeks)):
        wk = end - dt.timedelta(days=7 * i)
        print(f"[week ending {wk}]", flush=True)
        total += backfill(wk, force=a.force)
    print(f"done — {total} row(s) stored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
