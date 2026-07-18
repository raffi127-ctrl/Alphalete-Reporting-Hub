"""Org Sales Board — daily 9am Slack post (Item 1 of the VA-Slack replacements).

Replaces Jolie's manual daily post of the full board. Screenshots the daily
detailed board off the LIVE tab (`Alphalete ORG Sales Board` — the VA tab today;
same tab once our fill goes live) as ONE image and (once approved) posts it to
#top-leaders-alphalete-org.

Board layout on the live tab (found dynamically, never hardcoded):
  - Each section header row has "RUNNING WEEK TOTALS" in col J and Monday..Sunday
    in cols C..I; the next row holds the day-of-month dates (e.g. 13..19).
  - Rep rows follow (rank in col A, name in col B) until a "Totals" row.
  - Columns A..L are shown (col M "Org Head" is cropped off, matching Jolie).

Gate: run 9am; only post once the PREVIOUS day's column is 100% filled across
every rep in every section (a real 0 is typed, so a blank = not entered yet).
If not filled, hold and retry every 25 min. Post once per day.

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
from automations.org_sales_board.run import SHEET_ID, PROD_TAB
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
    """(ok, reason). ok only when every rep in every section has a value in
    yesterday's column."""
    missing = []
    for h in heads:
        col = _yesterday_col(g, h + 1, yday.day)
        if col is None:
            return False, (f"section at row {h}: no column for {yday.month}/{yday.day} "
                           "(week not rolled / date header missing)")
        for rr in _rep_rows(g, h):
            if not _cell(g, rr, col).strip():
                missing.append(f"{_cell(g, rr, 2).strip()} (row {rr})")
    if missing:
        return False, f"{len(missing)} rep cell(s) blank for {yday.month}/{yday.day}: " \
                      + ", ".join(missing[:6]) + (" …" if len(missing) > 6 else "")
    return True, ""


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
    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(PROD_TAB))
    g = _retry(ws.get_all_values)
    rng, start, end, heads = board_range(g)
    print(f"board: {PROD_TAB} {rng}  ({len(heads)} sections)  gid={ws.id}")

    ok, reason = fill_gate(g, heads, yday)
    print(f"gate (yesterday {yday.month}/{yday.day} filled): {ok}"
          + (f" — {reason}" if not ok else ""))

    caption = f"Org Sales Board ({today.month}/{today.day})"
    filename = f"Org Sales Board {today.month}.{today.day}.png"
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
    r = post_to_slack(out, caption, filename, dry_run=False)
    print(f"POSTED to {r['channel']}: ok={r.get('ok')} file={r.get('file')}")
    _mark_posted(day_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
