"""Write terminations into the 'Terminated Reps' tab.

Workbook: 'All in One Local Office - Raf'
(1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4), tab 'Terminated Reps'.

  A Rep Name    B Lead Rep    C # Days Worked   D Termination Date WE
  E Ownerville  F Slack Deact G Notes           H Year

TWO THINGS ABOUT THIS TAB SHAPE THE WRITE:

1. IT IS NOT AN EMPTY APPEND TARGET. Thousands of rows BELOW the last name are
   already seeded with unticked Ownerville / Slack Deact checkboxes and the
   Year — gspread's append_row would jump past all of them and land at row
   ~2689, orphaning the seeded formatting and leaving a 300-row hole. So we
   find the first row whose Rep Name is EMPTY and write there.

2. Ownerville and Slack Deact ARE NOT OURS TO SET. They record that a human
   went and deactivated the accounts; a bot ticking them would assert work
   nobody did. We write A:D (+ H when the seeded Year is missing) and never
   touch E, F or G. [[don't touch user data without confirming]]

Dedupe is on (folded name, termination date), not name alone: the same person
can legitimately hold two rows — Myra Singleton is in there twice, terminated
7/31 and again 8/3 after a rehire.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from automations.recruiting_report.fill import open_by_key
from automations.terminated_reps.board import Termination, norm_name, to_date

TRACKER_SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "Terminated Reps"

# Every 2026 row on the tab is 'Raf' (813 of them) or the historical 'Hogue'
# split. This office is the only one we file, so the value is constant —
# confirmed by Eve: "Rafael siempre porque no hacemos otra oficina".
LEAD_REP = "Raf"

HEADERS = ["Rep Name", "Lead Rep", "# Days Worked", "Termination Date WE",
           "Ownerville", "Slack Deact", "Notes", "Year"]

COL_NAME, COL_LEAD, COL_DAYS, COL_DATE = 1, 2, 3, 4
COL_YEAR = 8


class TrackerError(RuntimeError):
    pass


@dataclass
class AppendResult:
    added: list[Termination]
    skipped: list[Termination]        # already on the tab
    first_row: int | None
    tab_url: str
    dry_run: bool


def _open(sheet_id: str = TRACKER_SHEET_ID, tab: str = TAB):
    sh = open_by_key(sheet_id)
    try:
        ws = next(w for w in sh.worksheets() if w.title.strip().lower() == tab.lower())
    except StopIteration:
        raise TrackerError(
            f"No {tab!r} tab in workbook {sheet_id}. Tabs: "
            f"{', '.join(w.title for w in sh.worksheets())}") from None
    return sh, ws


def _check_headers(grid: list) -> None:
    """Refuse to write into a tab whose columns have moved. Cheap insurance:
    the whole write is positional A:D, so a reordered header would file days
    worked under 'Lead Rep' with no error at all."""
    row = [str(v or "").strip().lower() for v in (grid[0] if grid else [])]
    want = [h.lower() for h in HEADERS]
    if row[:len(want)] != want:
        raise TrackerError(
            f"{TAB!r} header row changed — expected {HEADERS}, found "
            f"{row[:len(HEADERS)]}. Fix the mapping before writing.")


def existing_keys(grid: list) -> set:
    """Every (folded name, date) already filed."""
    out = set()
    for r in grid[1:]:
        name = str(r[COL_NAME - 1] or "").strip() if len(r) >= COL_NAME else ""
        if not name:
            continue
        d = to_date(r[COL_DATE - 1]) if len(r) >= COL_DATE else None
        if d:
            out.add((norm_name(name), d))
    return out


def first_free_row(grid: list) -> int:
    """The row just past the LAST filled Rep Name.

    Scanned from the BOTTOM, not the top, and that is the whole point: row 1979
    of the live tab is a hole — a name someone cleared, leaving the termination
    date behind. Taking the FIRST empty name would append into the middle of
    2024's history there and overwrite the leftover date, while the 400 real
    rows below it stayed put. Appending strictly after the last name means a
    hole is left alone (it's Eve's to fix, not ours to fill)."""
    for i in range(len(grid), 1, -1):
        r = grid[i - 1]
        if str(r[COL_NAME - 1] or "").strip() if len(r) >= COL_NAME else "":
            return i + 1
    return 2


def append(rows: list[Termination], *, sheet_id: str = TRACKER_SHEET_ID,
           tab: str = TAB, dry_run: bool = True, logfn=print) -> AppendResult:
    """File the terminations that aren't on the tab yet. Returns what was
    added (in tab order) so the Slack post reports exactly what changed."""
    sh, ws = _open(sheet_id, tab)
    grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    _check_headers(grid)
    have = existing_keys(grid)

    added, skipped, seen = [], [], set()
    for t in rows:
        if t.key in have or t.key in seen:
            skipped.append(t)
            continue
        seen.add(t.key)
        added.append(t)

    start = first_free_row(grid)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={ws.id}"
    if not added:
        logfn(f"  nothing new — {len(skipped)} already on {tab!r}")
        return AppendResult([], skipped, None, url, dry_run)

    body = [[t.name, LEAD_REP,
             "" if t.days_worked is None else t.days_worked,
             f"{t.term_date.month}/{t.term_date.day}/{t.term_date.year}"]
            for t in added]
    end = start + len(added) - 1

    # Only fill Year where the seeded value is missing — writing the whole
    # column back would rewrite rows we otherwise leave alone.
    years = []
    for i, t in enumerate(added):
        r = start + i
        seeded = (grid[r - 1][COL_YEAR - 1]
                  if r - 1 < len(grid) and len(grid[r - 1]) >= COL_YEAR else "")
        years.append([t.term_date.year] if str(seeded).strip() == "" else [seeded])

    logfn(f"  {'DRY-RUN — would write' if dry_run else 'writing'} "
          f"{len(added)} row(s) into {tab!r} A{start}:D{end}")
    for t in added:
        logfn(f"     {t.term_date.isoformat()}  {t.name}  "
              f"{'' if t.days_worked is None else str(t.days_worked) + 'd'}  "
              f"({t.source}, {t.tab} row {t.row})")
    if skipped:
        logfn(f"  ({len(skipped)} already filed — skipped)")

    if not dry_run:
        # USER_ENTERED so the date lands as a real date, matching the serials
        # already in column D.
        ws.update(body, f"A{start}:D{end}", value_input_option="USER_ENTERED")
        ws.update(years, f"H{start}:H{end}", value_input_option="USER_ENTERED")
    return AppendResult(added, skipped, start, url, dry_run)
