"""When each rep actually started, from AppStream.

WHY THIS EXISTS. The board colours a rep's row by how long they have been
here, and that is the first thing Raf reads off it: "the colors are important
just to judge where they're at in the onboarding process ... when we see where
people fall off, it's important to know what week they fell off." Tenure is
computed from a start date, and almost nobody has one on file — 42 of Raf's 61
reps were blank — so the colour was coming off his spreadsheet instead. The
board is meant to REPLACE that sheet (Megan 2026-09-13), so it cannot depend
on reading it.

Raf named the source in the same Loom: "days worked based off the start date,
which it just can be pulled off of AppStream."

WHAT A START DATE IS HERE. AppStream's retention report has a "Total Daily
Bob" row, and the detail page behind each day lists the people brought on
board THAT day. Being brought on board is being booked for a first day, so
the earliest day a rep appears there is when they started. Earliest, never
latest: somebody who comes back is not starting again.

COST, and why this is a harvest and not a page read. One page load per day per
office. A backfill of eight weeks across sixteen offices is nearly a thousand
loads, so it runs once and then keeps up a day at a time. It also needs a real
browser on the warm rcaptain session, like every other AppStream job.
"""
from __future__ import annotations

import collections
import datetime as dt

SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"   # AUTOMATION MASTER
TAB = "Rep Start Dates"
COLUMNS = ["Owner", "Rep", "Start Date", "Source"]

# The retention row whose detail page lists that day's arrivals.
BOB_ROW = "Total Daily Bob"

# First Name · Last Name · Email · Phone · Rating · Job Board · Date and Time
# · Ad — eight data columns, confirmed against the live popup 2026-09-13.
BOB_COLS = 8


def _header(day: dt.date) -> str:
    """The retention grid's column header for a day: 'Sep 8, 2026'."""
    return f"{day.strftime('%b')} {day.day}, {day.year}"


def harvest(office_id: str, owner: str, start: dt.date, end: dt.date,
            log=print) -> dict:
    """{rep: earliest date seen} for one office, by walking the BOB detail
    page for every day in the range.

    A day with no arrivals has no detail link and is skipped, not retried —
    that is the ordinary case, not a failure."""
    from automations.applicant_tracker import applicantstream as A

    found: dict = {}
    with A.session() as app:
        app.select_office(str(office_id))
        day = start
        while day <= end:
            try:
                app.open_retention_details()
                href = app.detail_href(BOB_ROW, _header(day))
                if href:
                    for r in app.scrape_at(href, BOB_COLS):
                        name = " ".join(str(x).strip()
                                        for x in r[:2] if str(x).strip())
                        if not name:
                            continue
                        key = name.strip().lower()
                        # EARLIEST wins: a rep who returns did not start again.
                        if key not in found or day < found[key][1]:
                            found[key] = (name, day)
            except Exception as e:   # noqa: BLE001 — one bad day is not the run
                log(f"  {owner} {day}: skipped ({type(e).__name__})")
            day += dt.timedelta(days=1)
    log(f"  {owner}: {len(found)} start date(s) between {start} and {end}")
    return {v[0]: v[1] for v in found.values()}


def store(owner: str, dates: dict, sheet_id: str = SHEET_ID, log=print) -> int:
    """Write start dates, keeping the EARLIEST already on file.

    Never overwrites an older date with a newer one — a backfill that reaches
    further back must be able to correct the tab, while a daily run that only
    sees this week must not move somebody's start forward."""
    try:
        from automations.recruiting_report.fill import open_by_key, _retry

        sh = open_by_key(sheet_id)
        try:
            ws = sh.worksheet(TAB)
        except Exception:
            ws = sh.add_worksheet(title=TAB, rows=4000, cols=len(COLUMNS))

        grid = _retry(ws.get_all_values) or []
        header = [str(h).strip() for h in grid[0]] if grid else COLUMNS
        idx = {n: header.index(n) for n in COLUMNS if n in header}

        merged = {}
        for row in grid[1:] if grid else []:
            if len(row) <= idx.get("Rep", 1):
                continue
            merged[(str(row[idx["Owner"]]).strip().lower(),
                    str(row[idx["Rep"]]).strip().lower())] = list(row)

        wrote = 0
        for rep, day in dates.items():
            key = (owner.strip().lower(), rep.strip().lower())
            was = merged.get(key)
            if was:
                try:
                    old = dt.date.fromisoformat(
                        str(was[idx["Start Date"]]).strip()[:10])
                    if old <= day:
                        continue        # already have an earlier or equal one
                except ValueError:
                    pass
            merged[key] = [owner, rep, day.isoformat(), "appstream"]
            wrote += 1

        body = [COLUMNS] + [merged[k] for k in sorted(merged)]
        _retry(ws.clear)
        _retry(ws.update, "A1", body, value_input_option="USER_ENTERED")
        log(f"  {owner}: {wrote} start date(s) written ({len(merged)} on file)")
        return wrote
    except Exception as e:   # noqa: BLE001 — never take a harvest down
        log(f"  start dates: SKIPPED ({type(e).__name__}: {e})")
        return 0


def stored(owner: str = "", sheet_id: str = SHEET_ID) -> dict:
    """{rep lowered: date} — no browser, safe to call from a page."""
    from automations.recruiting_report.fill import open_by_key

    try:
        grid = open_by_key(sheet_id).worksheet(TAB).get_all_values()
    except Exception:
        return {}
    if not grid:
        return {}
    header = [str(h).strip() for h in grid[0]]
    want = (owner or "").strip().lower()
    out = {}
    for row in grid[1:]:
        rec = dict(zip(header, row))
        if want and str(rec.get("Owner") or "").strip().lower() != want:
            continue
        rep = str(rec.get("Rep") or "").strip()
        try:
            day = dt.date.fromisoformat(str(rec.get("Start Date") or "")[:10])
        except ValueError:
            continue
        if rep:
            out[rep.lower()] = day
    return out


def tenure_label(start: dt.date, on: dt.date | None = None) -> str:
    """'1st Wk' … '4th Wk' … '5th wk+', spelled the way the board spells it.

    Weeks are counted from the MONDAY of the start week, so everyone who
    started in the same week shares a tenure — which is what the field status
    means on the board, rather than a rolling seven days per person."""
    on = on or dt.date.today()
    first_monday = start - dt.timedelta(days=start.weekday())
    this_monday = on - dt.timedelta(days=on.weekday())
    weeks = ((this_monday - first_monday).days // 7) + 1
    if weeks <= 0:
        return ""
    if weeks >= 5:
        return "5th wk+"
    return {1: "1st Wk", 2: "2nd Wk", 3: "3rd Wk", 4: "4th Wk"}[weeks]


def labels_for(owner: str, on: dt.date | None = None,
               sheet_id: str = SHEET_ID) -> dict:
    """{rep lowered: tenure label} for one office, ready for the board."""
    return {rep: tenure_label(day, on)
            for rep, day in stored(owner, sheet_id).items()}
