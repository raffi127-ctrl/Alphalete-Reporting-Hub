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


def page_week(page) -> "dt.date | None":
    """The week the retention report is ALREADY showing, read off the box.

    Every failure so far came from guessing this. A Monday anchor was wrong;
    a Saturday anchor was wrong too — the page's own default came back
    09-06-2026, a Sunday. So the anchor is not assumed any more, it is read,
    and the weeks are stepped back from it. That also makes this correct for
    any office whose report is set up differently."""
    try:
        v = page.evaluate(
            """() => {
                const b = [...document.querySelectorAll('input')]
                            .find(x => x.name === 'weekStart');
                return b ? (b.value || '').trim() : '';
            }""")
        return dt.datetime.strptime(v, "%m-%d-%Y").date() if v else None
    except Exception:   # noqa: BLE001 — caller falls back
        return None


def _weeks_back_from(anchor: dt.date, start: dt.date, end: dt.date) -> list:
    """Every week opening from `anchor` back far enough to cover `start`.

    Anchor comes from the page, so the weekday is whatever AppStream uses."""
    out, cur = [], anchor
    while cur + dt.timedelta(days=6) >= start:
        if cur <= end:
            out.append(cur)
        cur -= dt.timedelta(days=7)
        if len(out) > 60:           # a guard, not a limit anyone should hit
            break
    return sorted(out)


_LAST_DIAG: dict = {}


def _capture(page) -> None:
    """Record where a failed week attempt actually landed.

    Every failure so far has been a wrong guess about what the page did, and
    the exception path used to skip this entirely — a navigation destroys the
    polling context, so the run ended with nothing to show for it.
    """
    if "landed" in _LAST_DIAG:
        return
    try:
        _LAST_DIAG["landed"] = page.evaluate(
            r"""() => {
                const box = [...document.querySelectorAll('input')]
                              .find(x => x.name === 'weekStart');
                return {
                    url: location.href.slice(-90),
                    box: box ? box.value : '(gone)',
                    head: (document.body.innerText || '')
                            .replace(/\s+/g, ' ').trim().slice(0, 220),
                };
            }""")
    except Exception:   # noqa: BLE001 — diagnostics never break a run
        _LAST_DIAG["landed"] = "unreadable"


def _show_week(page, wk_start: dt.date, log=print) -> bool:
    """Put the retention report on `monday`'s week and submit.

    The Week box and its button are found by what they LOOK like rather than
    by id: an input holding a MM-DD-YYYY date, and the control whose text is
    "Get Report". AppStream's ids are generated and this page is not one we
    control, so a shape match survives a rename where a hardcoded id does not.
    Returns False rather than raising — a week that will not open is a week to
    skip, not a failed harvest."""
    # The caller re-opens the report through the DRIVER. Building the url by
    # hand here was the first fault: the real one is
    # index.cfm?p=701&rqst=…&newOfficeId=… — a "?p=", not an "&p=" — so
    # splitting on "&p=" returned the whole url and appended a SECOND p
    # parameter, landing somewhere with no date box at all.
    want_value = wk_start.strftime("%m-%d-%Y")
    want_header = _header(wk_start)
    try:
        # WHAT IS THIS BOX CALLED? Driving the form — setting .value, and then
        # really typing into it and clicking Get Report — left the page on the
        # week it loads with, both times. This is a ColdFusion page, and those
        # generally accept their own form fields as URL parameters, so the
        # field NAME is worth more than another synthetic click.
        found = page.evaluate(
            r"""() => {
                const ins = [...document.querySelectorAll('input')];
                const i = ins.findIndex(
                    x => /^\d{2}-\d{2}-\d{4}$/.test((x.value||'').trim()));
                if (i < 0) return null;
                const box = ins[i];
                const form = box.form;
                const submit = [...document.querySelectorAll('input,button')]
                    .find(b => /get\s*report/i.test(b.value || b.innerText || ''));
                return {
                    idx: i,
                    name: box.name || '', id: box.id || '',
                    readOnly: !!box.readOnly,
                    action: form ? (form.getAttribute('action') || '') : null,
                    method: form ? (form.method || '') : null,
                    submitName: submit ? (submit.name || '') : '',
                    submitValue: submit ? (submit.value || '') : '',
                };
            }""")
        if not found:
            log(f"    week {wk_start}: no date box on the page")
            return False
        if not _LAST_DIAG:
            _LAST_DIAG.update(found)   # rides the summary line; see harvest()
        if "fields" not in _LAST_DIAG:
            # EVERY field, once. The POST lands a week EARLIER than asked for,
            # so weekStart is plainly not the only thing steering it, and one
            # more hypothesis per run is not a way to find the other one.
            try:
                _LAST_DIAG["fields"] = page.evaluate(
                    r"""() => {
                        const box = [...document.querySelectorAll('input')]
                                      .find(x => x.name === 'weekStart');
                        const f = box && box.form;
                        if (!f) return '(no form)';
                        return [...f.querySelectorAll('input,select')]
                            .map(e => `${e.name || e.id || e.type}=${
                                 (e.value || '').slice(0, 12)}`)
                            .join(' ');
                    }""")[:300]
            except Exception:   # noqa: BLE001
                _LAST_DIAG["fields"] = "unreadable"
        log(f"    week {wk_start}: box={found}")

        # The box is READONLY and the form is a POST. That is both failures
        # explained at once: typing into a readonly input does nothing, and a
        # POST form reads form scope, not the URL. So set the value directly
        # and post the form natively.
        #
        # Native submit, not a click: the Get Report control is NAMED "submit",
        # which shadows form.submit on the element, and whatever handler sits
        # on it is free to re-read the calendar widget and put the old week
        # back. HTMLFormElement.prototype.submit.call() steps around both. A
        # readonly field is still submitted (unlike a disabled one), and the
        # native submit omits the button's own name/value pair, so that gets
        # added as a hidden field in case the page tests for it.
        page.evaluate(
            r"""([idx, want]) => {
                const box = [...document.querySelectorAll('input')][idx];
                const form = box.form;
                // The form's action is a bare "index.cfm" — posting it as-is
                // drops p=701, rqst and newOfficeId and lands on the home
                // page, which is exactly what the last run recorded. Point it
                // at the URL we are already on so the query string survives
                // and weekStart rides in the body.
                if (form) form.action = location.href;
                box.removeAttribute('readonly');
                box.value = want;
                box.dispatchEvent(new Event('change', {bubbles: true}));
                if (!form) return;
                let h = form.querySelector("input[type=hidden][name=submit]");
                if (!h) {
                    h = document.createElement('input');
                    h.type = 'hidden'; h.name = 'submit'; h.value = 'Get Report';
                    form.appendChild(h);
                }
                HTMLFormElement.prototype.submit.call(form);
            }""", [found["idx"], want_value])

        # CONFIRM THE PAGE ACTUALLY CHANGED — and confirm it against the BOX,
        # not against a header string I formatted myself. The box is what the
        # server echoes back, so it says what the server actually honoured;
        # a header guess can only ever tell me my guess was wrong.
        for _ in range(20):
            page.wait_for_timeout(750)
            try:
                if page_week(page) == wk_start:
                    # The box is the server's own answer, so this is the test.
                    # The header string is NOT a test — it is my formatting
                    # guess, and requiring it was rejecting weeks that had in
                    # fact opened. Record the real headers instead: the same
                    # guess is what detail_href matches day columns on, so it
                    # is also why every opened week yielded nothing.
                    if "headers" not in _LAST_DIAG:
                        try:
                            _LAST_DIAG["headers"] = page.evaluate(
                                r"""() => [...document.querySelectorAll('table tr')]
                                        .map(r => r.innerText.replace(/\s+/g,' ').trim())
                                        .filter(t => /\d{4}|Mon|Sat|Sun/.test(t))[0]
                                        || '(no dated row)'""")[:200]
                        except Exception:   # noqa: BLE001
                            _LAST_DIAG["headers"] = "unreadable"
                    return True
            except Exception:   # noqa: BLE001 — navigation destroyed the context
                continue

        _capture(page)
        log(f"    week {wk_start}: submitted but {want_header!r} never appeared")
        return False
    except Exception as e:   # noqa: BLE001
        _LAST_DIAG.setdefault("raised", type(e).__name__)
        _capture(page)
        log(f"    week {wk_start}: {type(e).__name__}")
        return False


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
        # ONE PASS PER WEEK, not per day. The retention report renders ONE
        # week at a time — the first run walked 35 days against a page that
        # only ever showed the current week's seven columns and found nothing,
        # exit 0. Set the week, submit, then read its days.
        app.open_retention_details()
        anchor = page_week(app.page)
        if anchor is None:
            log(f"  {owner}: no week box on the retention report — skipped")
            return {}
        log(f"  {owner}: report opens on the week of {anchor}")
        weeks = _weeks_back_from(anchor, start, end)
        opened = 0
        for wk_start in weeks:
            app.open_retention_details()
            if not _show_week(app.page, wk_start, log=log):
                log(f"  {owner}: could not open week of {wk_start} — skipped")
                continue
            opened += 1
            for i in range(7):
                day = wk_start + dt.timedelta(days=i)
                if day < start or day > end:
                    continue
                try:
                    href = app.detail_href(BOB_ROW, _header(day))
                    if not href:
                        continue
                    for r in app.scrape_at(href, BOB_COLS):
                        name = " ".join(str(x).strip()
                                        for x in r[:2] if str(x).strip())
                        if not name:
                            continue
                        key = name.strip().lower()
                        # EARLIEST wins: a rep who returns did not start again.
                        if key not in found or day < found[key][1]:
                            found[key] = (name, day)
                    # scrape_at navigates AWAY from the report, so the week has
                    # to be re-shown before the next day is looked up.
                    app.open_retention_details()
                    _show_week(app.page, wk_start, log=log)
                except Exception as e:   # noqa: BLE001 — one day is not the run
                    log(f"  {owner} {day}: skipped ({type(e).__name__})")
    # The diagnosis rides the SUMMARY line, because the queue's status view
    # shows only the tail of stdout — the per-week lines were being cut off,
    # which is how "0/5 opened" arrived with no reason attached.
    # The queue's status view shows only the TAIL of stdout, so anything that
    # matters has to be ON the summary line.
    # Only the LANDING goes on the line — the status view truncates it at a
    # fixed width, and the box is already known.
    landed = _LAST_DIAG.get("landed")
    why = ""
    if _LAST_DIAG.get("fields") and opened < len(weeks):
        why = f" · fields: {_LAST_DIAG['fields']}"
    elif _LAST_DIAG.get("headers"):
        why = f" · headers: {_LAST_DIAG['headers']}"
    elif opened < len(weeks) and landed:
        why = f" · {_LAST_DIAG.get('raised', '')} landed: {landed}"
    log(f"  {owner}: {len(found)} start date(s) between {start} and {end} "
        f"— {opened}/{len(weeks)} week(s) opened{why}")
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
