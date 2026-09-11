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
KN_OFFICE, KN_DAY, KN_ROWS, KN_COUNT = 0, 1, 2, 3
KN_RECEIVED, KN_LOCAL, KN_POSTED = 4, 5, 6

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
    """Now, on the OFFICE's clock. A board that says a rep has been quiet for
    48 minutes is a claim about their evening, not about the runner's."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(office.timezone)).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return dt.datetime.now()


def in_field_hours(office, now: Optional[dt.datetime] = None) -> bool:
    """Only post while their reps are actually out. Sunday is off for everyone."""
    now = now or _office_now(office)
    if now.weekday() == 6:
        return False
    try:
        from automations.disposition_signup.schema import DEFAULT_HOURS as H
    except Exception:  # noqa: BLE001
        H = {"day_start": "13:30", "day_end": "22:00",
             "sat_start": "10:45", "sat_end": "18:30"}
    start, end = ((H["sat_start"], H["sat_end"]) if now.weekday() == 5
                  else (H["day_start"], H["day_end"]))
    return _hm(start) <= (now.hour, now.minute) <= _hm(end)


def _hm(text: str) -> Tuple[int, int]:
    h, m = str(text).split(":")
    return int(h), int(m)


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

        reps = M.to_reps(raw, day)
        gaps = M.gaps(reps, now, GAP_THRESHOLD_MIN)
        posted_at = _posted_map(row[KN_POSTED])

        due = [d for d in dests
               if force or is_due(d, posted_at.get(d["channel_id"]), now)]
        if not due:
            log("%-10s %d rep(s), %d over %dmin -- nothing due"
                % (key, len(reps), len(gaps), GAP_THRESHOLD_MIN))
            continue

        log("%-10s %d rep(s), %d over %dmin -> %s"
            % (key, len(reps), len(gaps), GAP_THRESHOLD_MIN,
               ", ".join(d.get("channel_name") or d["channel_id"] for d in due)))
        for g in gaps[:10]:
            log("    %-24s %s min ago" % (g["name"], g["minutesSinceLastKnock"]))

        if not send:
            continue

        card = _render(key, gaps, day)
        comment = _comment(office, reps, gaps, now)
        for d in due:
            try:
                _upload(d["channel_id"], card, comment)
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


def _render(office_key: str, gaps: List[Dict], day: dt.date) -> Path:
    from automations.b2b_dispositions.capture import render_gap_card
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / ("%s-%s.png" % (office_key, day.isoformat()))
    # scale=2 to match what the live boards already post; a 1x card beside a
    # 2x one reads as the softer of the two.
    return render_gap_card(gaps, out, scale=2.0)


def _clock(now: dt.datetime) -> str:
    """'8:05 PM'. Built by hand, NOT with %-I: that is a GNU extension which
    does not exist on Windows, and this repo's rule is that every report runs
    on both."""
    hour = now.hour % 12 or 12
    return "%d:%02d %s" % (hour, now.minute, "AM" if now.hour < 12 else "PM")


def _comment(office, reps: List[Dict], gaps: List[Dict], now: dt.datetime) -> str:
    knocks = sum(r.get("total_knocks", 0) for r in reps)
    return ("*%s — KNOCKS & DISPOSITIONS*\n%d rep(s) out · %s knocks today · "
            "%d over %d min\n_as of %s their time_"
            % (office.label, len(reps), "{:,}".format(knocks), len(gaps),
               GAP_THRESHOLD_MIN, _clock(now)))


def _upload(channel_id: str, card: Path, comment: str) -> None:
    from automations.shared import slack_metrics_post as smp
    smp._client().files_upload_v2(
        channel=channel_id, file=str(card), filename=card.name,
        initial_comment=comment)


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
