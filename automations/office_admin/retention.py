"""This week's new starts, off ApplicantStream's own Retention Report.

Megan, 2026-11-09: *"you should just look at the retention details report and
not walk the calendar as this would be faster."* She is right — and by a lot.
The calendar walk opens one page per day, seven of them, and the report answers
the same question in two: the report itself, then one detail page.

WHICH ROW. **New Starts Showed Up** (`id=Hired_Showed_Up`). Checked against the
calendar walk on Raf's office for the week of 11/01/2026: both return the SAME
29 people with the same 29 email addresses, nobody extra on either side. That
check is what makes this a swap rather than a change of meaning -- the two were
not assumed to agree, they were compared.

THE WEEKLY TOTAL CELL CARRIES THE WHOLE WEEK. Each day's cell drills to a
single day (`dt=<serial>`), but the Weekly Total cell drills with a RANGE
(`dt=11/08/2026&dt2=11/14/2026`), and its detail page banner reads "For Date:
Sunday, Nov 01, 2026 - Saturday, Nov 07, 2026 | Total Apps: 29". So one detail
page is the week -- which is also where the Sunday-to-Saturday boundary this
board uses comes from ([[reference_appstream_calendar_reads]]).

THE REPORT ONLY EVER RENDERS THE CURRENT WEEK. Its `#weekStart` box is a
readonly datepicker, and `weekStart=` / `dt=` on the URL are ignored -- all
three were tried on 2026-11-09 and every one came back 11/08/2026. That is no
obstacle to the job this serves, which always wants the current week. For any
other week the dates on the weekly-total href are substituted, which is the one
place this builds a URL instead of following one.

WHAT IT WILL NOT DO. Return a half-read week. A report that does not carry the
row, or a detail page that will not load, RAISES -- the caller falls back to the
calendar walk. An empty week is only ever reported when the report says the
count is zero, never when something could not be read
([[feedback_empty_means_proven_zero]]).
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

# The report row that holds the week's new starts, and the row id its drill
# links carry. The LABEL is what is matched on the page; the id is here so the
# next person reading a captured href recognises it.
ROW_LABEL = "New Starts Showed Up"
ROW_ID = "Hired_Showed_Up"

# THE ROW THE BOARD IS SEEDED FROM (Megan, 2026-11-15): *"we would want this
# extension to live off of the applicant stream for that current week that are
# scheduled to start ... when they're brought on board, even though they're
# brought on board Monday, they could have a 2 week out start date. So we want
# to actually see the new starts on our onboarding list because those are the
# ones that are actually starting in the office that week."*
#
# Showing up is a FACT ABOUT A SCHEDULED PERSON, not what puts them on the
# board: seeded from the showed-up row, a row only appeared the morning they
# walked in, which is too late to onboard anybody from. Both rows live on the
# same report and are read the same way, so this is the same two page loads.
SCHEDULED_ROW_LABEL = "Total New Starts Scheduled"
SCHEDULED_STAGE = "Scheduled to start"

# The detail table's own date column: the APPLICATION timestamp.
#
# It was read here as "the day they are due in, which is the board's Start".
# It is not. Probed on 2026-11-22 against both of Raf's funnels for the week
# of 11/22: 29 of 31 rows had the cell EMPTY, and the two with a value read
# '11/03/2026 7:40 AM' and '09/10/2026 2:01 PM' -- when somebody applied,
# months before the week on the banner. Asked for a start day it can only
# ever answer None, which is why all 31 rows on OBCL 11.23 carried
# Start = 11/22.
#
# Still asked for by name, and still kept: where a value DOES fall inside the
# week it is the best thing on the page, and `_day` already refuses anything
# outside it. The day proper comes off the training calendar
# (fdot.week_rows). THE SCHEDULED ROW'S REAL ANSWER IS THE WEEK.
DATE_COLUMN = "Date and Time"

# The detail table's columns, as the page prints them (2026-11-09):
#   '', First Name, Last Name, Email, Phone, Rating, Job Board, Date and Time,
#   Ad (Subject Line), ''
# Read BY HEADER NAME rather than by position -- this table has already gained
# a column (Rating) that the older detail tables in applicantstream.py do not
# have, and the next one would silently shift every field after it.
WANT = ("First Name", "Last Name", "Email", "Phone")

STAGE = "Showed up (first day of training)"


class NotOnTheReport(RuntimeError):
    """The report rendered but carries no such row — fall back to the calendar."""


def _week_href(page, label: str = ROW_LABEL) -> Optional[str]:
    """The weekly-total drill link for one row of the report.

    By ROW LABEL and by the presence of `dt2` (what makes a link a RANGE), not
    by position: the report has sixty-odd rows and gains them.
    """
    return page.evaluate(
        """(label) => {
            const norm = s => (s||'').replace(/\\s+/g,' ').trim().toLowerCase();
            const row = [...document.querySelectorAll('tr')].find(tr => {
                const f = tr.querySelector('td,th');
                return f && norm(f.innerText).startsWith(norm(label));
            });
            if (!row) return null;
            return [...row.querySelectorAll('a')]
                .map(a => a.getAttribute('href'))
                .find(h => h && h.indexOf('dt2=') !== -1) || null;
        }""",
        label,
    )


def _rendered_week(page) -> Optional[dt.date]:
    """The Sunday the report is actually showing, read off the page."""
    got = page.evaluate(
        "() => (document.body.innerText.match(/(\\d{2}\\/\\d{2}\\/\\d{4}) (\\d{2}\\/\\d{2}\\/\\d{4})/)||[])[1] || ''")
    try:
        return dt.datetime.strptime(got, "%m/%d/%Y").date()
    except (ValueError, TypeError):
        return None


def _retarget(href: str, week_start: dt.date) -> str:
    """Point a weekly-total href at a different week.

    The ONLY URL this builds, and only because the report refuses to render any
    week but the current one. Both dates are replaced together: a href with a
    start from one week and an end from another would quietly return a mixture.
    """
    end = week_start + dt.timedelta(days=6)
    href = re.sub(r"([?&]dt=)[^&]*", r"\g<1>" + week_start.strftime("%m/%d/%Y"), href)
    href = re.sub(r"([?&]dt2=)[^&]*", r"\g<1>" + end.strftime("%m/%d/%Y"), href)
    return href


def _detail_rows(app, want=WANT) -> List[Dict]:
    """The loaded detail page's table, as {header: value} per row."""
    got = app.page.evaluate(
        """() => {
            const ts = [...document.querySelectorAll('table')];
            let best = null, n = 0;
            ts.forEach(t => { const r = t.querySelectorAll('tr').length;
                              if (r > n) { n = r; best = t; } });
            if (!best) return null;
            const trs = [...best.querySelectorAll('tr')];
            const head = [...trs[0].children].map(c => c.innerText.trim());
            const rows = [];
            for (let i = 1; i < trs.length; i++) {
                const tds = [...trs[i].querySelectorAll('td')];
                if (!tds.length) continue;
                const o = {};
                head.forEach((h, j) => { if (h) o[h] = (tds[j] ? tds[j].innerText.trim() : ''); });
                if (Object.values(o).some(v => v)) rows.push(o);
            }
            return {head: head, rows: rows,
                    banner: (document.body.innerText.match(/For Date[^\\n]*/) || [''])[0]};
        }"""
    )
    if not got:
        raise RuntimeError("the detail page rendered no table")
    missing = [c for c in want if c not in got["head"]]
    if missing:
        raise RuntimeError(
            "the detail table has no %s column (it has: %s). It was renamed or "
            "this is the wrong page — refusing to guess at a position."
            % (", ".join(missing), ", ".join(h for h in got["head"] if h)))
    return got["rows"]


def _day(text, week_start: Optional[dt.date]) -> Optional[dt.date]:
    """The date in a detail row's date cell, when it is a day of that week.

    A cell that will not parse, or parses to a day outside the week asked for,
    answers None -- and None means the row falls back to the week's Sunday,
    which is what every retention-seeded row already carries. It never invents
    a day: a wrong Start on a row somebody onboards from is worse than a vague
    one, and this is reported as a count rather than passed off as read.
    """
    got = " ".join(str(text or "").split())
    if not got:
        return None
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", got)
    if not m:
        return None
    mm, dd, yy = (int(x) for x in m.groups())
    if yy < 100:
        yy += 2000
    try:
        day = dt.date(yy, mm, dd)
    except ValueError:
        return None
    if week_start is not None and not (
            week_start <= day <= week_start + dt.timedelta(days=6)):
        return None
    return day


def _as_people(rows: List[Dict], *, stage: str = STAGE,
               week_start: Optional[dt.date] = None,
               dated: bool = False) -> List[Dict]:
    """The same shape `fdot.showed_up` returns, de-duplicated the same way.

    Deliberately identical: the seed does not know or care which reader filled
    it, and the day the two disagree about a field is the day one of them starts
    seeding a different person.

    With `dated`, each person also carries the day they are due in, read off
    the detail table's own date column.
    """
    out, seen = [], set()
    for r in rows:
        first = str(r.get("First Name") or "").strip()
        last = str(r.get("Last Name") or "").strip()
        if not first:
            continue
        email = str(r.get("Email") or "").strip()
        phone = re.sub(r"\D", "", str(r.get("Phone") or ""))[-10:]
        key = email.lower() or (first.lower(), last.lower(), phone)
        if key in seen:
            continue
        seen.add(key)
        row = {"first_name": first, "last_name": last, "email": email,
               "phone": phone, "stage": stage}
        if dated:
            day = _day(r.get(DATE_COLUMN), week_start)
            if day is not None:
                row["started"] = day
        out.append(row)
    return out


def read_week(app, office_id: str, week_start: dt.date, log=print, *,
              row_label: str = ROW_LABEL, stage: str = STAGE,
              dated: bool = False) -> List[Dict]:
    """One row of this week's Retention Report — two page loads, not seven.

    `app` is an applicant_tracker ApplicantStream session, already on the
    office. Raises if the report cannot be read; the caller falls back to the
    calendar walk rather than treating an unread week as an empty one.

    `row_label` picks WHICH question is being asked. The default is who showed
    up; `read_scheduled_week` asks who is due in. They are different questions
    and must never stand in for one another -- see `SCHEDULED_ROW_LABEL`.
    """
    from automations.icd_onboarding.board import week_start_of

    want = week_start_of(week_start)
    app.open_retention_details()
    href = _week_href(app.page, row_label)
    if not href:
        raise NotOnTheReport(
            "%s has no %r row on the Retention Report" % (office_id, row_label))

    shown = _rendered_week(app.page)
    if shown != want:
        # The report will not be moved (its week box is readonly and the URL
        # parameters are ignored), so the DETAIL link is retargeted instead.
        log("  retention: report is showing %s, asking the detail page for %s"
            % (shown or "?", want))
        href = _retarget(href, want)

    app._goto_detail(href)
    rows = _detail_rows(app, WANT + ((DATE_COLUMN,) if dated else ()))
    people = _as_people(rows, stage=stage, week_start=want, dated=dated)
    log("  week of %s: %d %s (Retention Report)"
        % (want, len(people), row_label))
    if dated:
        vague = [p for p in people if not p.get("started")]
        if vague:
            # SAID, never swallowed: those rows take the week's Sunday as their
            # Start, which is a vaguer answer than the page was asked for.
            #
            # NOT "no readable date", which is what this said until 2026-11-22
            # and which blamed the page for a column it never carried. Read
            # that day: 29 of 31 rows had this cell EMPTY, and the two that
            # had one read 11/03 and 09/10 -- the APPLICATION timestamp,
            # months before the week asked for. It is not a start date and
            # never was, so a run where every row is "vague" is the ordinary
            # case, not a fault to go chasing. The day comes off the training
            # calendar (fdot.week_rows); this row gives the week.
            log("    %d of %d carry no start day here (this column is the "
                "apply date) — the week's %s stands in until the training "
                "calendar names their day"
                % (len(vague), len(people), want.strftime("%m/%d/%Y")))
    return people


def read_scheduled_week(app, office_id: str, week_start: dt.date,
                        log=print) -> List[Dict]:
    """Who is SCHEDULED to start in the office that week, with each day.

    What the onboarding board is seeded from. NOT interchangeable with
    `read_week`: if this row cannot be read, the caller reports that and seeds
    nothing, because seeding the showed-up answer instead would quietly put a
    different question's people on the board
    ([[feedback_empty_means_proven_zero]]).
    """
    return read_week(app, office_id, week_start, log,
                     row_label=SCHEDULED_ROW_LABEL, stage=SCHEDULED_STAGE,
                     dated=True)
