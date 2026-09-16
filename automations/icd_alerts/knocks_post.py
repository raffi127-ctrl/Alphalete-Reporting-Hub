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

from automations.icd_alerts import (campaign_guard, knocks_map as M,
                                    offices as O, post as P)

KNOCKS_TAB = "ICD Knocks"
KN_OFFICE, KN_DAY, KN_ROWS, KN_TRACKER, KN_COUNT = 0, 1, 2, 3, 4
KN_RECEIVED, KN_LOCAL, KN_POSTED = 5, 6, 7

# HOW OLD A READING MAY BE AND STILL BE WORTH DRAWING. The agent relays every
# couple of minutes, so twenty-five is a dozen missed sweeps -- not a slow
# tick, a machine that has stopped. Below the 45 that marks an office QUIET,
# deliberately: the board should go silent before we start telling people an
# office is down, not after.
STALE_MINUTES = 25

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


def _received_at(text: str) -> Optional[dt.datetime]:
    """When the relay took this row in. None when it cannot be read.

    TWO FORMATS, BECAUSE THE SHEET WRITES ONE AND THE MACHINE WRITES THE
    OTHER. 'Received At' comes back from Sheets as 9/16/2026 16:58:01 and the
    machine's own clock column is ISO. Reading only ISO -- which is what the
    first version of this did -- makes every row unparseable, and with the
    staleness check below that silences EVERY office's board at once. Caught
    before it shipped, on 2026-09-16, by asking what the column actually
    contains rather than assuming.
    """
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _too_old(text: str) -> bool:
    """Is this reading too old to draw a board from?

    UNREADABLE MEANS CARRY ON, not stop. A format we cannot parse is our
    problem, and the cost of guessing wrong in each direction is not
    symmetric: posting a board that might be slightly old is recoverable, and
    silencing every office at once because of a date format is not. The
    quiet-machine nudge still reports a machine that has actually stopped.
    """
    when = _received_at(text)
    if when is None:
        return False
    return P.is_stale(when, minutes=STALE_MINUTES)


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
    # THE SAME BOARD, ALSO AS A TEXT (Megan 2026-09-15: "not instead- this is
    # in addition to"). Merged into the same destination list so cadence, the
    # due check, the per-destination markers and the one-room-failure-must-
    # not-cost-the-rest handling are the code that already exists.
    texts = P.approved_texts(book)
    can_text = _can_text()
    if texts and not can_text:
        # OUT LOUD. A machine that cannot text silently dropping every text
        # destination is a board somebody is waiting for that never arrives
        # and never errors.
        log("this machine cannot send iMessage, so %d office(s) with a text "
            "destination will get Slack only -- see gap_alerts.config."
            "TEXTING_MACHINES" % len(texts))
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

        # A BOARD BUILT ON FROZEN NUMBERS IS WORSE THAN NO BOARD.
        #
        # The row is the last thing that machine relayed, and nothing here
        # ever asked how old it was -- so an office whose agent had stopped
        # kept getting its last good reading re-rendered and re-sent, with a
        # fresh timestamp in the title every time. Confidently wrong, on a
        # cadence.
        #
        # Khalil Mansour, 2026-09-16: his agent died at 16:58 and his 5:12
        # board and 5:20 text both went out carrying 16:58's knocks. Nobody
        # reading them could have known.
        #
        # THE QUIET-MACHINE NUDGE ALREADY COVERS THE GAP, so stopping here
        # loses nobody any visibility -- it only stops us asserting a number
        # we cannot stand behind. The agent relays every couple of minutes,
        # so anything this old means it is not running at all.
        if _too_old(row[KN_RECEIVED]):
            log("%-10s last relayed at %s -- too old to post a board from"
                % (key, row[KN_RECEIVED] or "?"))
            continue

        dests = list(approved.get(key) or [])
        if can_text:
            # A TEXT FOLLOWS THE BOARD IT IS A COPY OF. The form never asks a
            # cadence for a group chat -- it is the same board, "as well as"
            # Slack, not a separate schedule -- so these arrive with none.
            # Zero is NOT "no cadence" here: it means the fixed 2:00/5:15/9:00
            # slots, so Carlos's group got one text at 14:05 because that
            # happened to be just past a slot, and his second campaign,
            # approved at 14:50, would have sent nothing until 17:15
            # (2026-09-15).
            beat = next((int(d.get("cadence_min") or 0) for d in dests
                         if int(d.get("cadence_min") or 0) > 0), 0)
            for t in (texts.get(key) or []):
                t = dict(t)
                if int(t.get("cadence_min") or 0) <= 0 and beat:
                    t["cadence_min"] = beat
                dests.append(t)
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

        # THE ROWS MUST BE THE CAMPAIGN THIS OFFICE IS ENROLLED AS. A pin can
        # fail to take and still serve a grid -- Calvin's board came back
        # Box-shaped under an ENERGYWELL heading and published, and nobody
        # reading it could have told (2026-09-02).
        # THE RELAYED GRID, NOT THE MAPPED ROWS. to_rows() normalises a
        # campaign's own columns into the shared board vocabulary -- B2B
        # AT&T's "corp/franchise - no opp" becomes "Sale" and
        # "Talked To - Not Interested" -- so by then the very thing that
        # identifies a campaign is gone. Checking the mapped rows refused
        # Carlos's B2B AT&T board on 2026-09-15 with "none of the campaign
        # signatures we know", while the grid his machine actually sent
        # carried the signature perfectly. It passed for Box only by luck.
        why = campaign_guard.check(getattr(office, "campaign", "") or "", raw)
        if why:
            log("%-10s NOT DRAWN — %s" % (key, why))
            if not _said_already("withheld", key, day, why):
                try:
                    from automations.icd_alerts import post as _P
                    # THE OFFICE KEY, not just the label. Two campaigns on one
                    # machine share a label -- "carlos's Local Office" was
                    # posted for both, and nobody reading it could tell which
                    # one was withheld.
                    _P._slack(O.OPS_CHANNEL,
                              ":rotating_light: *%s* (`%s`) — knocks board "
                              "withheld.\n> %s" % (office.label, key, why))
                except Exception:  # noqa: BLE001
                    pass
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
                if P.is_text_dest(d["channel_id"]):
                    _text(P.text_group_of(d["channel_id"]), boards,
                          _gaps_text(office, rows_for_board, now))
                else:
                    _upload(d["channel_id"], boards, comment)
                posted_at[d["channel_id"]] = now
                posted_total += 1
            except Exception as e:  # noqa: BLE001 — one room must not cost the rest
                where = d.get("channel_name") or d["channel_id"]
                log("%-10s FAILED to post to %s: %s: %s"
                    % (key, where, type(e).__name__, str(e)[:120]))
                if P.is_text_dest(d["channel_id"]) and not _said_already(
                        "text", key, day,
                        "%s|%s" % (where, type(e).__name__)):
                    # A GROUP NAME IS THE ONE THING NOBODY CAN CHECK FOR THEM.
                    # It is typed on a form, it cannot be verified from the
                    # machine that approves it, and a near-miss delivers
                    # nothing. So this goes where a person will see it rather
                    # than into a log.
                    try:
                        P._slack(O.OPS_CHANNEL,
                                 ":speech_balloon: *%s* — could not text "
                                 "their board to \u201c%s\u201d.\n> %s\n"
                                 "> Their Slack channels are unaffected. "
                                 "Check the group name is exactly right and "
                                 "that Lucy is in the chat."
                                 % (office.label, where, str(e)[:200]))
                    except Exception:  # noqa: BLE001
                        pass
        tab.update_cell(i, KN_POSTED + 1, json.dumps(
            {k: v.isoformat(timespec="seconds") for k, v in posted_at.items()}))

    if not send:
        log("\nDRY RUN -- nothing posted and nothing recorded.")
    return {"posted": posted_total}


def _said_already(kind: str, key: str, day: dt.date, detail: str) -> bool:
    """Has this exact complaint already gone to the channel today?

    THE POSTER RUNS EVERY TWO MINUTES. An alert with no memory is not an
    alert, it is a flood: one withheld board put the same paragraph into
    #claudecorrections dozens of times on 2026-09-15 and buried everything
    else in the channel. Keyed on the DETAIL as well as the office, so a
    second, different problem still gets through.

    Best effort -- failing to remember must never stop the work.
    """
    import hashlib
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / ".said.json"
        try:
            seen = json.loads(path.read_text())
        except (OSError, ValueError):
            seen = {}
        stamp = "%s|%s|%s|%s" % (
            kind, key, day.isoformat(),
            hashlib.sha1(detail.encode("utf-8", "replace")).hexdigest()[:12])
        if seen.get(stamp):
            return True
        # Yesterday's entries are not worth carrying.
        seen = {k: v for k, v in seen.items() if day.isoformat() in k}
        seen[stamp] = True
        path.write_text(json.dumps(seen))
        return False
    except Exception:  # noqa: BLE001
        return False


# WHAT A CAMPAIGN IS CALLED ON A BOARD. Named here rather than derived from
# the sign-up form's wording: splitting "AT&T Fiber — Internet & Phones" on
# the dash gives "Internet & Phones", which tells a reader nothing and is not
# what anybody calls it. The form's labels are written for an owner choosing
# from a list; a header beside a date needs the name people say out loud.
BOARD_CAMPAIGN_NAME = {
    "att": "AT&T Fiber",
    "nds": "NDS",
    "energy": "Energy Wells",
    "b2b_att": "B2B AT&T",
    "b2b_box": "B2B Box",
}


def _board_title(office) -> str:
    """The office, and WHICH CAMPAIGN this board is (Megan 2026-09-15: "we
    also need the campaign listed in the header box in case an ICD is getting
    multiples").

    Carlos runs two campaigns off one Mac mini and both boards land in
    #a-players-b2b. Titled by office alone they are two pictures with the same
    heading and different numbers, and the only way to tell them apart is to
    know his rep lists by heart.

    ALWAYS, not only when an office has two. A board that names its campaign
    only sometimes is one you have to check the absence of -- and the office
    that gains a second campaign tomorrow is the one whose old boards are
    already in the scrollback, unlabelled.
    """
    label = getattr(office, "label", "") or getattr(office, "key", "")
    campaign = (getattr(office, "campaign", "") or "").strip().lower()
    short = BOARD_CAMPAIGN_NAME.get(campaign, "")
    return "%s (%s)" % (label, short) if short else label


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
    from automations.icd_alerts import chan
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_dir = OUT_DIR / office.key
    # Chan's LAST week, so a rep is always reading their day against a pace.
    # His same-day line is impossible here -- the numbers come off the office's
    # own laptop, which cannot see his office -- and no comparison is not a
    # failed board, so this is allowed to come back empty.
    compare = chan.comparison_for(day, log=lambda *_: None)
    return knocks_render.render_knocks_boards(
        day, rows=rows, out_dir=out_dir,
        title_suffix=_board_title(office),
        extra_totals=[compare] if compare else None,
        # First knock goes green against THIS office's start time on THIS day.
        # The flat 1:30 PM target greened every Saturday first-knock on every
        # board, because no office starts at 1:30 on a Saturday.
        first_knock_green_at=knocks_render.first_knock_target(office, day),
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


def _gaps_text(office, rows: List[Dict], now: dt.datetime) -> str:
    """The gap list Raf's texts carry, for an ICD's own reps.

    Megan 2026-09-15, looking at Carlos's first text beside Raf's: "we're
    missing this part on these texts though". A board photo on a phone is a
    wall of small numbers; the list above it is the part somebody acts on, and
    it is the whole reason these go out as texts rather than sitting in Slack.

    BUILT FROM THE BOARD'S OWN ROWS, not a second read. Every rep's last knock
    is already on the row being drawn, so the minutes are arithmetic we
    already have -- and a separate pull could disagree with the picture
    directly beneath it.

    Formatted by gap_alerts.gap_text so an ICD's text and Raf's are the same
    message: longest gap first, "min" not "minutes", the clock on whoever is
    newly over.
    """
    try:
        from automations.gap_alerts import config as gc
        from automations.gap_alerts.run import gap_text
    except Exception:  # noqa: BLE001 — a missing list must not cost the board
        return ""

    gaps = []
    key = getattr(office, "key", "") or "?"
    for r in rows:
        name = str(r.get("Rep") or "").strip()
        last = str(r.get("Last Knock") or "").strip()
        if not name or not last:
            continue
        mins = _minutes_since(last, now)
        if mins is not None and mins >= gc.GAP_THRESHOLD_MIN:
            gaps.append({"name": name, "minutesSinceLastKnock": mins})
    if not gaps:
        # Nobody over the line is not an empty message -- it is no message.
        return ""
    # WHO IS NEWLY OVER, marked with the clock. This passed previous=set() and
    # first_of_day=True, which makes gap_text's `new = not first_of_day and
    # ...` false for everybody -- so the ICD texts never carried the marker at
    # all while Raf's did (Megan 2026-09-15). The clock is the difference
    # between "here are twelve names" and "these two just went quiet": without
    # it the list is undifferentiated and reads the same at 2pm and 6pm.
    before = _previous_gaps(key, now.date())
    text, names = gap_text(gaps, previous=before,
                           first_of_day=before is None)
    _remember_gaps(key, now.date(), names)
    return text


def _gaps_path():
    return OUT_DIR / ".gaps_seen.json"


def _previous_gaps(key: str, day: dt.date):
    """Who was on this office's last list today, or None if there wasn't one.

    None and empty-set are different: None means no list has gone out today,
    so EVERY name is simply the first list rather than twelve people who all
    just went quiet. gap_text takes that as first_of_day.
    """
    try:
        seen = json.loads(_gaps_path().read_text())
    except (OSError, ValueError):
        return None
    got = seen.get("%s|%s" % (day.isoformat(), key))
    return set(got) if got is not None else None


def _remember_gaps(key: str, day: dt.date, names) -> None:
    """Best effort -- failing to remember must never cost the text."""
    try:
        try:
            seen = json.loads(_gaps_path().read_text())
        except (OSError, ValueError):
            seen = {}
        seen = {k: v for k, v in seen.items() if k.startswith(day.isoformat())}
        seen["%s|%s" % (day.isoformat(), key)] = sorted(names or [])
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        _gaps_path().write_text(json.dumps(seen, indent=2, sort_keys=True))
    except Exception:  # noqa: BLE001
        pass


def _minutes_since(last_knock: str, now: dt.datetime):
    """Minutes between a board's "Last Knock" cell and now, or None.

    The cell is a wall clock in the OFFICE's own day ("2:47 PM"), so it is
    read against the same `now` the board was drawn with -- which knocks_post
    has already converted to that office's timezone.
    """
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            t = dt.datetime.strptime(last_knock.strip().upper(), fmt)
        except ValueError:
            continue
        when = now.replace(hour=t.hour, minute=t.minute, second=0,
                           microsecond=0)
        if when > now:            # a clock that reads ahead is bad data
            return None
        return int((now - when).total_seconds() // 60)
    return None


def _can_text() -> bool:
    """Is THIS machine allowed to send iMessage?

    Asked of gap_alerts.config, which is the one list, because an unconsented
    send does not fail -- it blocks on a permission dialog nobody is there to
    click, for about five minutes, every tick. A machine goes on that list
    only after a text has been SEEN arriving from the identity that sends.
    """
    try:
        from automations.gap_alerts import config as gc
        return bool(gc.can_text())
    except Exception:  # noqa: BLE001
        return False


def _text(group: str, boards, caption: str = "") -> None:
    """The board to an iMessage group, through the sender production uses.

    NOT our own AppleScript. text_post knows two things this would otherwise
    have to rediscover: resolve the group by NAME every time (a stored chat id
    goes stale the moment somebody is added, and sends into a thread nobody
    can see), and leave IMAGE_SEND_DELAY_S between sends because Messages
    uploads asynchronously and crowding it DROPS IMAGES SILENTLY.

    It raises on a name that matches nothing or more than one thing, which is
    what we want: texting an office's numbers into the wrong leaders' group is
    worse than not texting at all.

    NOT THE SLACK HEADING (Megan 2026-09-15: "we dont need that intro text on
    any texts - just the chart photo is fine"). In Slack that line earns its
    place: it is what the channel preview shows and what dates the post. In a
    group text the picture arrives whole, with the time already printed across
    the top of the board, so the sentence above it is only something to scroll
    past.

    The caption it DOES carry is the gap list -- the part somebody acts on,
    and the reason these go out as texts at all. send_to_group skips the text
    message entirely when there is none, so a quiet stretch sends the board
    alone rather than a header with nothing under it.
    """
    from automations.b2b_dispositions import text_post as tp
    tp.send_to_group(group, caption or "", list(boards), dry_run=False)


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
