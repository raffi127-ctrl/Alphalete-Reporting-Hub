"""Append promotion rows to Maud's Recognition sheet — the current week's tab.

APPEND-ONLY. We find the first empty row after the last filled one and write
Rep | Trainer | Owner | Recognition | Notes there. We never edit or clear an
existing row, and we dedup by rep so re-submitting can't double-log someone.
See [[feedback_save_state_during_mapping]] / [[project_recognition_weekly_tab]].
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config as C

HEADERS = ["Rep", "Trainer", "Owner", "Recognition", "Notes for Extra Recognition"]


@dataclass
class Promotion:
    name: str
    trainer: str
    recognition: str        # "LVL 1 Leader" etc.
    note: str = ""
    owner: str = ""


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def _target_worksheet(sh):
    """The current week's M.D.YY tab (matches Maud's Sunday tab-creator). Falls
    back to the front tab if that exact name isn't present yet."""
    if C.RECOGNITION_TAB_OVERRIDE:
        return sh.worksheet(C.RECOGNITION_TAB_OVERRIDE)
    from automations.leaders_call.recognition_tab import week_tab_name
    want = week_tab_name()
    titles = {w.title: w for w in sh.worksheets()}
    if want in titles:
        return titles[want]
    return sh.worksheets()[0]              # newest tab sits at index 0


def _header_row(grid):
    """0-based index of the 'Rep | Trainer | Owner | Recognition | …' row."""
    for i, row in enumerate(grid[:10]):
        cells = [(c or "").strip().lower() for c in row[:4]]
        if cells[:2] == ["rep", "trainer"]:
            return i
    raise RuntimeError("Recognition tab has no 'Rep | Trainer | …' header row.")


def append_promotions(promos, *, sheet_id: str = None, dry_run: bool = True):
    """Append each Promotion to the current recognition tab.

    Returns a result dict {tab, wrote, added, skipped_dup, row_start, link}.
    Dry-run computes everything and writes nothing.
    """
    from automations.recruiting_report import fill
    sheet_id = sheet_id or C.RECOGNITION_SHEET_ID
    sh = fill._client().open_by_key(sheet_id)
    ws = _target_worksheet(sh)
    grid = ws.get_all_values()
    hdr = _header_row(grid)

    existing = {_norm(row[0]) for row in grid[hdr + 1:] if row and row[0].strip()}
    # last filled data row (1-based); append below it.
    last_filled = hdr + 1
    for i in range(hdr + 1, len(grid)):
        if grid[i] and grid[i][0].strip():
            last_filled = i + 1            # store 1-based

    added, skipped, rows = [], [], []
    for p in promos:
        if _norm(p.name) in existing:
            skipped.append(p.name)
            continue
        existing.add(_norm(p.name))
        rows.append([p.name, p.trainer, p.owner or C.OWNER, p.recognition, p.note])
        added.append(p.name)

    row_start = last_filled + 1
    link = (f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={ws.id}")
    if rows and not dry_run:
        rng = f"A{row_start}:E{row_start + len(rows) - 1}"
        ws.update(rows, rng, value_input_option="USER_ENTERED")

    return {"tab": ws.title, "wrote": bool(rows) and not dry_run,
            "added": added, "skipped_dup": skipped, "row_start": row_start,
            "link": link, "n": len(rows)}


def logged_this_week(*, sheet_id: str = None, owner: str = None):
    """Reps THIS office logged on the current tab — [(rep, recognition)]. Only
    rows whose Owner matches ours, so the remove-list never offers another
    office's row."""
    from automations.recruiting_report import fill
    sheet_id = sheet_id or C.RECOGNITION_SHEET_ID
    owner = owner or C.OWNER
    sh = fill._client().open_by_key(sheet_id)
    ws = _target_worksheet(sh)
    grid = ws.get_all_values()
    hdr = _header_row(grid)
    out = []
    for row in grid[hdr + 1:]:
        if len(row) < 3 or not row[0].strip():
            continue
        if _norm(row[2]) == _norm(owner):
            rec = row[3].strip() if len(row) > 3 else ""
            out.append((row[0].strip(), rec))
    return out


def remove_promotions(names, *, sheet_id: str = None, owner: str = None,
                      dry_run: bool = True):
    """Clear the row (A:E) for each named rep — but ONLY where Owner is ours, so
    we can never blank another office's entry. Clearing (not deleting) leaves the
    other rows exactly where they are. Returns {tab, wrote, removed, link}."""
    from automations.recruiting_report import fill
    sheet_id = sheet_id or C.RECOGNITION_SHEET_ID
    owner = owner or C.OWNER
    want = {_norm(n) for n in names}
    sh = fill._client().open_by_key(sheet_id)
    ws = _target_worksheet(sh)
    grid = ws.get_all_values()
    hdr = _header_row(grid)
    link = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={ws.id}"

    removed, ranges = [], []
    for i in range(hdr + 1, len(grid)):
        row = grid[i]
        if len(row) < 3 or not row[0].strip():
            continue
        if _norm(row[0]) in want and _norm(row[2]) == _norm(owner):
            ranges.append(f"A{i + 1}:E{i + 1}")     # 1-based row
            removed.append(row[0].strip())
    if ranges and not dry_run:
        ws.batch_clear(ranges)
    return {"tab": ws.title, "wrote": bool(ranges) and not dry_run,
            "removed": removed, "link": link, "n": len(removed)}
