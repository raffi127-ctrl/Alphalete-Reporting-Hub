"""Mark 'Bug Reports' rows resolved from the CLI — no Streamlit needed.

WHY THIS EXISTS
The Hub auto-files a row on the Bug Reports tab every time a report run fails,
but nothing ever flips Status off 'Open'. So the tab piles up with glitches
that were ALREADY fixed in a later commit, and the triage ("which of these is
still real?") has to be redone by hand every time. This lets the agent — or
anyone — stamp a row as resolved with the fixing commit, so the tab reflects
reality.

STATUS VALUE: 'Resolved'
Distinct from the human-triage 'Fixed' / 'Needs Info' statuses. The Sheet's
Apps Script emails the submitter when a bug flips to Fixed/Needs Info; 'Resolved'
is the quiet, fixed-in-commit marker for bulk cleanup and should NOT trigger a
submitter email. (If you WANT the submitter emailed, pass --status Fixed.)

COLUMNS BY LABEL, NOT INDEX
Status / Resolution Note / Resolved At are located by header name every run, so
a schema reshuffle can never make this write the wrong cell.

USAGE
    # preview (default — writes nothing):
    python -m automations.hub_bug_resolve --match "503" --note "fixed in 98ee27a"
    # apply:
    python -m automations.hub_bug_resolve --match "503" --note "fixed in 98ee27a" --apply
    # by explicit IDs:
    python -m automations.hub_bug_resolve --ids 20260604105843 20260603205343 \
        --note "fixed in f80fb18" --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List, Optional

import gspread

# Canonical intake Sheet (same key dashboard.py uses; a stable Sheet id, not a
# row/column, so it's safe to name here).
INTAKE_SPREADSHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
BUG_TAB = "Bug Reports"

# Quiet, fixed-in-commit status — see module docstring.
RESOLVED_STATUS = "Resolved"


def _bugs_ws():
    from automations.recruiting_report import fill
    sh = fill.open_by_key(INTAKE_SPREADSHEET_ID)
    return sh.worksheet(BUG_TAB)


def _col(headers: List[str], name: str) -> int:
    """1-based column index for `name` (case-insensitive). Raises if absent —
    we never guess a position."""
    for i, h in enumerate(headers, 1):
        if (h or "").strip().lower() == name.lower():
            return i
    raise KeyError(
        f"Bug Reports tab has no {name!r} column (have: {headers}). "
        "Refusing to guess a position."
    )


def resolve(
    *,
    ids: Optional[List[str]] = None,
    match: Optional[str] = None,
    note: str,
    status: str = RESOLVED_STATUS,
    apply: bool = False,
) -> List[dict]:
    """Mark matching bug rows resolved. Returns the list of rows it touched
    (or WOULD touch in preview mode).

    Selection: explicit `ids`, and/or rows whose ID/Title/Details contain the
    `match` substring (case-insensitive). At least one selector is required.
    """
    if not ids and not match:
        raise ValueError("pass --ids and/or --match to select rows")
    ws = _bugs_ws()
    values = ws.get_all_values()
    if not values:
        print("Bug Reports tab is empty.")
        return []
    headers = values[0]
    c_id = _col(headers, "ID")
    c_status = _col(headers, "Status")
    c_note = _col(headers, "Resolution Note")
    c_resolved = _col(headers, "Resolved At")
    c_title = _col(headers, "Title")

    id_set = {str(x).strip() for x in (ids or [])}
    needle = (match or "").strip().lower()
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    selected = []
    for rownum, row in enumerate(values[1:], start=2):
        def cell(i: int) -> str:
            return row[i - 1] if len(row) >= i else ""
        rid = cell(c_id).strip()
        cur_status = cell(c_status).strip()
        hay = " ".join(cell(i).lower() for i in (c_id, c_title)) + " " + " ".join(
            (row[j] or "").lower() for j in range(len(row))
        )
        hit = (rid in id_set) or (needle and needle in hay)
        if not hit:
            continue
        # Don't re-stamp something already resolved/fixed (idempotent re-runs).
        if cur_status.lower() in ("resolved", "fixed"):
            continue
        selected.append({
            "row": rownum, "id": rid, "title": cell(c_title).strip(),
            "from_status": cur_status or "Open",
        })

    if not selected:
        print("No matching unresolved rows.")
        return []

    print(f"{'APPLY' if apply else 'DRY-RUN'} — {len(selected)} row(s) -> "
          f"Status={status!r}, Resolution Note={note!r}:")
    for s in selected:
        print(f"  row {s['row']:>3} | {s['id']} | {s['from_status']:>11} -> "
              f"{status} | {s['title'][:50]}")

    if not apply:
        print("\n(preview only — re-run with --apply to write)")
        return selected

    # One batched write keeps us well under the per-minute quota.
    def a1(col: int, rownum: int) -> str:
        return gspread.utils.rowcol_to_a1(rownum, col)
    data = []
    for s in selected:
        r = s["row"]
        data.append({"range": a1(c_status, r), "values": [[status]]})
        data.append({"range": a1(c_note, r), "values": [[note]]})
        data.append({"range": a1(c_resolved, r), "values": [[stamp]]})
    ws.batch_update(data, value_input_option="USER_ENTERED")
    print(f"\n✓ wrote {len(selected)} row(s).")
    return selected


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Mark Bug Reports rows resolved.")
    ap.add_argument("--ids", nargs="*", default=[], help="explicit bug IDs")
    ap.add_argument("--match", default="", help="substring of ID/Title/Details")
    ap.add_argument("--note", required=True, help="Resolution Note (cite the fix/commit)")
    ap.add_argument("--status", default=RESOLVED_STATUS,
                    help=f"status to set (default {RESOLVED_STATUS!r}; "
                         "use 'Fixed' to email the submitter)")
    ap.add_argument("--apply", action="store_true", help="write (default: preview)")
    args = ap.parse_args(argv)
    try:
        resolve(ids=args.ids, match=args.match or None, note=args.note,
                status=args.status, apply=args.apply)
    except (ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
