"""The 'Mobrium List' tab: read it, and apply a plan to it.

Workbook: 'All in One Local Office - Raf'
(1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4), tab 'Mobrium List' — the same
workbook 'Terminated Reps' lives in.

  A First Name    B Last Name    C Emails    D Phone

Four columns, one header row, ~51 people, and nothing else on the tab. It is a
CURATED list, not a roster: OwnerVille has 420 active reps and only 51 of them
are here, so this module only ever removes the terminated and adds the week's
new starts. It never syncs the tab to anything.

THE TAB IS SORTED BY FIRST NAME, THEN LAST NAME (Eve's rule, 2026-08-14), so an
append would visibly break it. New people are INSERTED at their alphabetical
position. If the tab is found out of order, insertion can't place anyone
sensibly, so those go at the bottom — and then `sort_rows` puts the whole tab
back in order as the last step of the run. That final sort is what makes the
rule hold even after someone types a row in by hand.

WRITES ARE ROW OPERATIONS, NOT A REWRITE — except the closing sort, which moves
whole A:D tuples and so still leaves each cell's own value untouched. That
matters because column D holds phone numbers typed in two different styles that
somebody chose.

THREE OPERATIONS, IN A FIXED ORDER: fills, then deletions, then insertions.
Fills and deletions both address the grid AS READ, so the fills have to happen
while those row numbers are still true; insertions address the finished tab and
therefore go last.

THE OTHER TWO RUN IN OPPOSITE DIRECTIONS, and that is not an accident:

  * Deletions go BOTTOM-UP. Their rows are indices into the grid as READ, so
    deleting the lowest first would shift every remaining target up by one.
  * Insertions go TOP-DOWN. Their rows are indices into the FINISHED tab —
    `plan.place` folds each new person into its projection before placing the
    next — so each insert is only correct once the ones above it have happened.

Getting the second one backwards is silent: the counts come out right, every
name is present, and each new person simply sits one row below where they
belong. It cost a sandbox run to spot.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from automations.recruiting_report.fill import open_by_key
from automations.mobrium_list.ownerville import norm_name

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
TAB = "Mobrium List"

HEADERS = ["First Name", "Last Name", "Emails", "Phone"]
COL_FIRST, COL_LAST, COL_EMAIL, COL_PHONE = 1, 2, 3, 4


class SheetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    """One person on the list."""
    row: int
    first: str
    last: str
    email: str
    phone: str

    @property
    def full(self) -> str:
        return f"{self.first} {self.last}".strip()

    @property
    def key(self) -> str:
        return norm_name(self.full)

    @property
    def sort_key(self) -> Tuple[str, str]:
        """FIRST NAME, THEN LAST NAME — Eve's rule, 2026-08-14.

        The tab used to be kept on the first name alone, because that is how it
        happened to be ordered ('Jennifer Nzekwe' sat above 'Jennifer Medina')
        and a two-level key read the whole tab as unsorted on that one pair.
        The tab is now sorted on both levels and `run.py` re-sorts it on every
        pass, so the key and the tab agree.
        """
        return (self.first.strip().lower(), self.last.strip().lower())

    def values(self) -> list:
        return [self.first, self.last, self.email, self.phone]


def open_tab(sheet_id: str = SHEET_ID, tab: str = TAB):
    sh = open_by_key(sheet_id)
    try:
        ws = next(w for w in sh.worksheets()
                  if w.title.strip().lower() == tab.lower())
    except StopIteration:
        raise SheetError(
            f"No {tab!r} tab in workbook {sheet_id}. Tabs: "
            f"{', '.join(w.title for w in sh.worksheets())}") from None
    return sh, ws


def _check_headers(grid: list) -> None:
    """Refuse to write into a tab whose columns moved. The whole write is
    positional A:D, so a reordered header would file phone numbers under
    'Emails' without erroring at all."""
    row = [str(v or "").strip().lower() for v in (grid[0] if grid else [])]
    want = [h.lower() for h in HEADERS]
    if row[:len(want)] != want:
        raise SheetError(
            f"{TAB!r} header row changed — expected {HEADERS}, found "
            f"{row[:len(HEADERS)]}. Fix the mapping before writing.")


def read(sheet_id: str = SHEET_ID, tab: str = TAB) -> Tuple[List[Entry], object]:
    """Everyone on the tab, in tab order, plus the worksheet handle."""
    _sh, ws = open_tab(sheet_id, tab)
    grid = ws.get_values(value_render_option="UNFORMATTED_VALUE")
    _check_headers(grid)
    entries = []
    for i, raw in enumerate(grid[1:], 2):
        row = list(raw) + [""] * 4
        first, last = str(row[0] or "").strip(), str(row[1] or "").strip()
        if not first and not last:
            continue
        entries.append(Entry(row=i, first=first, last=last,
                             email=str(row[2] or "").strip(),
                             phone=str(row[3] or "").strip()))
    return entries, ws


def is_sorted(entries: List[Entry]) -> bool:
    keys = [e.sort_key for e in entries]
    return keys == sorted(keys)


def insert_position(entries: List[Entry], first: str, last: str) -> int:
    """The 1-indexed sheet row a new person belongs on, keeping (first, last)
    order. An exact name-twin of someone already there lands AFTER them (strict
    `<`), which is where an eye would put them. Falls to just past the last
    entry when they sort last."""
    key = (first.strip().lower(), last.strip().lower())
    for e in entries:
        if key < e.sort_key:
            return e.row
    return (entries[-1].row + 1) if entries else 2


def tab_url(ws) -> str:
    return (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
            f"/edit#gid={ws.id}")


def apply(ws, *, removals: List[Entry], additions: List[Tuple[int, list]],
          fills: Optional[List[Tuple[int, str, str]]] = None,
          dry_run: bool = True, logfn=print) -> None:
    """Fill, delete, insert. `fills` is [(row, email, phone)] where an empty
    string means "leave that cell alone". See the module docstring for the
    ordering rules.
    """
    if dry_run:
        logfn("  (dry run — the tab is not touched)")
        return

    for row, email, phone in (fills or ()):
        # One cell at a time: writing C:D as a range would blank whichever of
        # the two we don't have a value for.
        if email:
            ws.update_acell(f"C{row}", email)
        if phone:
            ws.update_acell(f"D{row}", phone)
        logfn(f"  filled row {row}: "
              + ", ".join(f"{c}={v}" for c, v in (("email", email),
                                                  ("phone", phone)) if v))

    # Delete bottom-up, collapsing runs of adjacent rows into one call.
    rows = sorted({e.row for e in removals}, reverse=True)
    blocks: List[Tuple[int, int]] = []
    for r in rows:
        if blocks and blocks[-1][0] == r + 1:
            blocks[-1] = (r, blocks[-1][1])
        else:
            blocks.append((r, r))
    for start, end in blocks:
        ws.delete_rows(start, end)
        logfn(f"  deleted row(s) {start}"
              f"{'' if start == end else f'-{end}'}")

    for row, values in sorted(additions, key=lambda x: x[0]):
        ws.insert_row(values, index=row, value_input_option="USER_ENTERED")
        logfn(f"  inserted at row {row}: {values[0]} {values[1]}")


def sort_rows(ws, entries: List[Entry], *, dry_run: bool = True,
              logfn=print) -> int:
    """Put the tab in (first, last) order. Returns how many rows moved.

    The tab has to READ as alphabetical on both levels (Eve, 2026-08-14), and a
    hand-typed row or an append-fallback run can knock it out of order — so
    every run ends here rather than trusting the order it found.

    This is the one write in the module that is a REWRITE, so it stays as
    narrow as it can: whole A:D tuples are moved intact, which keeps each
    person's own phone-number style, and nothing is created or dropped — the
    row count going out equals the row count coming in. Anything below the last
    entry, and every column right of D, is left alone.
    """
    ordered = sorted(entries, key=lambda e: e.sort_key)
    moved = sum(1 for a, b in zip(entries, ordered) if a.row != b.row)
    if not moved:
        logfn("  order: already (first, last) alphabetical — nothing moved")
        return 0
    if dry_run:
        logfn(f"  order: {moved} row(s) would move (dry run — not touched)")
        return moved
    first_row = entries[0].row
    ws.update(f"A{first_row}:D{first_row + len(ordered) - 1}",
              [e.values() for e in ordered], value_input_option="USER_ENTERED")
    logfn(f"  order: re-sorted, {moved} row(s) moved")
    return moved
