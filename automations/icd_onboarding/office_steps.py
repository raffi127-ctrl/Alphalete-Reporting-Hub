"""Which onboarding steps an office actually does.

Megan, 2026-11-09: *"we need to ask them if they have blue ink on the
enrollment because if they don't then they can't enroll in apex and so we would
skip that part."*

APEX GENUINELY CANNOT RUN WITHOUT BLUE INK, and not as a matter of policy:
`apex_new_starts.eco_run.plan` reads each person's DOB, address, city and zip
OUT OF THE SIGNED PACKET, and anybody without one is blocked with "no signed
Blue Ink packet — type this one by hand". An office with no Blue Ink would have
every person blocked, every week, for ever.

WHY A BOARD NEEDS TO KNOW. Those two columns would otherwise sit empty on every
row, so the office would read as permanently behind, the printed sheet would
count boxes nobody can ever tick, and the chase list would name work that does
not exist. A step an office does not do is not an outstanding step.

HOW IT IS MARKED: the cells are written `n/a` when the week is seeded. That
needs no new idea anywhere else -- `remaining()` already counts any non-empty
cell as answered, `write_step` already refuses to overwrite one, and the
printed grid already shows a cell's text when it is not a date. An office that
later gets Blue Ink has those cells cleared and everything resumes.

UNKNOWN IS NOT NO. An office nobody has asked yet returns None, and nothing is
marked -- the columns stay open and the usual sources fill them if they can.
Marking an unasked office `n/a` would quietly switch off a step that works.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

# The Office Settings column holding the answer, and what counts as one.
TAB = "Office Settings"
COL_OFFICE = "Office"
COL_BLUEINK = "Blue Ink"
COL_RATE = "Rate of Pay"

YES = {"yes", "y", "true", "1", "on"}
NO = {"no", "n", "false", "0", "off", "none"}

# What an office without Blue Ink does not do. Apex is here because its data
# comes out of the packet; Blue Ink is here because there is no account.
WITHOUT_BLUEINK: Sequence[str] = ("Blue Ink", "Added to APEX")

# What goes in the cell. Short, obvious on a printed sheet, and not a date --
# so `cell_text` prints it as itself rather than turning it into a tick.
NOT_APPLICABLE = "n/a"


def _rows(book=None) -> List[Dict[str, str]]:
    """Office Settings as {header: value}. [] when it cannot be read.

    BY HEADER: that tab gained an `Owner` column from another session on
    2026-11-06 and a positional read returned the wrong cell in silence
    ([[feedback_no_hardcoded_columns]]).
    """
    try:
        if book is None:
            from automations.icd_alerts import post as P
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        grid = book.worksheet(TAB).get_all_values()
    except Exception:          # noqa: BLE001
        return []
    if not grid:
        return []
    head = [str(h).strip() for h in grid[0]]
    return [{h: (r[i].strip() if i < len(r) else "")
             for i, h in enumerate(head) if h} for r in grid[1:]]


def uses_blueink(office_key: str, book=None) -> Optional[bool]:
    """True / False / None for "does this office have Blue Ink?".

    None means NOBODY HAS ASKED, which is not the same as no.
    """
    key = str(office_key or "").strip().lower()
    if not key:
        return None
    # Alphalete's own account is the one every other part of this was built on.
    if key == "raf":
        return True
    for r in _rows(book):
        if r.get(COL_OFFICE, "").strip().lower() != key:
            continue
        said = r.get(COL_BLUEINK, "").strip().lower()
        if said in YES:
            return True
        if said in NO:
            return False
        return None
    return None


def rate_of_pay(office_key: str, book=None) -> Optional[str]:
    """What this office pays per hour, or None when nobody has said.

    Megan, 2026-11-12, after Apex refused the first completed record: *"Rate
    of pay is something that we should ask the ICD upon enrollment, by the
    way, to make sure we're putting the right information for their office
    here."*

    APEX WILL NOT SAVE WITHOUT IT -- the first supervised run filled every
    other box correctly and still bounced on "Rate of Pay is required".

    NONE IS NOT A DEFAULT. $10.00 is what Alphalete pays, and it reached the
    code as a constant; another office's rate is their own, like their address
    and their pay facts. An office nobody has asked returns None and the
    person is held back and named, because a wrong rate lands on a real
    payroll record and nobody would see it was wrong.
    """
    key = str(office_key or "").strip().lower()
    if not key:
        return None
    for r in _rows(book):
        if r.get(COL_OFFICE, "").strip().lower() != key:
            continue
        said = str(r.get(COL_RATE, "")).strip().lstrip("$").strip()
        if not said:
            return None
        try:
            return "%.2f" % float(said)
        except ValueError:
            # Words in a money column: say nothing rather than type them in.
            return None
    return None


def skipped_for(office_key: str, book=None) -> Sequence[str]:
    """The steps this office does not do. () when it does them all, and ()
    when nobody has asked -- an unasked office keeps every column open."""
    return () if uses_blueink(office_key, book) is not False else WITHOUT_BLUEINK


def save_blueink(office_key: str, has_it: bool, book=None, log=print) -> bool:
    """Record the answer on Office Settings. Adds the column if it is new."""
    key = str(office_key or "").strip().lower()
    if not key:
        return False
    try:
        if book is None:
            from automations.icd_alerts import post as P
            from automations.recruiting_report.fill import open_by_key
            book = open_by_key(P.RELAY_SPREADSHEET_ID)
        ws = book.worksheet(TAB)
        grid = ws.get_all_values()
    except Exception as e:     # noqa: BLE001
        log("  office settings not readable: %s" % type(e).__name__)
        return False
    if not grid:
        return False
    head = [str(h).strip() for h in grid[0]]
    if COL_BLUEINK not in head:
        head.append(COL_BLUEINK)
        ws.update_cell(1, len(head), COL_BLUEINK)
    at = next((i for i, r in enumerate(grid[1:], start=2)
               if r and r[0].strip().lower() == key), None)
    if at is None:
        at = len(grid) + 1
        ws.update_cell(at, head.index(COL_OFFICE) + 1, key)
    ws.update_cell(at, head.index(COL_BLUEINK) + 1, "yes" if has_it else "no")
    log("  %s: Blue Ink = %s" % (key, "yes" if has_it else "no"))
    return True


def mark_not_applicable(office_key, week_start, *, dry_run: bool = True,
                        log=print) -> int:
    """Write `n/a` into the steps this office does not do, for one week.

    Only ever fills an EMPTY cell -- `write_step` sees to that -- so a step
    somebody has already earned is never overwritten by a later answer.
    """
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import fillers as F
    from automations.icd_onboarding import sheet as S

    steps = skipped_for(office_key)
    if not steps:
        return 0
    ws = S.open_board(F.workbook_for(office_key), create=False)
    if ws is None:
        return 0
    rows = B.for_week(S.rows_of(ws.get_all_values()), week_start)
    names = [("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
             for r in rows if r.get("Name") or r.get("Last Name")]
    if not names:
        return 0
    log("  %s does not use Blue Ink — marking %s n/a for %d people"
        % (office_key, " and ".join(steps), len(names)))
    if dry_run:
        return 0
    book = F.workbook_for(office_key)
    n = 0
    for column in steps:
        n += S.write_step(book, week_start, column,
                          {name: NOT_APPLICABLE for name in names},
                          dry_run=False, log=lambda *a: None, ws=ws)
    return n
