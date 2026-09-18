"""Columns C, D and E, per office and per day, from ApplicantStream.

Reports -> Retention Details, the selected day's column. Three rows of that
report, already mapped in fetch_office.METRICS:

    C  1st interviews showed up            'First Interviews Showed Up'
    D  1st showed up booked 2nd            'First Showed Up Booked Second'
    E  Retention first showed up booked    'Retention First Showed Up Booked
       second                               Second'

D IS NOT 'Total Second Interviews'. That was the first mapping and it is wrong:
that row counts every second interview booked on the day, including people whose
first round was on an earlier day, so it came out LARGER than C for several
offices (JC Pascual 8 vs 9, Ryan McSpadden 12 vs 18) and never reconciled with
E. The report has a row that is literally the numerator of E, sitting directly
above it. Checked on office 22177, Thursday 2026-09-17:
    First Interviews Showed Up              28
    First Showed Up Booked Second           11      <- D
    Retention First Showed Up Booked Second 39%     <- 11/28, so E = D/C

These are NOT derived from the ARS REPORT workbooks. Q+Di+De happens to equal
the '1st interviews showed up' Eve typed into her sample row, and Booked happens
to equal her '1st showed up booked 2nd', but she filled that row IN BY HAND as
an example -- the agreement is a coincidence, not a rule, and this report is an
alert that has to reflect the live number twice a day (Eve, 2026-09-17).

WEEK ANCHOR: AppStream takes the Sunday that STARTS the week, which is exactly
how 'Interviewers Retention (Interviewer)' labels its blocks -- '9/13' goes
through unchanged. (It is the ARS REPORT files that are seven days ahead.)

PERCENTS COME BACK AS WHOLE NUMBERS: fetch_office parses '44%' to 44, so the
value is divided by 100 before it reaches a Sheet cell that is formatted as a
percent. Writing 44 into a percent cell would read as 4400%.

THE SESSION IS THE EXPENSIVE PART: one login, then one office switch per owner.
Everything runs inside a single `appstream_direct_session`, the same way the
Daily Focus fill does, and the whole week is pulled in that one pass so both of
the day's runs cost the same as one.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.first_to_second_below_mark import ars_reports as ars

REPO_ROOT = Path(__file__).resolve().parents[2]
RECRUITING = REPO_ROOT / "automations" / "recruiting_report"

# Owner name (as the retention tab writes it) -> AppStream office id, for the
# owners the shared office lists do not reach under that spelling.
OFFICE_ALIASES = Path(__file__).resolve().parent / "owner-office-ids.json"

# The numerator row is not in fetch_office.METRICS -- the reports that map was
# built for never needed it. Registered here at import time rather than edited
# into the shared file, the same way recruiter_retention/daily.py adds the row
# the weekly report ignores. setdefault, so it never overrides a real entry.
FIRST_SHOWED_BOOKED_2ND = "first_showed_booked_2nd"


def _register_metric() -> None:
    from automations.recruiting_report import fetch_office
    fetch_office.METRICS.setdefault(
        FIRST_SHOWED_BOOKED_2ND,
        {"as_label": "First Showed Up Booked Second", "type": "count"})


# fetch_office metric key -> the column it fills on the tab.
METRIC_TO_FIELD = {
    "first_showed": "first_showed",                     # C
    FIRST_SHOWED_BOOKED_2ND: "booked_2nd",              # D
    "pct_first_showed_booked_2nd": "retention",         # E
}
PERCENT_METRICS = {"pct_first_showed_booked_2nd"}


def week_start_for(label: str, year_hint: Optional[int] = None) -> dt.date:
    """'9/13' -> date(2026, 9, 13), the Sunday AppStream wants.

    The retention tab writes M/D with no year, so the year is inferred: the
    block is the most recent one that is not in the future."""
    m = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})", label or "")
    if not m:
        raise ValueError(f"cannot read a date out of week label {label!r}")
    month, day = int(m.group(1)), int(m.group(2))
    today = dt.date.today()
    year = year_hint or today.year
    try:
        d = dt.date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"bad week label {label!r}: {exc}") from exc
    if year_hint is None and d > today + dt.timedelta(days=6):
        d = dt.date(year - 1, month, day)
    return d


def current_week_start(today: Optional[dt.date] = None) -> dt.date:
    """The Sunday that starts this week -- the same arithmetic daily_focus uses."""
    d = today or dt.date.today()
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


# ------------------------------------------------------------- office lookup
def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_office_aliases() -> Dict[str, str]:
    data = _load_json(OFFICE_ALIASES)
    return {k: str(v) for k, v in data.items() if not k.startswith("_")}


def build_office_index() -> Dict[str, Tuple[str, str]]:
    """{normalised owner name: (office_id, the name that matched)}.

    Three sources, most specific first: this module's own alias file, the
    committed ICD->office overrides, then the all-offices snapshot. That
    snapshot is a CACHE and goes stale, so a miss here is reported rather than
    guessed at."""
    index: Dict[str, Tuple[str, str]] = {}
    snapshot = _load_json(RECRUITING / "all-offices.json") or {}
    for office in snapshot.get("offices", []):
        oid, owner = office.get("office_id"), office.get("owner")
        if oid and owner:
            index.setdefault(ars._key(owner), (str(oid), owner))
    for name, oid in (_load_json(RECRUITING / "icd_office_mappings.json") or {}).items():
        if oid and str(oid) != "__SKIP__":
            index[ars._key(name)] = (str(oid), name)
    for name, oid in load_office_aliases().items():
        index[ars._key(name)] = (str(oid), name)
    return index


def resolve_office(owner: str, index: Dict[str, Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    """(office_id, matched name) for an owner, or None.

    Exact spelling only, plus the alias file. No fuzzy fallback on purpose: the
    office id decides WHOSE numbers land in the row, and 'Jose Velasquez' vs
    'Jose Antonio Chavez' are one bad guess apart."""
    return index.get(ars._key(owner))


# ------------------------------------------------------------------ the pull
def fetch_days(owners: List[str], week_label: str, day: str, *,
               logfn=print) -> Tuple[Dict[str, Dict[str, Optional[float]]], List[str]]:
    """{owner: {field: value}} for one day, plus the list of owners we could not pull.

    One AppStream login for the whole sweep. Values are already scaled: counts
    are ints, the retention is a fraction ready for a percent-formatted cell.
    """
    from automations.recruiting_report import fetch_office
    from automations.shared.tableau_patchright import appstream_direct_session

    _register_metric()
    index = build_office_index()
    targets: List[Tuple[str, str, str]] = []
    gaps: List[str] = []
    for owner in owners:
        hit = resolve_office(owner, index)
        if hit is None:
            gaps.append(f"{owner}: no AppStream office id")
            continue
        targets.append((owner, hit[0], hit[1]))

    week_start = week_start_for(week_label)
    key = day.strip().lower()
    logfn(f"  AppStream: {len(targets)} offices, week starting {week_start}, {day}")

    out: Dict[str, Dict[str, Optional[float]]] = {}
    with appstream_direct_session(verbose=False) as page:
        for owner, office_id, hint in targets:
            try:
                raw = fetch_office.fetch_one_daily(page, office_id, hint, week_start)
            except Exception as exc:                      # noqa: BLE001
                gaps.append(f"{owner} (office {office_id}): {type(exc).__name__}: {exc}")
                continue
            if not raw:
                # fetch_one_daily returns {} only on a CONFIRMED access denial.
                gaps.append(f"{owner} (office {office_id}): no AppStream access")
                continue
            row: Dict[str, Optional[float]] = {}
            for metric, field in METRIC_TO_FIELD.items():
                value = (raw.get(metric) or {}).get(key)
                if value is None:
                    row[field] = None
                elif metric in PERCENT_METRICS:
                    row[field] = value / 100.0      # '44%' arrives as 44
                else:
                    row[field] = value
            out[owner] = row
    return out, gaps


def fetch_weeks(owner_weeks: Dict[str, List[str]], *, logfn=print
                ) -> Tuple[Dict[str, Dict[str, Dict[str, Dict[str, Optional[float]]]]], List[str]]:
    """Every day of several weeks at once, for the two-week board.

    owner_weeks: {owner: [week label, ...]} -- last week's roster is not always
    this week's, so each owner is pulled only for the weeks they are on.

    Returns ({week label: {day: {owner: {field: value}}}}, gaps).

    ONE office switch per owner, then one week submit per week: the switch is
    the slow part, and the Retention Details page answers a second week on the
    same office without it. Re-pulling the days that already happened is the
    point -- an applicant who calls back on Friday moves Monday's number, and
    the board has to show the number as it stands now, not as it stood then.
    """
    from automations.recruiting_report import fetch_office
    from automations.shared.tableau_patchright import appstream_direct_session

    _register_metric()
    index = build_office_index()
    targets: List[Tuple[str, str, str, List[str]]] = []
    gaps: List[str] = []
    for owner, weeks in owner_weeks.items():
        hit = resolve_office(owner, index)
        if hit is None:
            gaps.append(f"{owner}: no AppStream office id")
            continue
        targets.append((owner, hit[0], hit[1], list(weeks)))

    all_weeks = sorted({w for _, _, _, ws in targets for w in ws})
    logfn(f"  AppStream: {len(targets)} offices, weeks {', '.join(all_weeks)}")

    out: Dict[str, Dict[str, Dict[str, Dict[str, Optional[float]]]]] = {}
    with appstream_direct_session(verbose=False) as page:
        for owner, office_id, hint, weeks in targets:
            try:
                if not fetch_office._switch_office(page, office_id, hint,
                                                   confirm_denial=True):
                    gaps.append(f"{owner} (office {office_id}): no AppStream access")
                    continue
                fetch_office._ensure_on_retention_report(page)
            except Exception as exc:                      # noqa: BLE001
                gaps.append(f"{owner} (office {office_id}): {type(exc).__name__}: {exc}")
                continue
            for wk in weeks:
                try:
                    fetch_office._set_week_and_submit(page, week_start_for(wk))
                    page.wait_for_timeout(500)
                    raw = fetch_office._scrape_metrics_per_day(page)
                except Exception as exc:                  # noqa: BLE001
                    gaps.append(f"{owner} (office {office_id}, week {wk}): "
                                f"{type(exc).__name__}: {exc}")
                    continue
                for day in ars.DAYS:
                    key = day.lower()
                    row: Dict[str, Optional[float]] = {}
                    for metric, field in METRIC_TO_FIELD.items():
                        value = (raw.get(metric) or {}).get(key)
                        if value is None:
                            row[field] = None
                        elif metric in PERCENT_METRICS:
                            row[field] = value / 100.0      # '44%' arrives as 44
                        else:
                            row[field] = value
                    out.setdefault(wk, {}).setdefault(day, {})[owner] = row
    return out, gaps
