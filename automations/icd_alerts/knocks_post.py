"""OUR side of the knocks board: draw it, and post it on each room's own clock.

THE LAPTOP HANDED OVER ROWS. Everything after that is here -- what the columns
mean, who counts as inactive, how the card looks, which rooms get it and how
often. That split is the same one the credit-check alerts use, and for the same
reason: an office can relay all day and still cannot put a message in Slack.

EACH DESTINATION HAS ITS OWN CLOCK. The owners' room every 15 minutes and the
rep channel once an hour is a normal answer (it is why the disposition
enrolment carries destinations rather than one cadence), so "is this due?" is
asked per room and answered from when THAT room last got one.

  python -m automations.icd_alerts.knocks_post                  # dry run
  python -m automations.icd_alerts.knocks_post --send
  python -m automations.icd_alerts.knocks_post --office kash --force
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.icd_alerts import knocks_map as M, offices as O, post as P

KNOCKS_TAB = "ICD Knocks"
KN_OFFICE, KN_DAY, KN_ROWS, KN_TRACKER, KN_COUNT = 0, 1, 2, 3, 4
KN_RECEIVED, KN_LOCAL, KN_POSTED = 5, 6, 7

GAP_THRESHOLD_MIN = 15
OUT_DIR = Path.home() / ".config" / "recruiting-report" / "icd_knocks_cards"

# Fixed-time destinations (cadence_min == 0) post at these moments, the same
# three knocks_intraday already uses. A slot counts as hit if we are within
# SLOT_GRACE_MIN after it -- the poster ticks every 10 minutes, so demanding
# the exact minute would mean a slot could be missed entirely.
SLOT_GRACE_MIN = 40


def _slots():
    try:
        from automations.disposition_signup.schema import CODY_SLOTS
        return list(CODY_SLOTS)
    except Exception:  # noqa: BLE001
        return ["14:00", "17:15", "21:00"]


def _office_now(office) -> dt.datetime:
    """Now, on the OFFICE's clock. One definition, in offices.py, because the
    quiet-laptop nudge asks the same question and the two must not drift."""
    return O.office_now(office)


def in_field_hours(office, now: Optional[dt.datetime] = None) -> bool:
    """Only post while THIS office's reps are out. One definition, in
    offices.py, because each office carries its own window now."""
    return O.in_field_hours(office, now)


# Re-exported: _slot_due still parses the fixed-time slots, and moving
# in_field_hours out took the helper with it. A NameError in a due-check
# reads as "no destination is ever due", which is silence.
_hm = O._hm


def is_due(dest: Dict, last_posted: Optional[dt.datetime],
           now: dt.datetime) -> bool:
    """Is THIS room due for a board?

    Never posted = due. That is what makes an approval take effect on the next
    tick rather than an hour later.
    """
    cadence = int(dest.get("cadence_min") or 0)
    if cadence == 0:
        return _slot_due(last_posted, now)
    if last_posted is None:
        return True
    return (now - last_posted) >= dt.timedelta(minutes=cadence)


def _slot_due(last_posted: Optional[dt.datetime], now: dt.datetime) -> bool:
    """Fixed times: due if we are just past a slot and have not posted since it."""
    for text in _slots():
        h, m = _hm(text)
        slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot <= now <= slot + dt.timedelta(minutes=SLOT_GRACE_MIN):
            return last_posted is None or last_posted < slot
    return False


def _parse_when(text: str) -> Optional[dt.datetime]:
    text = (text or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _posted_map(cell: str) -> Dict[str, dt.datetime]:
    try:
        raw = json.loads(cell or "{}")
    except ValueError:
        return {}
    return {k: w for k, v in raw.items() if (w := _parse_when(v))}


def run(day: Optional[dt.date] = None, *, send: bool = False,
        only: Optional[str] = None, force: bool = False, log=print) -> Dict:
    from automations.recruiting_report.fill import open_by_key
    book = open_by_key(P.RELAY_SPREADSHEET_ID)
    try:
        tab = book.worksheet(KNOCKS_TAB)
    except Exception:  # noqa: BLE001
        log("no '%s' tab yet -- no office has relayed knocks" % KNOCKS_TAB)
        return {"posted": 0}

    approved = P.approved_knocks(book)
    day = day or dt.date.today()
    values = tab.get_all_values()
    posted_total = 0

    for i, row in enumerate(values[1:], start=2):
        row = list(row) + [""] * (KN_POSTED + 1 - len(row))
        key = (row[KN_OFFICE] or "").strip().lower()
        if only and key != only.strip().lower():
            continue
        if P._day_key(row[KN_DAY]) != day.isoformat():
            continue
        office = O.get(key)
        if not office or not O.is_enrolled(key):
            log("%-10s relayed knocks but is not enrolled -- ignored" % key)
            continue

        dests = approved.get(key) or []
        if not dests:
            log("%-10s %s rep row(s) relayed, but no knocks destination is "
                "approved yet" % (key, row[KN_COUNT] or "?"))
            continue

        now = _office_now(office)
        if not force and not in_field_hours(office, now):
            log("%-10s outside field hours (%s their time)"
                % (key, now.strftime("%a %H:%M")))
            continue

        try:
            raw = json.loads(row[KN_ROWS] or "[]")
        except ValueError:
            log("%-10s knocks could not be read -- skipping" % key)
            continue

        try:
            tracker = json.loads(row[KN_TRACKER] or "[]")
        except ValueError:
            tracker = []
        rows_for_board = M.to_rows(raw, tracker)
        if not rows_for_board:
            log("%-10s relayed nothing to draw yet today" % key)
            continue
        posted_at = _posted_map(row[KN_POSTED])

        due = [d for d in dests
               if force or is_due(d, posted_at.get(d["channel_id"]), now)]
        if not due:
            log("%-10s %d rep(s) -- nothing due" % (key, len(rows_for_board)))
            continue

        boards, shape = _render(office, rows_for_board, day, now)
        log("%-10s %d rep(s), %s board -> %s"
            % (key, len(rows_for_board), shape,
               ", ".join(d.get("channel_name") or d["channel_id"] for d in due)))

        if not send:
            continue

        comment = _comment(office, rows_for_board, now)
        for d in due:
            try:
                _upload(d["channel_id"], boards, comment)
                posted_at[d["channel_id"]] = now
                posted_total += 1
            except Exception as e:  # noqa: BLE001 — one room must not cost the rest
                log("%-10s FAILED to post to %s: %s: %s"
                    % (key, d.get("channel_name") or d["channel_id"],
                       type(e).__name__, str(e)[:120]))
        tab.update_cell(i, KN_POSTED + 1, json.dumps(
            {k: v.isoformat(timespec="seconds") for k, v in posted_at.items()}))

    if not send:
        log("\nDRY RUN -- nothing posted and nothing recorded.")
    return {"posted": posted_total}


def _render(office, rows: List[Dict], day: dt.date, now: dt.datetime):
    """The office's board(s), through the SAME renderer every other office
    uses -- ([paths], shape).

    render_knocks_boards picks the board off the row SHAPE: fiber gets the
    Talk-To split and the rate columns, wireless gets its own flatter one plus
    a Time Gaps twin, Energy Wells gets VL and Presentation. Drawing our own
    card here instead would mean an ICD's board quietly diverging from
    everyone else's the first time a column was added -- and a column IS added
    every few weeks.
    """
    from automations.total_knocks import render as knocks_render
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_dir = OUT_DIR / office.key
    return knocks_render.render_knocks_boards(
        day, rows=rows, out_dir=out_dir,
        title_suffix=office.label,
        date_text="%s · %s" % (day.strftime("%a %m/%d"), _clock(now)))


def _clock(now: dt.datetime) -> str:
    """'8:05 PM'. Built by hand, NOT with %-I: that is a GNU extension which
    does not exist on Windows, and this repo's rule is that every report runs
    on both."""
    hour = now.hour % 12 or 12
    return "%d:%02d %s" % (hour, now.minute, "AM" if now.hour < 12 else "PM")


def _comment(office, rows: List[Dict], now: dt.datetime) -> str:
    """THE SAME HEADER RAF'S BOARD CARRIES (Megan 2026-09-12).

    Taken from gap_alerts rather than retyped, so the two cannot drift: one
    board in two rooms with two different headers is the kind of difference
    somebody has to explain.

    No office name, and no rep/knock summary. Raf's has neither -- the channel
    IS the office, so naming it in the header is telling a room whose room it
    is, and the counts are in the image directly beneath.
    """
    try:
        from automations.gap_alerts.config import CARD_TITLE
    except Exception:  # noqa: BLE001
        CARD_TITLE = "KNOCKS & DISPOSITIONS"
    return "*%s — %s*  ·  ranked by total knocks" % (CARD_TITLE.title(),
                                                     _clock(now))


def _upload(channel_id: str, boards, comment: str) -> None:
    """Every board this shape produced, in post order. A wireless office gets
    a pair (the board and its Time Gaps twin) and both belong in the room."""
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    for i, board in enumerate(boards):
        client.files_upload_v2(
            channel=channel_id, file=str(board), filename=Path(board).name,
            initial_comment=comment if i == 0 else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Post relayed ICD knocks boards")
    ap.add_argument("--send", action="store_true",
                    help="actually post (default is a dry run)")
    ap.add_argument("--office", help="limit to one office key")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--force", action="store_true",
                    help="ignore cadence and field hours (for a preview)")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.day) if args.day else dt.date.today()
    if args.send:
        P.assert_posting_as_lucy()
    run(day, send=args.send, only=args.office, force=args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
