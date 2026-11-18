"""Relay Archive -- keep the 'Lucy Access App' relay workbook small.

WHY (2026-11-18). Nothing ever trimmed the tabs every office computer writes
to: by 11/18 'ICD Knocks' held 13.9 MB of JSON and 'ICD Faults' 12.4 MB of
tracebacks, back to 9/12. The relay read them whole on every upload and 42
offices timed out at once (931 times on 11/17). The relay now reads only its
key columns (resources/icd-alerts-relay.gs::_keyRows), but Lucy's own checks
still read these tabs in full many times a minute, and they only grow.

WHAT IT DOES, per tab, for rows older than the tab's cutoff:
  1. copy the WHOLE row to the archive workbook (same tab name, plus
     Source Row / Archived At / Archive Key), skipping rows already there;
  2. read the copy back and check every row arrived;
  3. re-read the source rows' key cells and check they still say the same
     office and day (nothing may have moved);
  4. only then EMPTY the heavy cells in place.

IT NEVER DELETES OR MOVES A ROW. Eight code paths write into these tabs by row
number (Lucy's posted stamps, the relay's upserts); a moved row would put one
office's write on another office's row. And ~10 readers ask "has this office
EVER relayed?", so every office keeps its rows -- just without the bulk.

WHAT EACH TAB KEEPS (from reading every reader, 2026-11-18):
  * ICD Faults: 7 days in full. The oldest any reader looks is 3 days
    (approve.health_lines). Detail is emptied.
  * ICD Knocks: 14 days in full. icd_sales_board.knocks_backfill reads the 7
    days before today; knocks history also lives in 'Knocks Daily'. Rows JSON
    and Tracker JSON are emptied.
  * ICD Relay: NOT TOUCHED. The ICD sales board site's "Week over week" table
    and "Week Ending" picker read every week ever relayed, and it is the only
    copy of relay sales history.

DRY RUN BY DEFAULT. Nothing is written without --apply.

    python -m automations.relay_archive.run                 # what it would do
    python -m automations.relay_archive.run --apply         # do it
    python -m automations.relay_archive.run --restore 2026-11-01 --tab "ICD Knocks" --apply

Exit codes: 0 done (or nothing to do), 1 error, 2 refused by a guard.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import Dict, List, Optional, Sequence, Tuple

# The relay workbook ('Lucy Access App').
SOURCE_ID = "1_5YGHhZ0gCYVZzHl7TPnP-6_75xaI0kcjPinQdVTlKg"
# 'Lucy Access App — Archive'. Created once with --create-archive on the
# machine that runs this nightly (its Google account must own or edit it),
# then pasted here. Until then --archive-id is required to write anything.
ARCHIVE_ID = ""
ARCHIVE_TITLE = "Lucy Access App — Archive"

# keep_days: days kept in full (today counts as day 0).
# min_keep: a guard -- refuse any cutoff closer than this, whatever is passed.
# key: header labels that, with the row number, identify the row.
# heavy: header labels of the cells that get emptied.
TABS: Dict[str, Dict] = {
    "ICD Faults": {"keep_days": 7, "min_keep": 4,
                   "key": ("Office", "Day", "Stage", "Summary"),
                   "heavy": ("Detail",)},
    "ICD Knocks": {"keep_days": 14, "min_keep": 9,
                   "key": ("Office", "Day"),
                   "heavy": ("Rows JSON", "Tracker JSON")},
}
# Never a tab this job may touch, whatever is passed on the command line.
NEVER = ("ICD Relay",)

EXTRA_HEAD = ["Source Row", "Archived At", "Archive Key"]
# One append request stays well under the Sheets API's request size limit.
MAX_CHUNK_CHARS = 2_000_000


class Refused(Exception):
    """A guard said no. Nothing was written."""


def _day_key(cell: str) -> str:
    from automations.icd_alerts.post import _day_key as k
    return k(cell)


def _col_letter(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _indexes(header: Sequence[str], labels: Sequence[str], tab: str) -> List[int]:
    """Column positions by HEADER LABEL. A missing label is a changed
    template: refuse rather than guess a column."""
    head = [str(h).strip() for h in header]
    out = []
    for lab in labels:
        if lab not in head:
            raise Refused("'%s' has no '%s' column -- the tab changed, "
                          "nothing touched" % (tab, lab))
        out.append(head.index(lab))
    return out


def archive_key(row_num: int, row: Sequence[str], key_idx: Sequence[int]) -> str:
    """Row number + its key cells. Rows never move, so the number pins it;
    the key cells are what --restore and the pre-clear check compare."""
    parts = [str(row_num)] + [(row[i] if i < len(row) else "").strip()
                              for i in key_idx]
    return "|".join(parts)


def plan_tab(values: List[List[str]], tab: str, today: dt.date,
             keep_days: Optional[int] = None) -> Dict:
    """Which rows of `values` (row 1 = header) get archived + emptied.

    Pure: no API calls. Returns the rows to archive (row number, full row,
    key) and the bytes that would be freed."""
    cfg = TABS[tab]
    keep = cfg["keep_days"] if keep_days is None else keep_days
    if keep < cfg["min_keep"]:
        raise Refused("%s: keeping %d days is under the %d-day floor -- "
                      "refused" % (tab, keep, cfg["min_keep"]))
    if not values:
        raise Refused("%s: empty tab (no header) -- refused" % tab)
    header = values[0]
    key_idx = _indexes(header, cfg["key"], tab)
    heavy_idx = _indexes(header, cfg["heavy"], tab)
    day_i = key_idx[1]
    cutoff = today - dt.timedelta(days=keep)

    rows, freed, unreadable, kept = [], 0, 0, 0
    for n, row in enumerate(values[1:], start=2):
        office = (row[key_idx[0]] if key_idx[0] < len(row) else "").strip()
        if not office:
            continue
        try:
            day = dt.date.fromisoformat(_day_key(row[day_i] if day_i < len(row) else ""))
        except ValueError:
            unreadable += 1        # never empty a row whose day we can't read
            continue
        if day >= cutoff:
            kept += 1
            continue
        size = sum(len(row[i]) for i in heavy_idx if i < len(row))
        if not size:
            continue               # already emptied on an earlier night
        rows.append({"row": n, "values": list(row),
                     "key": archive_key(n, row, key_idx)})
        freed += size
    return {"tab": tab, "header": list(header), "key_idx": key_idx,
            "heavy_idx": heavy_idx, "cutoff": cutoff, "rows": rows,
            "freed_chars": freed, "unreadable": unreadable, "kept": kept}


def clear_ranges(plan: Dict) -> List[str]:
    """A1 ranges covering the heavy cells of the planned rows, with runs of
    consecutive rows merged so one request clears thousands of cells."""
    nums = sorted(r["row"] for r in plan["rows"])
    spans: List[Tuple[int, int]] = []
    for n in nums:
        if spans and n == spans[-1][1] + 1:
            spans[-1] = (spans[-1][0], n)
        else:
            spans.append((n, n))
    out = []
    for i in plan["heavy_idx"]:
        col = _col_letter(i)
        out += ["%s%d:%s%d" % (col, a, col, b) for a, b in spans]
    return out


def _chunks(rows: List[List[str]]) -> List[List[List[str]]]:
    out, cur, size = [], [], 0
    for r in rows:
        n = sum(len(c) for c in r)
        if cur and size + n > MAX_CHUNK_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += n
    if cur:
        out.append(cur)
    return out


def _archive_tab(arc_book, tab: str, header: List[str]):
    """The archive's tab of the same name, created with its header if new."""
    try:
        ws = arc_book.worksheet(tab)
    except Exception:  # noqa: BLE001 -- gspread.WorksheetNotFound
        ws = arc_book.add_worksheet(title=tab, rows=1, cols=len(header) + 3)
        ws.update(range_name="A1", values=[header + EXTRA_HEAD],
                  value_input_option="RAW")
        return ws
    have = ws.row_values(1)
    if have[:len(header)] != header:
        raise Refused("archive tab '%s' has a different header than the "
                      "source -- refused" % tab)
    return ws


def _archived_keys(ws, header_len: int) -> set:
    col = header_len + 3          # 1-based: the Archive Key column
    return set(ws.col_values(col)[1:])


def run_tab(src_book, arc_book, tab: str, today: dt.date, *, apply: bool,
            keep_days: Optional[int] = None, log=print) -> Dict:
    ws = src_book.worksheet(tab)
    values = ws.get_all_values()
    plan = plan_tab(values, tab, today, keep_days)
    log("%s: %d row(s) older than %s still hold %.1f MB; %d recent row(s) "
        "kept in full; %d row(s) with an unreadable day left alone"
        % (tab, len(plan["rows"]), plan["cutoff"], plan["freed_chars"] / 1e6,
           plan["kept"], plan["unreadable"]))
    if not plan["rows"] or not apply:
        return plan

    # 1. ARCHIVE (skipping rows an earlier, interrupted night already copied).
    arc = _archive_tab(arc_book, tab, plan["header"])
    have = _archived_keys(arc, len(plan["header"]))
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    width = len(plan["header"])
    todo = [(r["values"] + [""] * width)[:width] + [str(r["row"]), stamp, r["key"]]
            for r in plan["rows"] if r["key"] not in have]
    for chunk in _chunks(todo):
        arc.append_rows(chunk, value_input_option="RAW",
                        insert_data_option="INSERT_ROWS")
    log("%s: archived %d row(s) (%d were already there)"
        % (tab, len(todo), len(plan["rows"]) - len(todo)))

    # 2. READ THE COPY BACK.
    got = _archived_keys(arc, len(plan["header"]))
    missing = [r["key"] for r in plan["rows"] if r["key"] not in got]
    if missing:
        raise RuntimeError("%s: %d row(s) did not reach the archive (first: "
                           "%s) -- nothing emptied" % (tab, len(missing), missing[0]))

    # 3. NOTHING MOVED. Re-read the key cells of the source, just before the clear.
    lo, hi = min(plan["key_idx"]), max(plan["key_idx"])
    fresh = ws.get("%s1:%s%d" % (_col_letter(lo), _col_letter(hi),
                                  max(r["row"] for r in plan["rows"])))
    for r in plan["rows"]:
        cur = fresh[r["row"] - 1] if r["row"] - 1 < len(fresh) else []
        cur = [""] * lo + list(cur)
        if archive_key(r["row"], cur, plan["key_idx"]) != r["key"]:
            raise RuntimeError("%s: row %d changed since it was read (%s) -- "
                               "nothing emptied" % (tab, r["row"], r["key"]))

    # 4. EMPTY THE HEAVY CELLS.
    ranges = clear_ranges(plan)
    ws.batch_clear(ranges)
    log("%s: emptied %s in %d row(s), %d range(s)"
        % (tab, " + ".join(TABS[tab]["heavy"]), len(plan["rows"]), len(ranges)))
    return plan


def restore(src_book, arc_book, tab: str, day: dt.date, *, apply: bool,
            log=print) -> int:
    """Put one archived day's heavy cells back, for a hand rerun of that day.
    Fills only cells that are empty now -- never overwrites live data."""
    cfg = TABS[tab]
    arc = arc_book.worksheet(tab)
    avals = arc.get_all_values()
    header = avals[0][:-len(EXTRA_HEAD)]
    key_idx = _indexes(header, cfg["key"], tab)
    heavy_idx = _indexes(header, cfg["heavy"], tab)
    want = [r for r in avals[1:]
            if _day_key(r[key_idx[1]] if key_idx[1] < len(r) else "") == day.isoformat()]
    if not want:
        log("%s: nothing archived for %s" % (tab, day))
        return 0
    ws = src_book.worksheet(tab)
    src = ws.get_all_values()
    updates = []
    for r in want:
        n = int(r[len(header)])
        cur = src[n - 1] if n - 1 < len(src) else []
        if archive_key(n, cur, key_idx) != r[len(header) + 2]:
            log("%s: row %d no longer matches its archive key -- skipped" % (tab, n))
            continue
        for i in heavy_idx:
            if (cur[i] if i < len(cur) else "") == "" and r[i]:
                updates.append({"range": "%s%d" % (_col_letter(i), n),
                                "values": [[r[i]]]})
    log("%s: %d cell(s) to put back for %s%s"
        % (tab, len(updates), day, "" if apply else " (dry run)"))
    if apply and updates:
        ws.batch_update(updates, value_input_option="RAW")
    return len(updates)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default: dry run, nothing written)")
    ap.add_argument("--tab", action="append", choices=sorted(TABS),
                    help="limit to one tab (repeatable); default both")
    ap.add_argument("--keep-days", type=int,
                    help="override the tab's days kept in full (floor still applies)")
    ap.add_argument("--source-id", default=SOURCE_ID,
                    help="workbook to trim (a test copy while building)")
    ap.add_argument("--archive-id", default=ARCHIVE_ID,
                    help="workbook the old rows are copied to")
    ap.add_argument("--restore", metavar="YYYY-MM-DD",
                    help="put that day's archived cells back (needs one --tab)")
    ap.add_argument("--create-archive", action="store_true",
                    help="one-time: create the archive workbook on THIS "
                         "machine's Google account, print its id, write nothing else")
    ap.add_argument("--today", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    # A run that writes nothing tells the Hub nothing. This module previews by
    # DEFAULT (no --dry-run flag to spot), so the exit hook would otherwise
    # mark the card "ran" for a preview -- caught on the first wrapper test.
    if not a.apply:
        from automations.shared import hub_autopublish
        hub_autopublish.nothing_to_report()

    from automations.recruiting_report.fill import open_by_key

    if a.create_archive:
        # Sheets API create, not Drive: the Lucys' token has the spreadsheets
        # scope only. The file lands in that account's Drive root.
        from automations.recruiting_report import fill
        resp = fill._client().http_client.request(
            "post", "https://sheets.googleapis.com/v4/spreadsheets",
            json={"properties": {"title": ARCHIVE_TITLE}})
        print("archive workbook created: %s -- put it in ARCHIVE_ID"
              % resp.json()["spreadsheetId"])
        return 0

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    tabs = a.tab or sorted(TABS)
    if any(t in NEVER for t in tabs):
        print("refused: %s is never trimmed" % ", ".join(NEVER))
        return 2
    if (a.apply or a.restore) and not a.archive_id:
        print("refused: no archive workbook (--archive-id) -- nothing written")
        return 2
    if a.apply and a.archive_id == a.source_id:
        print("refused: the archive cannot be the workbook it archives")
        return 2

    try:
        src = open_by_key(a.source_id)
        arc = open_by_key(a.archive_id) if a.archive_id else None
        if a.restore:
            if len(tabs) != 1:
                print("refused: --restore needs exactly one --tab")
                return 2
            restore(src, arc, tabs[0], dt.date.fromisoformat(a.restore),
                    apply=a.apply)
            return 0
        total = 0
        for tab in tabs:
            total += run_tab(src, arc, tab, today, apply=a.apply,
                             keep_days=a.keep_days)["freed_chars"]
        print("%s: %.1f MB %s" % ("done" if a.apply else "dry run", total / 1e6,
                                  "freed" if a.apply else "would be freed"))
        return 0
    except Refused as e:
        print("refused: %s" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
