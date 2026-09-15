"""Yesterday's final knock board, into this morning's metrics thread.

Megan 2026-09-15: "for those getting knocks on the LucyECO and getting
metrics- can we make it so that their final knock board from the day prior is
posted that next morning in their metrics thread?"

WHY IT BELONGS THERE. An office's knock board lands through the day and is
scrolled past by the evening; the metrics thread is the thing an owner opens
the next morning to see how yesterday went. The board is the only part of
yesterday that is NOT in it, and it is the part that explains the rest -- a
soft day of numbers reads differently next to a day nobody knocked.

"THE DAY PRIOR" IS THE LAST SELLING DAY, not literally yesterday. On a Monday
yesterday is Sunday, which has no knocks at all, and posting an empty board or
nothing would both be wrong: what an owner wants on Monday morning is
Saturday. So this walks back to the most recent day that actually has rows.

IT POSTS ONCE. The poster runs every couple of minutes from 8am, and a recap
that arrived on every tick would be its own kind of broken.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional

from automations.icd_alerts import offices as O

# How far back to look for a day with knocks. Three covers a Monday after a
# Saturday, and a Tuesday after a bank-holiday Monday.
LOOK_BACK_DAYS = 3
# Posted before this hour, office time on our clock, or not at all.
RECAP_UNTIL_HOUR = 11
POSTED_PATH = (Path.home() / ".config" / "recruiting-report"
               / "icd_morning_recap.json")


def _posted() -> Dict:
    try:
        return json.loads(POSTED_PATH.read_text())
    except (OSError, ValueError):
        return {}


def eligible() -> List:
    """Offices on BOTH -- relaying their own knocks, and getting metrics.

    An office with no metrics thread has nowhere for this to go, and an office
    that is not relaying has no board to put there.
    """
    try:
        from automations.office_metrics import offices as OM
    except Exception:  # noqa: BLE001
        return []
    metrics = set(OM.OFFICES)
    return [o for o in O.active() if o.key in metrics]


def last_board_day(office_key: str, today: dt.date, book=None
                   ) -> "Optional[tuple]":
    """(day, rows) for the most recent day this office actually knocked."""
    from automations.icd_alerts import knocks_post as K
    from automations.recruiting_report.fill import open_by_key

    book = book or open_by_key(K.P.RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet("ICD Knocks").get_all_values()
    except Exception:  # noqa: BLE001
        return None
    by_day = {}
    for r in rows[1:]:
        if not r or (r[0] or "").strip().lower() != office_key:
            continue
        try:
            parsed = json.loads(r[2] or "[]")
        except (TypeError, ValueError):
            parsed = []
        if parsed:
            by_day[K.P._day_key(r[1])] = parsed
    for back in range(1, LOOK_BACK_DAYS + 1):
        key = (today - dt.timedelta(days=back)).isoformat()
        if by_day.get(key):
            return dt.date.fromisoformat(key), by_day[key]
    return None


def _metrics_thread(office, today: dt.date, log=print) -> str:
    """Today's metrics thread in this office's own channel, or ''.

    NOT POSTED IF IT IS NOT THERE YET. The thread is opened by a Slack
    Workflow at 7am and the boards land under it; arriving before it would
    mean a board floating loose in the channel above the thread it belongs to.
    Nothing is lost by waiting -- the poster tries again in two minutes.
    """
    from automations.shared import slack_metrics_post as smp
    try:
        from automations.office_metrics import offices as OM
        rec = OM.OFFICES.get(office.key)
        channel = getattr(rec, "channel_id", "") if rec else ""
        if not channel:
            return ""
        return smp.find_metrics_thread_ts(smp._client(), today,
                                          channel_id=channel) or ""
    except Exception as e:  # noqa: BLE001
        log("  could not find %s's metrics thread: %s"
            % (office.key, type(e).__name__))
        return ""


def run(today: Optional[dt.date] = None, *, send: bool = False,
        book=None, now: Optional[dt.datetime] = None,
        log=print) -> List[Dict]:
    """Post each eligible office's last board into this morning's thread."""
    from automations.icd_alerts import knocks_post as K
    from automations.recruiting_report.fill import open_by_key

    today = today or dt.date.today()
    if today.weekday() == 6:            # nobody opens a metrics thread Sunday
        return []
    # MORNINGS ONLY. The thread opens at 7am and the poster starts at 8; if it
    # has not appeared by late morning something else is wrong, and yesterday's
    # board dropping into an afternoon thread would read as today's.
    if (now or dt.datetime.now()).hour >= RECAP_UNTIL_HOUR:
        return []

    book = book or open_by_key(K.P.RELAY_SPREADSHEET_ID)
    posted = _posted()
    done = []
    for office in eligible():
        key = "%s|%s" % (today.isoformat(), office.key)
        if posted.get(key):
            continue
        found = last_board_day(office.key, today, book=book)
        if not found:
            continue
        day, rows = found
        log("RECAP: %-10s %s (%d rep rows)" % (office.key, day, len(rows)))
        if not send:
            done.append({"office": office.key, "day": day})
            continue

        ts = _metrics_thread(office, today, log=log)
        if not ts:
            continue                     # the thread is not up yet; try later
        try:
            boards, _shape = K._render(office, rows, day,
                                       dt.datetime.now())
        except Exception as e:  # noqa: BLE001 — one office must not stop the rest
            log("  could not draw %s's board: %s" % (office.key, type(e).__name__))
            continue
        if not boards:
            continue

        from automations.office_metrics import offices as OM
        channel = OM.OFFICES[office.key].channel_id
        # Built by hand: %-m is glibc-only and this repo runs on Windows too.
        comment = ("*Final knocks — %s %d/%d*"
                   % (day.strftime("%a"), day.month, day.day))
        try:
            _upload_to_thread(channel, ts, boards, comment)
        except Exception as e:  # noqa: BLE001
            log("  could not post %s's recap: %s: %s"
                % (office.key, type(e).__name__, str(e)[:120]))
            continue
        posted[key] = dt.datetime.now().isoformat(timespec="seconds")
        done.append({"office": office.key, "day": day})

    if send and done:
        POSTED_PATH.parent.mkdir(parents=True, exist_ok=True)
        for k in sorted(posted)[:-60]:
            posted.pop(k, None)
        POSTED_PATH.write_text(json.dumps(posted, indent=2, sort_keys=True))
    return done


def _upload_to_thread(channel_id: str, thread_ts: str, boards, comment: str):
    """Into the THREAD, not the channel. A board posted loose in the room is
    the thing this was meant to replace."""
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    for i, board in enumerate(boards):
        client.files_upload_v2(
            channel=channel_id, file=str(board), filename=Path(board).name,
            thread_ts=thread_ts,
            initial_comment=comment if i == 0 else None)
