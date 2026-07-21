"""Org Sales Board — daily 8:30am Slack post (Item 1 of the VA-Slack replacements).

Replaces Jolie's manual daily post of the full board. Screenshots the daily
detailed board off our AUTOMATION's tab (`Copy of Alphalete ORG Sales Board`)
as ONE image and posts it to #top-leaders-alphalete-org.

SOURCE TAB (Megan 2026-07-21): switched from the live VA tab (`PROD_TAB`) to our
copy tab (`SANDBOX_TAB`). The VA tab depended on the VAs hand-keying yesterday
before we could post — on 7/21 they hadn't entered Monday by the last pass, so the
gate held all day even though our automation had Monday (39/45 cells). Reading the
copy tab lets this post stand on our own numbers. Eve is validating the fill's
correctness; flip back to PROD_TAB only if she finds the copy tab off.

Board layout on the live tab (found dynamically, never hardcoded):
  - Each section header row has "RUNNING WEEK TOTALS" in col J and Monday..Sunday
    in cols C..I; the next row holds the day-of-month dates (e.g. 13..19).
  - Rep rows follow (rank in col A, name in col B) until a "Totals" row.
  - Columns A..L are shown (col M "Org Head" is cropped off, matching Jolie).

Gate (LIGHT, Megan 2026-07-18): runs 8:30am CST daily, retrying q25m. Posts
unless YESTERDAY is entirely empty across every section (board never updated).
It deliberately does NOT require 100% — Retail JE and Frontier lag a day and the
VA posts with those blanks anyway. Posts once per day; later passes no-op.
Caption/filename use YESTERDAY's date, matching the VA ("Org Sales Board 7.16").

Usage:
  python -m automations.org_sales_board.slack_post            # dry-run, make PNG
  python -m automations.org_sales_board.slack_post --post     # actually post (asks first!)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from gspread.utils import rowcol_to_a1

from automations.recruiting_report.fill import open_by_key, _retry
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
from automations.org_sales_board.screenshot_email import _export_png, _access_token

CHANNEL = ("#top-leaders-alphalete-org", "C067TTGFEFR")   # Lucy is a member
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "org_sales_board"
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "org_board_last_posted.txt"

HEADER_MARK = "RUNNING WEEK TOTALS"   # col J of every section header row
LAST_COL = "L"                        # crop through Previous Week's Totals
SUMMARY_LABELS = {"totals", "last week", "prior week",
                  "2 weeks prior", "3 weeks prior", "grand total"}


def _cell(g, r, c):
    return g[r - 1][c - 1] if r - 1 < len(g) and c - 1 < len(g[r - 1]) else ""


def _header_rows(g):
    """1-based rows whose col J == RUNNING WEEK TOTALS — one per daily section."""
    return [r for r in range(1, len(g) + 1)
            if _cell(g, r, 10).strip().upper() == HEADER_MARK]


SECTION_GAP = 30    # sections in the org board are ≤20 rows apart; the next
                    # block (unit-level breakdowns) starts ~47+ rows down.


def board_range(g):
    """A{first_header}:L{last_data_row} for the FIRST contiguous run of daily
    sections (the 8 org-wide product boards Jolie posts) — not the unit-level
    breakdown blocks further down the tab."""
    heads = _header_rows(g)
    if not heads:
        raise SystemExit("daily board not found (no RUNNING WEEK TOTALS header)")
    kept = [heads[0]]
    for h in heads[1:]:
        if h - kept[-1] <= SECTION_GAP:
            kept.append(h)
        else:
            break
    start = kept[0]
    r = kept[-1]
    end = r
    while r <= len(g):
        if any(_cell(g, r, c).strip() for c in range(1, 13)):
            end = r
            r += 1
        else:
            break
    return f"A{start}:{LAST_COL}{end}", start, end, kept


def _rep_rows(g, header_row):
    """Row numbers of the rep lines in a section (rank in A, name in B), stopping
    at the first Totals/summary row."""
    out = []
    r = header_row + 2                 # skip header + date row
    while r <= len(g):
        a = _cell(g, r, 1).strip()
        b = _cell(g, r, 2).strip()
        if a.lower() in SUMMARY_LABELS:
            break
        if not a and not b:
            break
        if b:                          # a named rep line
            out.append(r)
        r += 1
    return out


def _yesterday_col(g, date_row, yday_day):
    """Column index (C..I) in this section whose date cell == yesterday's day."""
    for c in range(3, 10):
        if _cell(g, date_row, c).strip() == str(yday_day):
            return c
    return None


def fill_gate(g, heads, yday: dt.date):
    """LIGHT sanity gate (Megan 2026-07-18): post unless yesterday's column is
    ENTIRELY empty across every section — which would mean the board never got
    touched or the week didn't roll.

    NOT "every cell filled": Retail JE and Frontier legitimately lag a day, and
    the VA posts with those blanks anyway (verified against her own 7/16 post).
    Requiring 100% held the report every morning and it never posted."""
    filled = total = sections_with_col = 0
    for h in heads:
        col = _yesterday_col(g, h + 1, yday.day)
        if col is None:
            continue
        sections_with_col += 1
        for rr in _rep_rows(g, h):
            total += 1
            if _cell(g, rr, col).strip():
                filled += 1
    if sections_with_col == 0:
        return False, (f"no section has a column for {yday.month}/{yday.day} "
                       "(week not rolled / date headers missing)")
    if total == 0:
        return False, "no rep rows found in any section"
    if filled == 0:
        return False, (f"board is empty for {yday.month}/{yday.day} — 0 of {total} "
                       "rep cells have data (board not updated?)")
    return True, f"{filled}/{total} rep cells filled for {yday.month}/{yday.day}"


def _publish_hub(status: str) -> None:
    """Flip the Hub card's pill. Best-effort — never fails the run."""
    try:
        from automations.day_orchestrator import hub_publish
        hub_publish.publish_done("org_board_slack", "Org Sales Board → #top-leaders-alphalete-org", status)
    except Exception:  # noqa: BLE001 — Hub publish must never break the post
        pass


def _channel():
    scratch = os.environ.get("ORG_BOARD_CHANNEL_ID")
    return (f"scratch ({scratch})", scratch) if scratch else CHANNEL


def _already_posted(day: str) -> bool:
    return STATE_PATH.exists() and STATE_PATH.read_text().strip() == day


def _mark_posted(day: str) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(day)


def post_to_slack(png: Path, caption: str, filename: str, dry_run: bool):
    from automations.shared import slack_metrics_post as smp
    name, cid = _channel()
    if dry_run:
        return {"dry_run": True, "channel": name, "id": cid, "caption": caption}
    resp = smp._client().files_upload_v2(channel=cid, file=str(png),
                                         filename=filename, initial_comment=caption)
    return {"channel": name, "id": cid, "ok": resp.get("ok"),
            "file": (resp.get("file") or {}).get("id")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true",
                    help="ACTUALLY post to Slack (default dry-run — no posting)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    today = dt.date.today()
    yday = today - dt.timedelta(days=1)
    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(SANDBOX_TAB))
    g = _retry(ws.get_all_values)
    rng, start, end, heads = board_range(g)
    print(f"board: {SANDBOX_TAB} {rng}  ({len(heads)} sections)  gid={ws.id}")

    ok, reason = fill_gate(g, heads, yday)
    print(f"gate: {ok} — {reason}")

    # The VA titles the post with YESTERDAY's date (the data date): a post made
    # on 7/17 reads "• *Org Sales Board 7/16*" / "Org Sales Board 7.16.png".
    caption = f"• *Org Sales Board {yday.month}/{yday.day}*"
    filename = f"Org Sales Board {yday.month}.{yday.day}.png"
    out = args.out or (OUT_DIR / filename)
    _export_png(ws.id, rng, out, _access_token())
    print(f"wrote {out}")

    if not ok:
        print("NOT FILLED — holding. (Scheduler retries in 25 min.)")
        return 75
    day_key = today.isoformat()
    if _already_posted(day_key):
        print(f"already posted {day_key} — nothing to do.")
        return 0
    if not args.post:
        r = post_to_slack(out, caption, filename, dry_run=True)
        print(f"dry-run (default): not posting. WOULD post to {r['channel']} ({r['id']}).")
        return 0
    try:
        r = post_to_slack(out, caption, filename, dry_run=False)
    except Exception:
        _publish_hub("failed")
        raise
    print(f"POSTED to {r['channel']}: ok={r.get('ok')} file={r.get('file')}")
    _mark_posted(day_key)
    # Report to the Hub ONLY on a real post — this runs 8x/day and publishing
    # every pass would bury the activity log. [[feedback_launchd_reports_must_publish]]
    _publish_hub("success")
    return 0


if __name__ == "__main__":
    sys.exit(main())
