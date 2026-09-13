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


def _sundays(start: dt.date, end: dt.date) -> list:
    """Every week-opening SUNDAY the range touches.

    Proven against the live report, not assumed: post any date and the server
    snaps it back to the Sunday on or before it, then renders Sunday through
    Saturday. Asking for 09-05, a Saturday, returns the week of 08-30. That
    one rule is behind every run that landed a week early."""
    first = start - dt.timedelta(days=(start.weekday() + 1) % 7)
    out, cur = [], first
    while cur <= end:
        out.append(cur)
        cur += dt.timedelta(days=7)
    return out


def _form_base(page) -> dict:
    """The retention form's own fields, so a week can be asked for directly."""
    return page.evaluate(
        """() => {
            const f = document.forms['frmRR'];
            if (!f) return null;
            const o = {};
            [...f.querySelectorAll('input,select')].forEach(e => {
                if (e.name) o[e.name] = e.value || '';
            });
            return o;
        }""")


def _week_links(page, base: dict, sunday: dt.date) -> dict:
    """{iso date: detail href} for the BOB row of one week.

    Asks the server for the week and reads its answer, rather than driving the
    page to it. Everything else was tried and ruled out: the week box is
    readonly and wired to a jQuery UI calendar, the report carries no
    prev/next control, and the week cannot be passed in the URL. The form
    answers plainly, so this asks it."""
    payload = dict(base)
    payload["weekStart"] = sunday.strftime("%m-%d-%Y")
    payload["startDate2"] = sunday.strftime("%m/%d/%Y")
    days = [sunday + dt.timedelta(days=i) for i in range(7)]
    return page.evaluate(
        r"""async ([payload, labels, rowLabel]) => {
            const body = new URLSearchParams(payload).toString();
            const r = await fetch('index.cfm', {
                method: 'POST', body, credentials: 'include',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            });
            const doc = new DOMParser()
                .parseFromString(await r.text(), 'text/html');
            const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const trs = [...doc.querySelectorAll('tr')];
            const row = trs.find(tr => {
                const c = tr.querySelector('td,th');
                return c && norm(c.innerText).startsWith(norm(rowLabel));
            });
            if (!row) return {};
            const out = {};
            for (const [iso, label] of labels) {
                const cells = trs.map(tr => [...tr.children]).find(
                    cs => cs.some(c => norm(c.innerText).includes(norm(label))));
                if (!cells) continue;
                const col = cells.findIndex(
                    c => norm(c.innerText).includes(norm(label)));
                const a = row.children[col]
                          && row.children[col].querySelector('a');
                if (a) out[iso] = a.getAttribute('href');
            }
            return out;
        }""",
        [payload, [[d.isoformat(), _header(d)] for d in days], BOB_ROW])


def harvest(office_id: str, owner: str, start: dt.date, end: dt.date,
            log=print) -> dict:
    """{rep: earliest date seen} for one office, from the BOB detail pages.

    A day with no arrivals has no detail link and is skipped, not retried —
    that is the ordinary case, not a failure."""
    from automations.applicant_tracker import applicantstream as A

    found: dict = {}
    with A.session() as app:
        app.select_office(str(office_id))
        app.open_retention_details()
        base = _form_base(app.page)
        if not base:
            log(f"  {owner}: retention form not found — skipped")
            return {}

        # EVERY href first, then the visits. scrape_at navigates away from the
        # report, and re-showing the week after each day was most of this
        # report's cost; asking for a week is one request.
        weeks = _sundays(start, end)
        links: dict = {}
        for sunday in weeks:
            try:
                links.update(_week_links(app.page, base, sunday))
            except Exception as e:   # noqa: BLE001 — one week is not the run
                log(f"  {owner}: week of {sunday} failed ({type(e).__name__})")
        log(f"  {owner}: {len(links)} day(s) with arrivals "
            f"across {len(weeks)} week(s)")

        for iso in sorted(links):
            day = dt.date.fromisoformat(iso)
            if day < start or day > end:
                continue
            try:
                for r in app.scrape_at(links[iso], BOB_COLS):
                    name = " ".join(str(x).strip()
                                    for x in r[:2] if str(x).strip())
                    if not name:
                        continue
                    key = name.strip().lower()
                    # EARLIEST wins: a rep who returns did not start again.
                    if key not in found or day < found[key][1]:
                        found[key] = (name, day)
            except Exception as e:   # noqa: BLE001 — one day is not the run
                log(f"  {owner} {day}: skipped ({type(e).__name__})")

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


# --------------------------------------------------------------------- cli
def _offices() -> dict:
    """{office_id: owner} — AppStream's own ids, from the tracker's list."""
    from automations.applicant_tracker import config as C
    return dict(C.OFFICE_NAMES)


def main(argv=None) -> int:
    """Runs on LUCY 1, which holds the warm AppStream session. Megan's laptop
    has no AppStream credential and should not get one — every machine mints
    its own, and the sessions are not shared.

        lucy rerun icd_start_dates                  # every mapped office
        lucy rerun icd_start_dates --office 11280   # one
        lucy rerun icd_start_dates --weeks 8        # reach further back
    """
    import argparse

    ap = argparse.ArgumentParser(prog="icd_start_dates")
    ap.add_argument("--office", action="append", default=[],
                    help="AppStream office id; repeatable. Default: all.")
    ap.add_argument("--weeks", type=int, default=5,
                    help="How far back to look. 5 is enough — a rep who is "
                         "not in that window is a veteran, not an unknown.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Read AppStream, write nothing.")
    a = ap.parse_args(argv)

    offices = _offices()
    wanted = [(o, offices.get(o, o)) for o in a.office] if a.office \
        else sorted(offices.items())
    end = dt.date.today()
    start = end - dt.timedelta(days=a.weeks * 7 - 1)

    total = 0
    for office_id, owner in wanted:
        print(f"[{office_id}] {owner}", flush=True)
        try:
            dates = harvest(office_id, owner, start, end)
        except Exception as e:   # noqa: BLE001 — one office is not the run
            print(f"  FAILED ({type(e).__name__}: {e})", flush=True)
            continue
        if a.dry_run:
            for rep, day in sorted(dates.items(), key=lambda kv: kv[1]):
                print(f"    {rep:<28} {day}  {tenure_label(day, end)}")
            print(f"  dry run — {len(dates)} found, nothing written")
            continue
        total += store(owner, dates)
    print(f"done — {total} start date(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
