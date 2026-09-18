"""OUR side: read what the ICD laptops relayed, decide what is new, post it.

THIS IS WHERE EVERY DECISION LIVES. The laptops report totals; nothing they do
can put a message in Slack. That is not politeness, it is the control Megan
asked for (2026-09-10, "we want to control the ecosystem"): an office is
switched off in `offices.py` or in the relay workbook's 'Relay Keys' tab, and
the next sweep it goes quiet -- with nothing to uninstall and no cooperation
needed from the ICD.

THE BASELINE RULE MOVED HERE from the laptop, and is stronger for it. 'Last
Posted JSON' lives on the relay row, so it survives a runner being re-imaged, a
laptop being restored from backup, and the same totals being relayed twice. The
worst a confused laptop can do is hand us numbers we have already seen, which
produces nothing.

  python -m automations.icd_alerts.post                 # dry run: show it
  python -m automations.icd_alerts.post --send          # actually post
  python -m automations.icd_alerts.post --office kash

DRY RUN IS THE DEFAULT and --send is the only way anything reaches Slack.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from automations.icd_alerts import offices as O
from automations.shared.credit_check_line import records_line
from automations.shared.sale_hype import shape as H_SHAPE
from automations.icd_alerts import rep_names as RN

# The relay workbook: 'Lucy Access App' (Megan supplied it 2026-09-11). The
# Apps Script in resources/icd-alerts-relay.gs is bound to THIS workbook, and
# its 'Relay Keys' tab is the list of who may hand anything in at all.
# Sheet1 is Megan's and is left alone.
RELAY_SPREADSHEET_ID = "1_5YGHhZ0gCYVZzHl7TPnP-6_75xaI0kcjPinQdVTlKg"
RELAY_TAB = "ICD Relay"

CHANNELS_TAB = "Office Channels"
FAULTS_TAB = "ICD Faults"
# The fault row, written by the laptop except for the last column, which
# is ours and is what stops one problem being announced twice.
F_OFFICE, F_DAY, F_STAGE, F_SUMMARY, F_DETAIL = 0, 1, 2, 3, 4
F_COUNT, F_FIRST, F_LAST, F_LOCAL, F_AGENT, F_PLATFORM = 5, 6, 7, 8, 9, 10
F_POSTED = 11
# Both halves are the same shape: what the office asked for, then what a
# human approved. A laptop writes only the asking columns.
CH_OFFICE, CH_OWNER, CH_ASKED, CH_ASKED_JSON, CH_ASKED_AT = 0, 1, 2, 3, 4
CH_APPROVED_JSON, CH_APPROVED = 5, 6
CH_KN_WANTED, CH_KN_JSON, CH_KN_HOURS = 7, 8, 9
CH_KN_APPROVED_JSON, CH_KN_APPROVED = 10, 11
CH_OV_NAME = 12
# TEXT DESTINATIONS. An office can have the same board sent to an iMessage
# group AS WELL AS its Slack channels (Megan 2026-09-15), so these sit beside
# the knocks columns rather than replacing them.
CH_TX_WANTED, CH_TX_JSON = 13, 14
CH_TX_APPROVED_JSON, CH_TX_APPROVED = 15, 16

# The prefix that makes a group chat look like a channel to the posting pass.
# Doing it this way means cadence, "is it due", the per-destination sent
# markers and the one-failure-must-not-cost-the-others handling are all the
# code that already exists, rather than a second copy that drifts.
TEXT_DEST_PREFIX = "imessage:"


def is_text_dest(channel_id: str) -> bool:
    return (channel_id or "").startswith(TEXT_DEST_PREFIX)


def text_group_of(channel_id: str) -> str:
    return (channel_id or "")[len(TEXT_DEST_PREFIX):]

COL_OFFICE, COL_DAY, COL_RECORDS = 0, 1, 2
COL_RECEIVED, COL_LOCAL_TIME, COL_AGENT = 3, 4, 5
COL_LAST_POSTED, COL_POSTED_AT = 6, 7
# APPENDED, not inserted. Sales arrived after offices were already relaying,
# and the deployed script and the sheet cannot be changed in the same instant
# -- so the new columns went on the END and every position above is untouched.
# An office still running the older agent simply leaves these blank.
COL_SALES, COL_LAST_POSTED_SALES = 8, 9
# {machine_id: {name, last}} -- merged by the relay, never overwritten, so an
# office running two computers shows both. Appended, like the sales columns,
# because the deployed script writes by POSITION.
COL_MACHINES = 10

# The knocks tab gained the same two facts, because the offices that only ever
# post knocks were the ones we knew nothing about.
KNOCKS_TAB = "ICD Knocks"
KN_AGENT, KN_MACHINES = 8, 9

# A laptop that has not checked in for this long is asleep, shut, or off wifi.
# Worth SAYING, never worth alerting the office about -- they cannot act on it
# and it is not their job to.
STALE_MINUTES = 45

# One poster at a time. Two overlapping runs would each read the same
# 'Last Posted' and each decide the same credit checks were new -- the one
# failure this design has no way to take back, because it happens in front of
# the office. launchd will not overlap a fast run, but a slow Sheets call is
# exactly when a second tick arrives.
LOCK_PATH = Path.home() / ".config" / "recruiting-report" / "icd_alerts_post.lock"
LOCK_STALE_MINUTES = 20

# When each office was last told it had gone quiet. REPEATED EVERY 30 MINUTES
# while it stays down (Megan 2026-09-12), not once a day.
#
# It was once a day, reasoning that a second message about a laptop somebody
# had already been asked to wake is nagging. That is true of a five-minute
# tick and false of a half-hour one: an office whose machine is off is losing
# its alerts the whole time, and one message at 11am that they scrolled past
# is not a fix. Half an hour is slow enough not to hector and often enough to
# be noticed.
WARNED_PATH = Path.home() / ".config" / "recruiting-report" / "icd_alerts_quiet.json"
NUDGE_REPEAT_MIN = 30
# 11am on the OFFICE'S clock. Their agent starts sweeping at 10:00 local, so
# by 11 it has had four chances to say hello -- silence then is a real problem,
# and it is early enough that a nudge still saves the day rather than reporting
# on a lost one. Nobody is helped by "they have not checked in" at 10:05.
QUIET_WARN_AFTER_HOUR = 11
QUIET_WARN_UNTIL_HOUR = 21


class RelayNotConfigured(RuntimeError):
    pass


# --- the pure part (unit-tested offline) ------------------------------------
def decide(records: Dict[str, int],
           last_posted: Optional[Dict[str, int]],
           name_for: Optional[Callable[[str], str]] = None
           ) -> Tuple[List[str], Dict[str, int], bool]:
    """(lines to post, what to record as posted, was this a baseline).

    BASELINE = we have never posted for this office/day. Everything the office
    has done so far reads as new, and announcing it would tell them at 3pm
    about credit checks from 9am as though they just happened. So the first
    pass records and stays silent. The AO sweep learned this by sending 42
    messages in one go on the day it shipped.

    Counts only ever move UP: a short or half-rendered grid on a laptop reads
    LOW, and taking that at face value would let the next good pass 'gain' the
    same credit checks again and ping twice about one event.
    """
    # `name_for` spells the rep the way her office does; the KEYS stay
    # SaraPlus's, because that is what 'Last Posted' is keyed by and a renamed
    # key would read as a new rep with a count of zero. See rep_names.
    show = name_for or (lambda n: n)
    records = {str(k): int(v) for k, v in (records or {}).items()}
    if last_posted is None:
        return [], records, True

    prev = {str(k): int(v) for k, v in last_posted.items()}
    merged = dict(prev)
    lines = []
    for rep, n in sorted(records.items()):
        was = prev.get(rep, 0)
        if n > was:
            lines.append(records_line(show(rep), n, n - was))
            merged[rep] = n
    return lines, merged, False


def decide_sales(sales: Dict, last_posted: Optional[Dict],
                 campaign=None) -> Tuple[List[str], Dict, bool]:
    """(hype lines, what to record as posted, was this a baseline).

    Same two rules the credit checks follow, for the same reasons. BASELINE:
    the first sight of a day announces nothing, or an office enrolling at 3pm
    would have every sale since lunchtime declared as if it had just landed.
    ONLY UP: a short or half-rendered grid reads LOW, and believing it would
    let the next good pass re-announce a sale that is already on the board.

    One line per REP, not per metric -- a rep who puts up an Int and two lines
    in the same sweep made ONE sale, and the tier is read off their whole day
    exactly as the AO board reads it.
    """
    from automations.shared import sale_hype as H

    # THE CAMPAIGN'S OWN METRIC NAMES, not AT&T's. Comparing a Box payload
    # against ("Int", "Int Up", "DTV", "NL") read every rep as all-zero, so
    # nothing ever "moved" and the channel stayed quiet with no error.
    names = H.shape(campaign).metrics
    sales = {str(k): {m: int(v.get(m, 0) or 0) for m in names}
             for k, v in (sales or {}).items()}
    if last_posted is None:
        return [], sales, True

    # A BACKLOG ARRIVING IN ONE TICK IS NOT LIVE ACTIVITY. When an office turns
    # sales on mid-day, its first payload carries everything sold since
    # morning, and the rule above cannot see it: something already recorded an
    # empty {} as "posted", so this reads as ordinary movement and the whole
    # day is declared at once. Cyrus, 2026-09-12: five sales announced in one
    # burst at 14:18, the oldest three hours stale.
    #
    # What separates the two cases is HOW MANY REPS MOVE AT ONCE. Reps do not
    # all sell inside the same two-minute tick, so a jump from nothing to
    # several reps is a backlog being handed over, while a genuine first sale
    # of the day is exactly one rep -- and that one still announces normally.
    if not last_posted and len([r for r, m in sales.items()
                                if any(m.values())]) > 1:
        return [], sales, True

    prev = {str(k): {m: int(v.get(m, 0) or 0) for m in names}
            for k, v in last_posted.items()}
    merged = {k: dict(v) for k, v in prev.items()}
    moved = []
    for rep, now_m in sorted(sales.items()):
        was = prev.get(rep) or {m: 0 for m in names}
        if any(now_m.get(m, 0) > was.get(m, 0) for m in names):
            moved.append(rep)
        merged[rep] = {m: max(now_m.get(m, 0), was.get(m, 0)) for m in names}
    return moved, merged, False


def is_stale(received: Optional[dt.datetime], now: Optional[dt.datetime] = None,
             minutes: int = STALE_MINUTES) -> bool:
    if not received:
        return True
    now = now or dt.datetime.now()
    return (now - received) > dt.timedelta(minutes=minutes)


# --- the sheet ---------------------------------------------------------------
class _Lock:
    """A pid lock that forgives a crash. Held for the length of one run."""

    def __enter__(self):
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOCK_PATH.exists():
            age = dt.datetime.now() - dt.datetime.fromtimestamp(
                LOCK_PATH.stat().st_mtime)
            if age < dt.timedelta(minutes=LOCK_STALE_MINUTES):
                self.held = False
                return self
            # Older than any real run: the holder died. Taking it is right --
            # the alternative is an office going silent until someone notices
            # a stale file.
            LOCK_PATH.unlink(missing_ok=True)
        LOCK_PATH.write_text(str(os.getpid()))
        self.held = True
        return self

    def __exit__(self, *exc):
        if getattr(self, "held", False):
            LOCK_PATH.unlink(missing_ok=True)
        return False


def check_ins(day: Optional[dt.date] = None, book=None) -> tuple:
    """({office: today's 'Received At' cell}, {every office that ever relayed})."""
    day = day or dt.date.today()
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)

    tab = book.worksheet(RELAY_TAB)
    values = tab.get_all_values()
    seen = {}
    # EVER, not just today. An office that has never relayed anything is not
    # QUIET -- it is not installed yet, and warning about it every afternoon
    # from the moment its row is added would teach us to ignore the warning
    # before the first real one arrived. It starts being watched the day its
    # laptop first says hello.
    ever = set()
    for row in values[1:]:
        if len(row) <= COL_DAY:
            continue
        key = (row[COL_OFFICE] or "").strip().lower()
        if not key:
            continue
        ever.add(key)
        if _day_key(row[COL_DAY]) == day.isoformat():
            seen[key] = (row[COL_RECEIVED] or "").strip()
    return seen, ever


def quiet_offices(day: Optional[dt.date] = None, minutes: int = STALE_MINUTES,
                  book=None) -> List[Dict]:
    """Enrolled offices whose laptop has not checked in lately, or at all.

    THE FAILURE THIS CATCHES IS SILENCE, and silence is the one an alerting
    system cannot see from the inside: a closed laptop and a quiet sales day
    produce exactly the same empty channel. Reported to us, never to the
    office -- they cannot act on it and it is not their job to.
    """
    seen, ever = check_ins(day, book=book)
    out = []
    for office in O.active():
        if office.key not in ever:
            continue                      # never installed; nothing to miss
        raw = seen.get(office.key)
        if raw is None:
            out.append({"office": office.key, "label": office.label,
                        "last": None, "reason": "has not checked in today"})
            continue
        when = _parse_received(raw)
        if is_stale(when, minutes=minutes):
            out.append({"office": office.key, "label": office.label,
                        "last": raw,
                        "reason": "last checked in %s" % (raw or "never")})
    return out


def _parse_when(text: str) -> Optional[dt.datetime]:
    """An ISO stamp we wrote ourselves, or None."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_received(cell: str) -> Optional[dt.datetime]:
    """The 'Received At' cell, however Sheets displays it."""
    cell = (cell or "").strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(cell, fmt)
        except ValueError:
            continue
    return None


def _relay_tab():
    if not RELAY_SPREADSHEET_ID:
        raise RelayNotConfigured(
            "post.RELAY_SPREADSHEET_ID is not set yet -- the relay workbook "
            "does not exist. Create it, deploy resources/icd-alerts-relay.gs "
            "as a web app, then put the workbook id here.")
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(RELAY_SPREADSHEET_ID).worksheet(RELAY_TAB)


def _day_key(cell: str) -> str:
    """The Day cell as 'YYYY-MM-DD', however Sheets chose to display it.

    gspread hands back the DISPLAYED text, and a Day column that Sheets has
    decided is a date displays as '1/1/2020'. Matching on the raw string then
    finds nothing and the office reads as having never relayed -- silence,
    which is the failure mode that looks exactly like a quiet day. The relay
    writes this column as text for the same reason; this is the belt to that
    pair of braces.
    """
    cell = (cell or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(cell, fmt).date().isoformat()
        except ValueError:
            continue
    return cell


def approved_channels(book=None) -> Dict[str, List]:
    """{office_key: [Channel]} for every office a human has signed off.

    APPROVED MEANS A PERSON RESOLVED IT. The office asks through the installer
    and that lands in the asking columns; this reads only our side of the
    sheet, so a laptop cannot approve itself into a channel. A LIST, because
    an office can want the pings in more than one room.
    """
    from automations.icd_alerts.offices import Channel
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(CHANNELS_TAB).get_all_values()
    except Exception:  # noqa: BLE001 — no tab yet is not a failure
        return {}

    out = {}
    for row in rows[1:]:
        if len(row) <= CH_APPROVED:
            continue
        key = (row[CH_OFFICE] or "").strip().lower()
        ok = (row[CH_APPROVED] or "").strip().upper() in ("TRUE", "YES", "Y")
        if not key or not ok:
            continue
        try:
            chans = json.loads(row[CH_APPROVED_JSON] or "[]")
        except ValueError:
            continue
        good = [Channel(c["channel_id"], c.get("channel_name") or c["channel_id"])
                for c in chans if c.get("channel_id")]
        if good:
            out[key] = good
    return out


def approved_knocks(book=None) -> Dict[str, List[Dict]]:
    """{office_key: [{channel_id, channel_name, cadence_min}]}, signed off.

    Read from OUR column, never from what the office asked for. The request
    carries a channel NAME somebody typed; this carries an id a person
    resolved and approved, which are not the same fact.
    """
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(CHANNELS_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for row in rows[1:]:
        if len(row) <= CH_KN_APPROVED:
            continue
        key = (row[CH_OFFICE] or "").strip().lower()
        ok = (row[CH_KN_APPROVED] or "").strip().upper() in ("TRUE", "YES", "Y")
        if not key or not ok:
            continue
        try:
            dests = json.loads(row[CH_KN_APPROVED_JSON] or "[]")
        except ValueError:
            continue
        good = [d for d in dests
                if d.get("channel_id") and int(d.get("cadence_min") or 0) >= 0]
        if good:
            out[key] = good
    return out


def approved_texts(book=None) -> Dict[str, List[Dict]]:
    """{office_key: [{channel_id, channel_name, cadence_min}]}, signed off.

    Shaped exactly like approved_knocks() so the posting pass can concatenate
    the two and treat them identically -- the channel_id is the group NAME
    behind TEXT_DEST_PREFIX.

    THE NAME IS THE ADDRESS, AND IT STAYS THE NAME. b2b_dispositions.text_post
    resolves a group by name on every single send because a chat id is
    regenerated whenever the membership changes, and a stale id does not raise
    -- Messages sends into a thread nobody can see. That is how the Texas de
    Brazil texts went missing for weeks. So nothing here ever stores an id.
    """
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(CHANNELS_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for row in rows[1:]:
        if len(row) <= CH_TX_APPROVED:
            continue
        key = (row[CH_OFFICE] or "").strip().lower()
        ok = (row[CH_TX_APPROVED] or "").strip().upper() in ("TRUE", "YES", "Y")
        if not key or not ok:
            continue
        try:
            groups = json.loads(row[CH_TX_APPROVED_JSON] or "[]")
        except ValueError:
            continue
        good = []
        for g in groups:
            name = (g.get("group") or "").strip() if isinstance(g, dict) else str(g).strip()
            if not name:
                continue
            good.append({"channel_id": TEXT_DEST_PREFIX + name,
                         "channel_name": name,
                         "cadence_min": int((g or {}).get("cadence_min") or 0)
                         if isinstance(g, dict) else 0})
        if good:
            out[key] = good
    return out


def set_knocks_cadence(office_key: str, minutes: int, book=None) -> bool:
    """Change how often an office's board posts. OUR COLUMN ONLY.

    NEVER TOUCH "Knocks: Wanted" OR ITS JSON. Those are the OFFICE's columns:
    their machine re-sends what it was installed with on every sweep, and the
    relay treats a disagreement as "they are asking for somewhere different"
    -- which CLEARS the approval. Cyrus's cadence was changed on 2026-09-15 by
    editing both columns so the sheet would not contradict itself, and the
    result was that his machine put its own number back, the relay un-approved
    him, and his board posted nothing for the rest of the day. Nothing said so.

    The poster only ever reads the approved column, so changing that one is
    both sufficient and safe. The two columns disagreeing is not a problem to
    tidy up -- it is the record of what they asked for versus what we granted.
    """
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)
    tab = book.worksheet(CHANNELS_TAB)
    key = office_key.strip().lower()
    for i, row in enumerate(tab.get_all_values()[1:], start=2):
        if (row[CH_OFFICE] or "").strip().lower() != key:
            continue
        try:
            dests = json.loads(row[CH_KN_APPROVED_JSON] or "[]")
        except ValueError:
            return False
        if not dests:
            return False
        for d in dests:
            d["cadence_min"] = int(minutes)
        tab.update(values=[[json.dumps(dests), "TRUE"]],
                   range_name="K%d:L%d" % (i, i))
        return True
    return False


def pending_texts(book=None) -> List[Dict]:
    """Offices that asked for their board as a text and are not signed off."""
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(CHANNELS_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for i, row in enumerate(rows[1:], start=2):
        row = list(row) + [""] * (CH_TX_APPROVED + 1 - len(row))
        ok = (row[CH_TX_APPROVED] or "").strip().upper() in ("TRUE", "YES", "Y")
        if ok:
            continue
        try:
            asked = json.loads(row[CH_TX_JSON] or "[]")
        except ValueError:
            asked = []
        if not asked:
            continue
        out.append({"row": i, "office": (row[CH_OFFICE] or "").strip(),
                    "groups": asked})
    return out


def pending_knocks(book=None) -> List[Dict]:
    """Offices that asked for a knocks board nobody has signed off yet."""
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(CHANNELS_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for i, row in enumerate(rows[1:], start=2):
        row = list(row) + [""] * (CH_KN_APPROVED + 1 - len(row))
        wanted = (row[CH_KN_WANTED] or "").strip()
        ok = (row[CH_KN_APPROVED] or "").strip().upper() in ("TRUE", "YES", "Y")
        if not wanted or wanted == "No knocks board" or ok:
            continue
        try:
            asked = json.loads(row[CH_KN_JSON] or "[]")
        except ValueError:
            asked = []
        out.append({"row": i, "office": (row[CH_OFFICE] or "").strip(),
                    "owner": (row[CH_OWNER] or "").strip(),
                    "wanted": wanted, "asked": asked,
                    "hours": (row[CH_KN_HOURS] or "").strip()})
    return out


def pending_requests(book=None) -> List[Dict]:
    """Offices that have asked for a channel nobody has approved yet."""
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(CHANNELS_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= CH_APPROVED:
            row = list(row) + [""] * (CH_APPROVED + 1 - len(row))
        approved = (row[CH_APPROVED] or "").strip().upper() in ("TRUE", "YES", "Y")
        if not (row[CH_ASKED] or "").strip() or approved:
            continue
        try:
            asked = json.loads(row[CH_ASKED_JSON] or "[]")
        except ValueError:
            asked = []
        out.append({"row": i, "office": (row[CH_OFFICE] or "").strip(),
                    "owner": (row[CH_OWNER] or "").strip(),
                    "wanted": (row[CH_ASKED] or "").strip(),
                    "asked": asked,
                    "asked_at": (row[CH_ASKED_AT] or "").strip()})
    return out


def _rows_for(day: dt.date, tab) -> List[Tuple[int, List[str]]]:
    """(1-based row number, row) for every relay row of `day`. The row number is
    carried because writing 'Last Posted JSON' back needs it -- and looking it
    up again later would be a second read of a sheet another office is writing
    to at the same time."""
    values = tab.get_all_values()
    out = []
    for i, row in enumerate(values[1:], start=2):
        if len(row) > COL_DAY and _day_key(row[COL_DAY]) == day.isoformat():
            out.append((i, row))
    return out


def _loads(cell: str) -> Optional[Dict[str, int]]:
    cell = (cell or "").strip()
    if not cell:
        return None
    try:
        return json.loads(cell)
    except ValueError:
        # Unreadable = treat as never posted. That costs one quiet baseline
        # pass, which is the safe direction: the alternative is announcing a
        # whole day at once.
        return None


# THE GIF BUDGET LIVES IN shared/sale_hype.py, not here -- Raf's board posts
# these same lines from another machine, and a cap only one of them honours is
# not a cap.
from automations.shared.sale_hype import (  # noqa: E402
    within_budget as _within_gif_budget, record_gifs as _record_gifs,
    gifs_sent as _gifs_sent, GIF_BUDGET)


def run(day: Optional[dt.date] = None, *, send: bool = False,
        only: Optional[str] = None, log=print) -> Dict:
    day = day or dt.date.today()
    tab = _relay_tab()
    approved = approved_channels(tab.spreadsheet)
    # ONE read for the whole tick. Per office it would be a read per office per
    # minute against a workbook the laptops are writing to.
    name_fixes = RN.load(tab.spreadsheet)
    rows = _rows_for(day, tab)
    if not rows:
        log("no offices have relayed anything for %s yet" % day.isoformat())
        return {"offices": 0, "posted": 0}

    posted = considered = 0
    for rownum, row in rows:
        key = (row[COL_OFFICE] or "").strip().lower()
        if only and key != only.strip().lower():
            continue
        office = O.get(key)
        if not O.is_enrolled(key):
            # Expected, not a fault: a revoked laptop keeps relaying for a
            # while and that is exactly what being revoked looks like.
            log("%-10s relayed but is not enrolled/active -- ignored" % key)
            continue
        considered += 1

        records = _loads(row[COL_RECORDS]) or {}
        last = _loads(row[COL_LAST_POSTED] if len(row) > COL_LAST_POSTED else "")
        show = RN.resolver(name_fixes, key)
        lines, merged, baseline = decide(records, last, show)
        # DOES THE PRE-SALE STEP COUNT ANYTHING REAL FOR THIS CAMPAIGN? On
        # Box it does not: one deal can leave several draft contracts behind
        # it, so the number would be wrong every time (Ryan McSpadden,
        # 2026-09-16). The state is still RECORDED -- `merged` goes to the
        # sheet either way -- so turning it back on announces what is new
        # from that moment rather than replaying the day.
        if not H_SHAPE(office.campaign).presale_ping:
            lines = []

        # Sales ride the same row and the same rules. An office still on the
        # older agent sends none, and this stays empty rather than erroring.
        sales = _loads(row[COL_SALES] if len(row) > COL_SALES else "") or {}
        last_sales = _loads(row[COL_LAST_POSTED_SALES]
                            if len(row) > COL_LAST_POSTED_SALES else "")
        sold, merged_sales, sales_baseline = decide_sales(
            sales, last_sales, office.campaign)
        hype_lines, gifs_used = [], 0
        if sold:
            from automations.shared import sale_hype as H
            hype_lines = [H.hype(show(rep) if show else rep,
                                 sales.get(rep) or {}, day, office.campaign)
                          for rep in sold]
            hype_lines, gifs_used = _within_gif_budget(hype_lines, day, key)

        if baseline:
            log("%-10s first relay of %s -- recording %d rep(s), posting nothing"
                % (key, day.isoformat(), len(records)))
        elif not lines and not hype_lines:
            log("%-10s nothing new (%d rep(s) tracked)" % (key, len(records)))
        else:
            targets, held = O.destinations(office, approved.get(key))
            log("%-10s %d new credit check line(s) -> %s%s"
                % (key, len(lines), ", ".join(t.name for t in targets),
                   "   [HELD -- no channel decided for this office]" if held else ""))
            for line in lines:
                log("    %s" % line)

        if not send:
            continue
        if hype_lines or lines:
            # SALES FIRST. A rep's sale is the louder news and the credit
            # checks are the early warning behind it; in one message the order
            # is the story.
            text = "\n".join(hype_lines + lines)
            targets, held = O.destinations(office, approved.get(key))
            if held:
                # Say whose they are and why they are here, because the person
                # reading them did not ask for them and cannot act on the
                # alerts themselves -- only on the routing.
                text = ("_%s has no Slack channel set yet, so these are coming "
                        "to you. Add their channel in "
                        "`automations/icd_alerts/offices.py` and they will go "
                        "straight there._\n\n%s" % (office.label, text))
            for channel in targets:
                # One failing room must not cost the others their alert, and
                # it must not stop 'Last Posted' being written either -- a
                # retry would re-announce everything to the rooms that DID get
                # it. Say which room failed and carry on.
                try:
                    _slack(channel.id, text)
                    posted += len(lines)
                    _record_gifs(day, key, gifs_used)
                    gifs_used = 0        # one room's worth, not one per room
                except Exception as e:  # noqa: BLE001
                    log("%-10s FAILED to post to %s: %s: %s"
                        % (key, channel.name, type(e).__name__, str(e)[:120]))
        if lines or hype_lines or baseline or sales_baseline:
            tab.update_cell(rownum, COL_LAST_POSTED + 1, json.dumps(merged))
            tab.update_cell(rownum, COL_LAST_POSTED_SALES + 1,
                            json.dumps(merged_sales))
            tab.update_cell(rownum, COL_POSTED_AT + 1,
                            dt.datetime.now().isoformat(timespec="seconds"))

    if not send:
        log("\nDRY RUN -- nothing posted and nothing recorded. Re-run with "
            "--send once the above looks right.")
    return {"offices": considered, "posted": posted}


ENROLLED_PATH = (Path.home() / ".config" / "recruiting-report"
                 / "icd_alerts_enrolled.json")


MACHINE_FACTS_PATH = (Path.home() / ".config" / "recruiting-report"
                      / "icd_machine_facts.json")
APPROVALS_PATH = (Path.home() / ".config" / "recruiting-report"
                  / "icd_last_approvals.json")


def _once_a_day(path: Path, key: str, day: dt.date) -> bool:
    """True if this exact thing has already been said today.

    Every alert in this module that fires from the poster needs this: the
    poster runs every two minutes, and a message with no memory is a flood
    rather than a message [[_said_already]].
    """
    stamp = "%s|%s" % (day.isoformat(), key)
    try:
        seen = json.loads(path.read_text())
    except (OSError, ValueError):
        seen = {}
    if seen.get(stamp):
        return True
    seen = {k: v for k, v in seen.items() if k.startswith(day.isoformat())}
    seen[stamp] = dt.datetime.now().isoformat(timespec="seconds")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(seen, indent=2, sort_keys=True))
    except OSError:
        pass
    return False


SIGNIN_WARNED_PATH = (Path.home() / ".config" / "recruiting-report"
                      / "icd_signin_asked.json")

# WHAT THE OFFICE IS TOLD, and WHERE. A DM to the owner, Megan and Eve --
# never the team channel (Megan 2026-09-15: "it should DM to the ICD, Eve, and
# I NOT the entire team channel"). A signed-out session is not the sales
# floor's business, and putting it in their channel is noise in the one room
# the boards are meant to own.
#
# IT NAMES THE MACHINE. Signing in anywhere else does nothing: Lucy keeps her
# own Chrome profile on purpose (config.py), so a session in Safari or in
# their everyday Chrome is invisible to her. They could sign in ten times and
# the sales would stay stopped -- and they would have no way to know why.
SIGNIN_ASK = (
    ":lock: *%s — Lucy cannot sign into %s.*\n"
    "%s stopped updating at %s. Nothing is lost — the numbers are still "
    "there, we just cannot see them.\n\n"
    "*This has to be done on the office computer running LucyECO* — the same "
    "one you set up.%s\n\n"
    "%s")

SIGNIN_PAGE = ("https://raffi127-ctrl.github.io/"
               "Alphalete-Reporting-Hub/signin.html")
INSTALL_PAGE = "https://raffi127-ctrl.github.io/Alphalete-Reporting-Hub/"

# THE FIX IS NOT THE SAME FOR ALL THREE, so the message must not pretend it
# is (Megan 2026-09-15: "we should build this alert message for sara+ and OV
# as well").
#
#   My Service Cloud has an authenticator. Nobody can type a code for them, so
#   a PERSON has to sign in inside Lucy's own browser -- and only there,
#   because she keeps her own Chrome profile (config.py). A session in Safari
#   is invisible to her.
#
#   SaraPlus and OwnerVille have no second factor. Lucy signs in fresh every
#   sweep with the saved password, so a failure means the PASSWORD is wrong or
#   changed -- and the fix is to run the installer again, which asks for it.
#   Sending them to sign in inside a browser would fix nothing.
SYSTEMS = {
    "servicecloud": {
        "name": "My Service Cloud",
        "what": "Sales",
        # The page itself says to have the authenticator ready, and says it
        # where it is actually needed. Repeating it here made the message
        # longer without making the ONE thing it has to convey -- which
        # computer to walk to -- any clearer.
        "why": "",
        "how": "Open this on that computer and press the button:\n" + SIGNIN_PAGE,
    },
    "saraplus": {
        "name": "SaraPlus",
        "what": "Credit checks and sales",
        "why": " The saved password is not being accepted — it has probably "
               "changed.",
        "how": "Open this on that computer and run it again; it will ask for "
               "the new password:\n" + INSTALL_PAGE,
    },
    "ownerville": {
        "name": "OwnerVille",
        "what": "Your knocks board",
        "why": " The saved password is not being accepted — it has probably "
               "changed.",
        "how": "Open this on that computer and run it again; it will ask for "
               "the new password:\n" + INSTALL_PAGE,
    },
}


def ask_office_to_sign_in(office_key: str, when: str = "", *,
                          system: str = "servicecloud",
                          send: bool = False, book=None, log=print) -> bool:
    """DM the owner, Megan and Eve that Lucy cannot sign into something.

    Ryan McSpadden on how often the authenticator is needed: "It saves
    typically, but it feels random when it logs me out" (2026-09-15). So this
    is not an edge case -- it will happen, and the office will not know. Their
    sales simply stop, which looks exactly like a slow week.

    ONCE A DAY. The sweep runs every couple of minutes and a session stays
    gone until somebody walks over to that computer.
    """
    spec = SYSTEMS.get(system) or SYSTEMS["servicecloud"]
    day = dt.date.today()
    # KEYED ON THE SYSTEM TOO. An office whose OwnerVille password changed and
    # whose Service Cloud then dropped has two different problems and two
    # different fixes; one telling the other to stay quiet would leave half
    # its numbers missing with nothing said.
    if _once_a_day(SIGNIN_WARNED_PATH, "signin|%s|%s" % (office_key, system),
                   day):
        return False
    office = O.get(office_key)
    label = getattr(office, "label", None) or office_key
    text = SIGNIN_ASK % (label, spec["name"], spec["what"],
                         when or "the last check-in", spec["why"], spec["how"])
    log(text)
    if not send:
        return False

    # DM, NOT THE TEAM'S ROOM (Megan 2026-09-15: "it should DM to the ICD,
    # Eve, and I NOT the entire team channel"). A signed-out session is not
    # the sales floor's business, and putting it in their channel is noise in
    # the one room the boards are meant to own.
    owner = getattr(office, "slack_user_id", "") or ""
    sent_to = []
    for uid in [owner] + list(O.APPROVERS):
        if not uid or uid in sent_to:
            continue
        try:
            _dm(uid, text)
            sent_to.append(uid)
        except Exception as e:  # noqa: BLE001 — one failed DM must not stop
            log("could not DM %s: %s" % (uid, type(e).__name__))
    if not owner:
        # WORTH SAYING. Without the owner's Slack id this reached us and not
        # the person who has to walk to the machine.
        log("no slack id on record for %s — only Megan and Eve were told"
            % office_key)
    return True


def warn_machine_facts(day: Optional[dt.date] = None, *, send: bool = False,
                       book=None, log=print) -> List[str]:
    """Say what we know about the machines, once a day.

    A NEW LAPTOP, AND NOTHING ELSE. laptop_offices() was written, tested and
    wired to nothing, so an office on a laptop was something Megan noticed by
    eye -- and a laptop closes and takes its channel quiet with nothing said.
    Offices already accepted on one (LAPTOP_ACKNOWLEDGED) are left out, so
    this fires for the one she has not seen.

    ONCE A DAY, and only when there is something. A standing list that has not
    changed is noise, and noise is what buried the real alerts this afternoon.
    """
    day = day or dt.date.today()
    lines = []

    laptops = laptop_offices(day, book=book)
    if laptops:
        lines.append("*On a laptop* — their channel stops when the lid closes:")
        for m in laptops:
            lines.append("   • %s — %s" % (m["office"], m["name"]))

    # NOT THE "too old to say what machine" LIST (Megan 2026-09-15: "We don't
    # need this"). It is true and it is not actionable: she knows which
    # offices are behind, and it fixes itself the moment they update. An alert
    # nobody can act on is the thing that teaches people to skim the channel,
    # which is how the ones that matter get missed. silent_machines() stays --
    # it is worth asking on purpose, just not worth saying every day.
    if not lines:
        return []
    for l in lines:
        log(l)
    if not send:
        return lines
    key = "machines|%s" % "|".join(sorted(m["office"] for m in laptops))
    if _once_a_day(MACHINE_FACTS_PATH, key, day):
        return lines
    _slack(O.OPS_CHANNEL,
           ":computer: *Machines worth knowing about.*\n" + "\n".join(lines)
           + "\n_Said once a day, and only when it changes._")
    return lines


def _approvals_now(book=None):
    """(ok, {office: {"board"|"alerts"|"texts"}}) from ONE read of the tab.

    WHY THIS EXISTS, and it is not tidiness. Each approved_* reader answers a
    failed read with {} -- the right call for a poster, where "I could not
    check" must never post to a room nobody approved. But warn_lost_approvals
    compared that {} against yesterday's snapshot and concluded every office
    on the roster had been switched off at once, then said so in the ops room:
    "Nothing posts for them until it is put back."

    2026-09-18, 10:02. Nine offices, every approval intact, nothing stopped.
    A single unlucky read, and the loudest possible message about it.

    ONE READ, not three. The detector called three readers that each opened
    the same tab, which is three chances to be rate-limited for one question
    -- and Sheets 429s on reads here, not only on writes.

    ok=False means WE COULD NOT TELL. It is not "nothing is approved", and the
    caller must not treat it as either an empty roster or a full one.
    """
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(CHANNELS_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return False, {}
    out: Dict[str, set] = {}
    for row in rows[1:]:
        key = (row[CH_OFFICE] or "").strip().lower() if row else ""
        if not key:
            continue
        def _on(flag: int, blob: int) -> bool:
            if len(row) <= flag:
                return False
            if (row[flag] or "").strip().upper() not in ("TRUE", "YES", "Y"):
                return False
            try:
                return bool(json.loads(row[blob] or "[]"))
            except ValueError:
                return False
        if _on(CH_KN_APPROVED, CH_KN_APPROVED_JSON):
            out.setdefault(key, set()).add("board")
        if _on(CH_APPROVED, CH_APPROVED_JSON):
            out.setdefault(key, set()).add("alerts")
        if _on(CH_TX_APPROVED, CH_TX_APPROVED_JSON):
            out.setdefault(key, set()).add("texts")
    return True, out


def warn_lost_approvals(day: Optional[dt.date] = None, *, send: bool = False,
                        book=None, log=print) -> List[str]:
    """An office that WAS switched on and now is not.

    "no knocks destination is approved yet" reads identically for an office
    waiting on Megan and one that was approved and has since been switched
    off. That ambiguity cost Cyrus his whole board on 2026-09-15: a cadence
    change re-wrote a column his machine owns, the relay read the
    disagreement as "they are asking for somewhere different", cleared his
    approval -- and the message that followed was the same one a brand new
    office produces.

    A new office is a nudge. An office that LOST an approval is a regression,
    and it is the difference between "somebody needs to press a button" and
    "something took this away".
    """
    day = day or dt.date.today()
    ok, now = _approvals_now(book)
    if not ok:
        # COULD NOT READ IS NOT "ALL GONE". Reporting it would say every
        # office had been switched off, and writing the snapshot would make
        # the next run believe it.
        log("could not read the approvals tab -- saying nothing this pass")
        return []

    try:
        before = json.loads(APPROVALS_PATH.read_text())
    except (OSError, ValueError):
        before = {}

    lost = []
    for key, had in sorted(before.items()):
        gone = set(had) - now.get(key, set())
        if gone:
            lost.append((key, sorted(gone)))

    # AND A SECOND GUARD, because ok=True only means the read RETURNED -- an
    # empty sheet, a renamed tab or a half-written row all parse fine. Every
    # office losing everything in one tick is not N independent regressions,
    # it is one thing wrong on our side.
    #
    # THREE, NOT "ALL". With one office enrolled, "all of them" and "the only
    # one" are the same sentence, and suppressing that would hide the exact
    # single-office regression this whole function was written for (Cyrus,
    # 2026-09-15). Three is small enough to catch a real sweep-wide failure
    # and large enough that it can never swallow one office going quiet.
    WHOLESALE = 3
    if (lost and before and not now
            and len(lost) == len(before) and len(lost) >= WHOLESALE):
        log("every office lost every approval at once -- that is a read "
            "problem, not %d offices being switched off" % len(lost))
        return []

    # Remember the CURRENT state either way, so a thing reported once is not
    # reported forever -- and so a restored approval quietly becomes normal.
    try:
        APPROVALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        APPROVALS_PATH.write_text(json.dumps(
            {k: sorted(v) for k, v in now.items()}, indent=2, sort_keys=True))
    except OSError:
        pass

    if not lost:
        return []
    lines = ["*%s* — lost: %s" % (key, ", ".join(gone)) for key, gone in lost]
    for l in lines:
        log("LOST APPROVAL: " + l)
    if not send:
        return lines
    key = "lost|%s" % "|".join("%s:%s" % (k, ",".join(g)) for k, g in lost)
    if _once_a_day(APPROVALS_PATH.with_suffix(".warned.json"), key, day):
        return lines
    _slack(O.OPS_CHANNEL,
           ":warning: *An office was switched ON and is now switched OFF.*\n"
           + "\n".join(lines)
           + "\n_This is not an office waiting for approval — it had one and "
             "it is gone. Nothing posts for them until it is put back._")
    return lines


def _seen_requests() -> Dict:
    try:
        return json.loads(ENROLLED_PATH.read_text())
    except (OSError, ValueError):
        return {}


def notify_pending(*, send: bool = False, book=None, log=print) -> List[Dict]:
    """Tell Megan when an office has enrolled and is waiting on her.

    THE APPROVAL WAS SOMETHING YOU HAD TO GO AND CHECK. An office installs,
    their request lands on a tab, and nothing anywhere says so -- which is
    workable for two offices on a call and useless at fifty, where the first
    sign of a forgotten approval is an owner asking why they see nothing
    (Megan 2026-09-12, having just enrolled two).

    Told ONCE per request. Keyed on what they actually asked for, so a changed
    answer is a new thing worth a second message and an unchanged one is not.
    """
    # AN ALERTS REQUEST FROM AN OFFICE WITH NO SARAPLUS IS NOT A REQUEST. Box,
    # Energy Wells and NDS have no credit checks and no sales, so the form
    # never asks them where those should post -- yet this told Megan that
    # "carlos hidalgo (carlos) asked for their credit-check alerts in Not sure
    # yet" and handed her a command that cannot do anything (2026-09-15).
    # Chasing an approval that does not exist is how the real ones get skimmed
    # past.
    alerts = [r for r in pending_requests(book)
              if _campaign_has_alerts(r.get("office", ""))]
    pending = alerts + [dict(r, knocks=True) for r in pending_knocks(book)]
    if not pending:
        return []

    seen = _seen_requests()
    fresh = []
    for r in pending:
        key = "%s:%s:%s" % (r["office"], "knocks" if r.get("knocks") else "alerts",
                            r.get("wanted", ""))
        if seen.get(key):
            continue
        r["_key"] = key
        fresh.append(r)
    if not fresh:
        return []

    for r in fresh:
        log("PENDING: %-10s %s %s"
            % (r["office"], "knocks" if r.get("knocks") else "alerts",
               r.get("wanted", "")))
    if not send:
        return fresh

    lines = [":inbox_tray: *An office is waiting on you.*"]
    for r in fresh:
        what = "knocks board" if r.get("knocks") else "credit-check alerts"
        lines.append("• *%s* (%s) asked for their %s in  `%s`"
                     % (r.get("owner") or r["office"], r["office"], what,
                        r.get("wanted") or "(not sure yet)"))
        lines.append("   `python -m automations.icd_alerts.approve %s%s`"
                     % (r["office"], " --knocks" if r.get("knocks") else ""))
    lines.append("_Nothing posts to their team until you do. Their laptop is "
                 "already relaying, so the data is not being lost._")
    _slack(O.OPS_CHANNEL, "\n".join(lines))

    ENROLLED_PATH.parent.mkdir(parents=True, exist_ok=True)
    for r in fresh:
        seen[r["_key"]] = dt.datetime.now().isoformat(timespec="seconds")
    ENROLLED_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True))
    return fresh


FAULT_THREADS_PATH = (Path.home() / ".config" / "recruiting-report"
                      / "icd_fault_threads.json")

# How a stage reads in a channel. The laptop sends the short word; nobody
# reading #claudecorrections should have to know our module names.
FAULT_STAGE_LABEL = {
    # Not posted in the ops room at all -- see notify_faults. Here so a stage
    # that somehow reaches the generic path still reads as English.
    "signin-servicecloud": "signing into My Service Cloud",
    "signin-saraplus": "signing into SaraPlus",
    "signin-ownerville": "signing into OwnerVille",
    "install": "during setup",
    "sweep": "reading SaraPlus",
    "knocks": "reading OwnerVille",
    "login": "signing in",
}


def _fault_threads() -> Dict:
    try:
        return json.loads(FAULT_THREADS_PATH.read_text())
    except (OSError, ValueError):
        return {}


def open_faults(day: Optional[dt.date] = None, book=None) -> List[Dict]:
    """Faults this office's laptop reported and we have not announced yet.

    ANNOUNCED ONCE, NOT WHILE IT LASTS. A broken sweep retries every couple of
    minutes and the relay counts the repeats into one row, so re-announcing on
    every recurrence would rebuild exactly the flood the threading fixed. The
    row's own Count carries "still happening"; the quiet nudge carries "this
    office is dark". This carries WHAT BROKE, once.
    """
    from automations.recruiting_report.fill import open_by_key

    day = day or dt.date.today()
    book = book or open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(FAULTS_TAB).get_all_values()
    except Exception:  # noqa: BLE001 — no tab until the first fault ever
        return []

    out = []
    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= F_POSTED or not (row[F_OFFICE] or "").strip():
            continue
        if _day_key(row[F_DAY]) != day.isoformat():
            continue
        if (row[F_POSTED] or "").strip():
            continue
        out.append({
            "rownum": i,
            "office": (row[F_OFFICE] or "").strip().lower(),
            "stage": (row[F_STAGE] or "").strip(),
            "summary": (row[F_SUMMARY] or "").strip(),
            "detail": (row[F_DETAIL] or "").strip(),
            "count": (row[F_COUNT] or "").strip(),
            "first": (row[F_FIRST] or "").strip(),
            "platform": (row[F_PLATFORM] or "").strip(),
        })
    return out


def notify_faults(day: Optional[dt.date] = None, *, send: bool = False,
                  book=None, log=print) -> List[Dict]:
    """Put what broke on an ICD laptop in front of us, once per fault.

    Megan 2026-09-13: "build the installer failure reporting". The gap it
    closes: an office that breaks goes SILENT, and silence names neither the
    cause nor the step. Working Cyrus's outage out by elimination on 2026-09-12
    took a call; office #12 will not get a call.

    One thread per office per day, like the quiet nudge, for the same reason --
    a laptop with a broken sweep and a broken knocks read is two faults, and
    two top-level posts per office does not scale past a handful of them.
    """
    from automations.recruiting_report.fill import open_by_key

    day = day or dt.date.today()
    book = book or open_by_key(RELAY_SPREADSHEET_ID)
    faults = open_faults(day, book=book)
    if not faults:
        return []

    for f in faults:
        log("FAULT: %-10s %s -- %s" % (f["office"], f["stage"], f["summary"]))
    if not send:
        return faults

    threads = _fault_threads()
    key_for = lambda f: "%s|%s" % (day.isoformat(), f["office"])   # noqa: E731
    tab = book.worksheet(FAULTS_TAB)
    stamp = dt.datetime.now().isoformat(timespec="seconds")

    for f in faults:
        # A LOST SESSION IS NOT A LAPTOP FAULT. It is the one failure here
        # that needs a person to walk to a specific computer, and posting it
        # in the ops room puts it in front of everyone except them. The
        # laptop names the system in its stage -- "signin-servicecloud" --
        # and this sends the DM that asks the owner, Megan and Eve instead.
        #
        # ask_office_to_sign_in existed from 2026-09-15 and NOTHING CALLED
        # IT, which is the same way the laptop and silent-machine detectors
        # sat dead: written, tested, shipped, never reached. This is the call.
        if str(f["stage"] or "").startswith("signin-"):
            system = f["stage"].split("-", 1)[1]
            try:
                ask_office_to_sign_in(f["office"], f.get("first") or "",
                                      system=system, send=True, book=book,
                                      log=log)
                tab.update_cell(f["rownum"], F_POSTED + 1, stamp)
            except Exception as e:  # noqa: BLE001 — one must not stop the rest
                log("could not ask %s to sign in: %s: %s"
                    % (f["office"], type(e).__name__, str(e)[:100]))
            continue

        office = O.get(f["office"])
        label = office.label if office else f["office"]
        where = FAULT_STAGE_LABEL.get(f["stage"], f["stage"] or "on the laptop")
        parent = threads.get(key_for(f))
        head = (":rotating_light: *%s* — something broke %s." % (label, where)
                if not parent else
                "*Also %s:*" % where)
        body = [head, "> %s" % f["summary"]]
        if f["count"] and f["count"] not in ("1", ""):
            body.append("_Happened %s times, first at %s._"
                        % (f["count"], f["first"] or "?"))
        if f["platform"]:
            body.append("_%s_" % f["platform"])
        if not parent:
            body.append("_The office was not asked to send anything — their "
                        "laptop reported this by itself._")
        text = "\n".join(body)
        try:
            ts = _slack(O.OPS_CHANNEL, text, thread_ts=parent)
            if not parent and ts:
                threads[key_for(f)] = ts
                parent = ts
            if f["detail"]:
                # THE TRACEBACK GOES IN THE THREAD, never the channel. It is
                # for whoever picks the ticket up, and it is the wrong size
                # for a room people are scanning.
                _slack(O.OPS_CHANNEL, "```%s```" % f["detail"][:2800],
                       thread_ts=parent or ts)
        except Exception as e:  # noqa: BLE001 — one fault must not stop the rest
            log("could not post fault for %s: %s: %s"
                % (f["office"], type(e).__name__, str(e)[:100]))
            continue
        try:
            tab.update_cell(f["rownum"], F_POSTED + 1, stamp)
        except Exception as e:  # noqa: BLE001
            # If this fails we would re-announce next tick. Say so rather than
            # letting it look like a duplicate bug later.
            log("posted the fault but could not mark it: %s" % type(e).__name__)

    FAULT_THREADS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAULT_THREADS_PATH.write_text(json.dumps(threads, indent=2, sort_keys=True))
    return faults


SIGNUPS_SEEN_PATH = (Path.home() / ".config" / "recruiting-report"
                     / "icd_alerts_signups_seen.json")


def _campaign_has_alerts(office_key: str) -> bool:
    """Does this office's campaign produce credit checks or sales at all?

    SARAPLUS IS NO LONGER THE ONLY ANSWER. This was written when an office
    with no SaraPlus had no sales full stop, so asking Megan to approve their
    alerts channel was chasing an approval for something that could never
    post. Box sells through My Service Cloud (2026-09-15), so a Box office
    now has sales, has hype lines, and needs a room for them -- and this
    guard would have kept their request off the pending list forever, with
    the office having answered the question at install and simply never
    hearing back.

    Unknown counts as YES: an office we cannot place should still be chased
    rather than silently dropped off the list.
    """
    try:
        from automations.icd_signup import store as _st
        from automations.icd_signup.schema import uses_saraplus
        rec = _st.get((office_key or "").strip().lower())
        if not rec:
            return True
        campaign = str(rec.campaign or "").strip().lower()
        from automations.icd_alerts.config import SERVICECLOUD_CAMPAIGNS
        return uses_saraplus(campaign) or campaign in SERVICECLOUD_CAMPAIGNS
    except Exception:  # noqa: BLE001
        return True


def notify_new_signups(*, send: bool = False, book=None, log=print) -> List:
    """Announce offices that filled the sign-up form. FROM HERE, NOT THE FORM.

    The form posted its own ping and it never arrived. Megan's own sign-up
    landed perfectly on the tab -- row, key, setup link -- and nothing reached
    the corrections channel, so the only way to know an office had signed up
    was to go and look at a spreadsheet (2026-09-13).

    THE FORM IS THE WRONG PLACE TO POST FROM, and that is the real lesson. It
    runs on Streamlit Cloud with whatever token is in that app's secrets, in a
    Slack workspace it is otherwise a stranger to: a bot that is not in the
    channel, a scope nobody granted, a secret that expires -- three ways to be
    silent, none of them visible from here. This poster already runs every
    couple of minutes on a Lucy that holds Lucy Reporting's token and already
    posts to this exact channel. Announcing from the machine that is already
    talking removes the whole class of failure.

    Told ONCE per office, keyed on when they submitted, so a resubmission is a
    new thing worth saying and a rerun of this is not.
    """
    from automations.icd_signup import request_notify as RN
    from automations.icd_signup import store as SS

    try:
        pending = SS.pending(book)
    except Exception as e:  # noqa: BLE001 — no tab yet, or Sheets is down
        log("could not read sign-ups: %s" % type(e).__name__)
        return []
    if not pending:
        return []

    try:
        seen = json.loads(SIGNUPS_SEEN_PATH.read_text())
    except (OSError, ValueError):
        seen = {}

    fresh = [r for r in pending
             if seen.get("%s|%s" % (r.office_key, r.submitted_at)) is None]
    if not fresh:
        return []

    for r in fresh:
        log("SIGN-UP: %-10s %s" % (r.office_key, r.owner))
    if not send:
        return fresh

    stamp = dt.datetime.now().isoformat(timespec="seconds")
    for r in fresh:
        # Their link, rebuilt from the key we already gave them, so Megan can
        # re-send it without going to look the key up.
        link = ""
        try:
            keys = {row[0].strip().lower(): (row[1] or "").strip()
                    for row in (book or _book_for_keys()).worksheet(
                        "Relay Keys").get_all_values()[1:] if row and row[0]}
            if keys.get(r.office_key):
                link = SS.setup_link(keys[r.office_key])
        except Exception:  # noqa: BLE001 — the announcement matters more
            pass
        head, detail = RN.lines(r, link)
        try:
            ts = _slack(O.OPS_CHANNEL, head)
            _slack(O.OPS_CHANNEL, "\n".join(detail), thread_ts=ts)
        except Exception as e:  # noqa: BLE001 — one office must not stop the rest
            log("could not announce %s: %s: %s"
                % (r.office_key, type(e).__name__, str(e)[:120]))
            continue
        seen["%s|%s" % (r.office_key, r.submitted_at)] = stamp

    SIGNUPS_SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNUPS_SEEN_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True))
    return fresh


def _book_for_keys():
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(RELAY_SPREADSHEET_ID)


def run_requested_approvals(*, send: bool = False, book=None, log=print) -> List:
    """Do the approving a click asked for, and say what happened.

    THE CLICK CANNOT DO THIS ITSELF. Approving resolves Slack channels, checks
    Lucy is in each one and writes the sign-off; the form runs on Streamlit
    Cloud with a token that is a stranger to the workspace -- which is exactly
    how the sign-up ping failed. So the browser marks the row and this runs
    the real thing, on the machine that already holds the right token, with
    every check intact.

    REPORTS BACK EITHER WAY. A click that quietly did nothing is worse than a
    command that printed an error, because the person who clicked has already
    walked away believing the office is live.
    """
    from automations.icd_signup import approve as SA
    from automations.icd_signup import store as SS
    from automations.icd_signup.schema import STATUS_PENDING

    try:
        waiting = SS.approval_requested(book)
    except Exception as e:  # noqa: BLE001
        log("could not read approval requests: %s" % type(e).__name__)
        return []
    if not waiting:
        return []

    done = []
    for rec in waiting:
        log("APPROVE REQUESTED: %s (%s)" % (rec.office_key, rec.owner))
        if not send:
            done.append(rec)
            continue
        said = []
        try:
            # Put it back to pending FIRST. If this run dies halfway, the next
            # tick must not try again forever -- a person can click again,
            # and a loop that re-approves every two minutes cannot be seen.
            SS.set_status(rec.office_key, STATUS_PENDING,
                          note="approving…", book=book)
            rc = SA.approve(rec.office_key, log=said.append)
        except Exception as e:  # noqa: BLE001 — one office must not stop the rest
            rc, said = 1, said + ["%s: %s" % (type(e).__name__, str(e)[:200])]
        tail = "\n".join(str(x) for x in said[-12:]) or "(no output)"
        head = ("✅ *%s* is live — approved from the link."
                % (rec.owner or rec.office_key)
                if rc == 0 else
                ":x: *%s* could not be approved yet." % (rec.owner or rec.office_key))
        try:
            ts = _slack(O.OPS_CHANNEL, head)
            _slack(O.OPS_CHANNEL, "```%s```" % tail[:2800], thread_ts=ts)
        except Exception as e:  # noqa: BLE001
            log("approved %s but could not say so: %s"
                % (rec.office_key, type(e).__name__))
        done.append(rec)
    return done


def machines_for(row: List[str], col: Optional[int] = None) -> Dict:
    """{machine_id: {name, last}} off a relay OR knocks row. Never raises.

    The column differs between the two tabs, and both carry this now: an
    office with no SaraPlus never writes to the relay tab, so its machine was
    only ever described on the knocks hand-over.
    """
    col = COL_MACHINES if col is None else col
    try:
        out = json.loads(row[col] or "{}") if len(row) > col else {}
    except (TypeError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def stale_machines(row: List[str], now: Optional[dt.datetime] = None,
                   minutes: int = STALE_MINUTES) -> List[Dict]:
    """The machines on this row that have stopped, when others have NOT.

    THE CASE THE OFFICE-LEVEL NUDGE CANNOT SEE. An office that installs on two
    computers keeps relaying while either one lives, so the office looks alive
    and nobody is told that half its redundancy is gone. That is precisely the
    situation somebody set up a second machine to avoid.

    Returns nothing when every machine is quiet -- that is the whole office
    being down, which warn_quiet already says, and saying it twice in two
    different shapes is how people stop reading both.
    """
    seen = machines_for(row)
    if len(seen) < 2:
        return []
    now = now or dt.datetime.now()
    out, alive = [], 0
    for mid, info in seen.items():
        when = _parse_when(str((info or {}).get("last") or "").replace("Z", "")[:19])
        if when is None:
            continue
        if (now - when) > dt.timedelta(minutes=minutes):
            out.append({"id": mid, "name": (info or {}).get("name") or mid,
                        "last": when})
        else:
            alive += 1
    return out if alive else []


MACHINES_WARNED_PATH = (Path.home() / ".config" / "recruiting-report"
                        / "icd_alerts_machines_warned.json")


def warn_stale_machines(day: Optional[dt.date] = None, *, send: bool = False,
                        now: Optional[dt.datetime] = None, book=None,
                        log=print) -> List[Dict]:
    """Say when ONE of an office's machines has stopped and another has not.

    The office-level nudge cannot see this: the office keeps relaying while
    either computer lives, so it looks alive. Somebody who set up a second
    machine as a backup has quietly lost the backup, and the first they would
    know is the day the remaining one goes down too.

    TOLD TO US, NOT TO THEM, and once per machine per day. Their numbers are
    still arriving -- nothing is broken from where they sit -- so this is a
    thing to mention, not a thing to chase somebody about.
    """
    from automations.recruiting_report.fill import open_by_key

    day = day or dt.date.today()
    now = now or dt.datetime.now()
    book = book or open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(RELAY_TAB).get_all_values()
    except Exception as e:  # noqa: BLE001
        log("could not read the relay tab: %s" % type(e).__name__)
        return []

    found = []
    for row in rows[1:]:
        if not row or not (row[COL_OFFICE] or "").strip():
            continue
        if _day_key(row[COL_DAY]) != day.isoformat():
            continue
        key = (row[COL_OFFICE] or "").strip().lower()
        for m in stale_machines(row, now):
            found.append(dict(m, office=key))
    if not found:
        return []

    try:
        warned = json.loads(MACHINES_WARNED_PATH.read_text())
    except (OSError, ValueError):
        warned = {}
    today = day.isoformat()
    fresh = [f for f in found
             if warned.get("%s|%s|%s" % (today, f["office"], f["id"])) is None]
    if not fresh:
        return []

    for f in fresh:
        log("MACHINE QUIET: %-10s %s (last %s)"
            % (f["office"], f["name"], f["last"].strftime("%H:%M")))
    if not send:
        return fresh

    stamp = now.isoformat(timespec="seconds")
    for f in fresh:
        office = O.get(f["office"])
        label = office.label if office else f["office"]
        text = (":desktop_computer: *%s* — one of their computers has stopped, "
                "the other is still going.\n"
                "> *%s* last checked in at %s.\n"
                "_Their numbers are still arriving, so nothing is missing "
                "right now — but the backup they set up is not there any "
                "more._" % (label, f["name"], f["last"].strftime("%H:%M")))
        try:
            _slack(O.OPS_CHANNEL, text)
        except Exception as e:  # noqa: BLE001
            log("could not post machine notice: %s" % type(e).__name__)
            continue
        warned["%s|%s|%s" % (today, f["office"], f["id"])] = stamp

    MACHINES_WARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Yesterday's keys are noise; keep a few days so a restart does not
    # re-announce everything.
    for k in sorted(warned)[:-40]:
        warned.pop(k, None)
    MACHINES_WARNED_PATH.write_text(json.dumps(warned, indent=2, sort_keys=True))
    return fresh


# OFFICES ALLOWED TO STAY ON A LAPTOP, and who decided.
#
# Not a loophole -- the opposite. The point of finding laptops is to catch the
# NEXT one, and a detector that keeps reporting the laptop everybody already
# agreed to is one that gets ignored, taking the new laptop down with it. An
# office in here has been looked at and accepted, gaps and all.
LAPTOP_ACKNOWLEDGED = {
    "cyrus": "Megan, 2026-09-15 — the only office on a laptop; accepted "
             "knowing the lid closing takes his channel quiet.",
}


def laptop_offices(day: Optional[dt.date] = None, book=None,
                   include_acknowledged: bool = False) -> List[Dict]:
    """Offices relaying from a machine with a battery.

    The installer turns laptops away now, but every office enrolled BEFORE
    that rule existed is still on whatever they had -- and a laptop is the
    single most likely reason a channel goes quiet. This makes them visible
    without asking anybody what is on their desk.

    AN EMPTY LIST IS NOT AN ALL-CLEAR. Only agent icd_alerts/3 and later say
    what machine they are; anything older sends no answer, and an office that
    never said is not counted here. The offices most likely to be on a laptop
    are the ones who enrolled earliest, which are exactly the ones whose agent
    is too old to admit it -- so read a zero as "nobody has told us", and use
    silent_machines() to see who still cannot answer the question.

    Offices in LAPTOP_ACKNOWLEDGED are left out unless asked for, so what
    comes back is the list worth acting on.
    """
    from automations.recruiting_report.fill import open_by_key

    day = day or dt.date.today()
    book = book or open_by_key(RELAY_SPREADSHEET_ID)
    rows = []
    for tab, col in ((RELAY_TAB, COL_MACHINES), (KNOCKS_TAB, KN_MACHINES)):
        # BOTH TABS. An office with no SaraPlus never writes to the relay tab
        # at all, so reading only that one answered "no laptops" while every
        # Box, Energy Wells and NDS office was simply unexamined.
        try:
            got = book.worksheet(tab).get_all_values()
        except Exception:  # noqa: BLE001
            continue
        for r in got[1:]:
            rows.append((r, col))
    out = []
    for row, mcol in rows:
        if not row or not (row[COL_OFFICE] or "").strip():
            continue
        for mid, info in (machines_for(row, mcol) or {}).items():
            if isinstance(info, dict) and info.get("desktop") is False:
                office = (row[COL_OFFICE] or "").strip().lower()
                if not include_acknowledged and office in LAPTOP_ACKNOWLEDGED:
                    continue
                out.append({"office": office,
                            "id": mid,
                            "name": (info or {}).get("name") or mid,
                            "day": _day_key(row[COL_DAY]),
                            "acknowledged": office in LAPTOP_ACKNOWLEDGED})
    return out


def silent_machines(day: Optional[dt.date] = None, book=None) -> List[Dict]:
    """Offices whose agent is too old to say what machine it runs on.

    The blind spot behind laptop_offices(). An office here has not been
    cleared -- it simply cannot answer yet, and will start answering the
    moment it updates.
    """
    from automations.recruiting_report.fill import open_by_key

    day = day or dt.date.today()
    book = book or open_by_key(RELAY_SPREADSHEET_ID)
    try:
        rows = book.worksheet(RELAY_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return []
    # ONE ANSWER PER OFFICE, FROM ITS NEWEST ROW. The tab keeps a row per
    # office per day, so an office that has since updated still has old rows
    # sitting behind it -- reading every row reported Kash as unable to answer
    # on the strength of a row from agent 1, days after he was on agent 3.
    latest: Dict[str, Dict] = {}
    for row in rows[1:]:
        if not row or not (row[COL_OFFICE] or "").strip():
            continue
        office = (row[COL_OFFICE] or "").strip().lower()
        day_key = _day_key(row[COL_DAY])
        # Strictly older loses. On the SAME day the later row wins, because
        # rows are appended in order -- so a re-relay after an update beats
        # the morning's row instead of losing to it.
        if office in latest and day_key < latest[office]["day"]:
            continue
        machines = machines_for(row) or {}
        told = [m for m in machines.values()
                if isinstance(m, dict) and m.get("desktop") is not None]
        agent = (row[COL_AGENT] or "").strip() if len(row) > COL_AGENT else ""
        latest[office] = {"office": office,
                          "agent": agent or "unknown",
                          "day": day_key,
                          "told": bool(told)}
    return [v for v in latest.values() if not v["told"]]


def _warned() -> Dict:
    try:
        return json.loads(WARNED_PATH.read_text())
    except (OSError, ValueError):
        return {}


# TWO OPENINGS, because they are two different facts and the office knows
# which one is true. "Hasn't checked in today" sent to somebody whose machine
# ran all morning and stopped at 10:56 is wrong in a way they will notice, and
# a nudge that gets the basics wrong is one they stop reading.
NUDGE_NEVER = ("your Lucy Reports computer hasn't checked in at all today, so "
               "your office's alerts aren't running")
NUDGE_STOPPED = ("your Lucy Reports computer has gone quiet — it last checked "
                 "in at %s, so your office's alerts have stopped")

OWNER_NUDGE = (
    "Hi %s — %s.\n\n"
    "It's almost always one of these:\n"
    "  • %s\n"
    "  • %s\n"
    "  • it's off wifi\n\n"
    "Sort any of those and it picks itself up within a few minutes. Nothing is "
    "lost in the meantime. If it's none of those, please DM Megan & Eve to "
    "help with troubleshooting.")


def sales_system_for(office) -> str:
    """What THIS office's numbers come from, in their own words.

    'SaraPlus is cumulative' was written into the quiet notice when every
    office was AT&T. Roshan sells Box and reads My Service Cloud; she was told
    about a system her office has never touched (2026-09-18). It is the same
    shape as every other non-AT&T bug here -- a campaign that is not att
    falling through a path written as though it were.
    """
    from automations.icd_alerts import config as C
    campaign = (getattr(office, "campaign", "") or "att").strip().lower()
    if campaign in C.NO_SARAPLUS:
        return SYSTEMS["servicecloud"]["name"]
    return SYSTEMS["saraplus"]["name"]


def laptop_keys(book=None) -> set:
    """Offices we KNOW are on a laptop. Read once, not once per office."""
    try:
        return {d.get("office") for d in
                laptop_offices(book=book, include_acknowledged=True)
                if d.get("office")}
    except Exception:  # noqa: BLE001 — never lose a nudge to this
        return set()


def machine_words(laptop: bool = False) -> Dict[str, str]:
    """What to call this office's computer, and how it goes to sleep.

    "wake it and leave the lid open" is advice for a laptop. Roshan runs an
    iMac, and Megan's answer to the nudge was exactly the right one: "ROshan
    has an Imac so shouldn't be logged out". A nudge that gets the basics
    wrong is one people stop reading -- which the comment above NUDGE_NEVER
    already says, about a different detail.

    DEFAULTS TO THE DESKTOP WORDING, because it is the one that is never
    absurd: telling somebody with a laptop that their computer may be
    switched off is merely incomplete, while telling an iMac owner to leave
    the lid open reads as a message meant for somebody else.
    """
    if laptop:
        return {"noun": "laptop",
                "asleep": "the laptop is asleep or shut — wake it and leave "
                          "the lid open",
                "power": "it's unplugged — it has to be on power to stay awake"}
    return {"noun": "computer",
            "asleep": "the computer is asleep — wake it with the mouse or "
                      "keyboard",
            "power": "it's switched off, or lost power"}


def _nudge_text(first: str, quiet: Dict, laptop: bool = False) -> str:
    """The nudge, opening with whichever thing actually happened."""
    last = (quiet.get("last") or "").strip()
    w = machine_words(laptop)
    if quiet.get("last") and "not checked in" not in (quiet.get("reason") or ""):
        # Just the clock, not the date -- they are reading this today.
        stamp = last.split(" ")[-1] if " " in last else last
        opened = NUDGE_STOPPED % stamp
    else:
        opened = NUDGE_NEVER
    return OWNER_NUDGE % (first, opened, w["asleep"], w["power"])


def warn_quiet(day: Optional[dt.date] = None, *, send: bool = False,
               now: Optional[dt.datetime] = None, log=print) -> List[Dict]:
    """Nudge the OFFICE, and tell us. 11am on their own clock.

    I built this to warn us only, reasoning that an ICD cannot act on it. That
    was wrong for THIS failure and Megan said so (2026-09-12): a laptop that is
    asleep, shut or unplugged is the one thing only they can fix, and it is
    fixed in ten seconds. Telling the person who can act is the whole point.

    REPEATED EVERY 30 MINUTES while the machine stays down. One message they
    scrolled past is not a fix, and an office whose laptop is off is losing
    its alerts the entire time -- but a message per tick would be a dozen an
    hour, which is how a useful nudge becomes one people mute.
    """
    now = now or dt.datetime.now()
    day = day or now.date()
    if now.weekday() == 6:               # nobody is selling on Sunday
        return []

    quiet = quiet_offices(day)
    # ONCE, not once per office: which of these run a laptop decides whether
    # the advice mentions a lid. Read here so a quiet morning costs one call.
    laptops = laptop_keys()

    data = _warned()
    sent = data.get(day.isoformat()) or {}
    if isinstance(sent, list):          # the oldest once-a-day shape
        sent = {k: "" for k in sent}
    sent = dict(sent)

    def _last_at(v):
        # THREE SHAPES, because this state file outlives its own format: a
        # bare timestamp string (the every-30-minutes version) and the dict
        # that carries the thread ts as well.
        return (v or {}).get("at") if isinstance(v, dict) else (v or "")

    def _thread_of(v):
        return (v or {}).get("ts") if isinstance(v, dict) else None

    # BACK ONLINE, SAID IN THE THREAD. The parent promises updates "until it is
    # back", and a thread that simply stops reads exactly like a watcher that
    # died (Eve 2026-09-14: Cyrus quiet 17:34 -> 19:31, and nothing said so).
    # Once per outage: the "back" mark is dropped when the office goes quiet
    # again, so a second outage the same day gets its own all-clear.
    quiet_keys = {q["office"] for q in quiet}
    recovered = [k for k, v in sent.items()
                 if _thread_of(v) and not v.get("back") and k not in quiet_keys]
    changed = False
    if recovered:
        seen, _ever = check_ins(day)
        for key in recovered:
            raw = seen.get(key)
            if not raw:
                continue
            went = _parse_received(sent[key].get("last") or "")
            came = _parse_received(raw)
            if went and came and came > went:
                text = (":white_check_mark: back online — checked in at %s "
                        "(quiet for %s)." % (_clock(raw), _span(came - went)))
            else:
                text = (":white_check_mark: back online — checked in at %s."
                        % _clock(raw))
            log("BACK: %-10s %s" % (key, text))
            if not send:
                continue
            try:
                _slack(O.OPS_CHANNEL, text, thread_ts=_thread_of(sent[key]))
            except Exception as e:  # noqa: BLE001 — one office must not stop the rest
                log("could not post back-online for %s: %s: %s"
                    % (key, type(e).__name__, str(e)[:100]))
                continue
            sent[key] = dict(sent[key], back=now.isoformat(timespec="seconds"))
            changed = True

    fresh = []
    for q in quiet:
        last = _parse_when(_last_at(sent.get(q["office"])))
        # AGAINST `now`, NOT THE WALL CLOCK. They are the same in production,
        # but a repeat gate that reads dt.datetime.now() cannot be tested at
        # all -- and this gate is the only thing standing between one office
        # and a message every two minutes.
        if last and (now - last) < dt.timedelta(minutes=NUDGE_REPEAT_MIN):
            continue
        office = O.get(q["office"])
        # Each office is judged on ITS OWN clock. An Eastern office is an hour
        # further into its morning than a Central one, and a single shared
        # cutoff would nag one of them early and let the other slide.
        local = O.office_now(office) if office else now
        if not (QUIET_WARN_AFTER_HOUR <= local.hour <= QUIET_WARN_UNTIL_HOUR):
            continue
        q["office_time"] = local.strftime("%H:%M")
        q["how_long"] = _quiet_phrase(q, now)
        fresh.append(q)

    for q in fresh:
        log("QUIET: %-10s %s" % (q["office"], q["how_long"]))
    if not send or not fresh:
        if changed:
            _save_warned(data, day, sent)
        return fresh

    nudged = []
    for q in fresh:
        office = O.get(q["office"])
        if not (office and office.slack_user_id):
            continue
        first = (office.owner or "").split()[0] if office.owner else "there"
        try:
            _dm(office.slack_user_id, _nudge_text(first, q, key in laptops))
            nudged.append(q["office"])
        except Exception as e:  # noqa: BLE001 — a failed nudge must still reach us
            log("could not DM %s: %s: %s" % (q["office"], type(e).__name__,
                                             str(e)[:100]))

    # ONE THREAD PER OFFICE PER DAY (Megan 2026-09-12: "1 thread per ICD so
    # it's not clogging up the channel"). A laptop that stays down all
    # afternoon produced a top-level post every 30 minutes -- Cyrus had three
    # identical ones by 13:21, and they pushed real incidents off the screen.
    # The first nudge for an office opens a thread; every repeat lands under
    # it, so the channel shows ONE line per office no matter how long it is
    # down, and the history is all in one place.
    stamp = now.isoformat(timespec="seconds")
    for q in fresh:
        key = q["office"]
        parent = _thread_of(sent.get(key))
        tail = ("  _Nudged them._" if key in nudged
                else "  _No Slack id on file — nudge them yourself._")
        if parent:
            # A REPLY, and deliberately terse: the parent already explains
            # what this is, and a thread of identical paragraphs is the same
            # noise one level down.
            was_back = isinstance(sent.get(key), dict) and sent[key].get("back")
            text = ("%s — %s.%s" % ("quiet again" if was_back else "still quiet",
                                    q["how_long"], tail))
        else:
            text = ("\n\n".join([
                ":warning: *%s* — the alerts computer %s.%s"
                % (q["label"], q["how_long"], tail),
                "_Nothing is lost: %s is cumulative, so whatever it "
                "missed arrives when the %s is back online._"
                % (sales_system_for(O.get(key)),
                   machine_words(key in laptops)["noun"]),
                "_Updates follow in this thread until it is back._"]))
        try:
            ts = _slack(O.OPS_CHANNEL, text, thread_ts=parent)
        except Exception as e:  # noqa: BLE001 — one office must not stop the rest
            log("could not post quiet notice for %s: %s: %s"
                % (key, type(e).__name__, str(e)[:100]))
            continue
        # "last" is the check-in the outage started after, so the all-clear
        # can say how long it lasted. No "back" key: this outage is open.
        sent[key] = {"at": stamp, "ts": parent or ts, "last": q.get("last")}

    _save_warned(data, day, sent)
    return fresh


def _save_warned(data: Dict, day: dt.date, sent: Dict) -> None:
    WARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    data[day.isoformat()] = sent
    # Keep only the last few days; nothing older is interesting.
    for k in sorted(data)[:-5]:
        data.pop(k, None)
    WARNED_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))


def _clock(raw: str) -> str:
    """'9/14/2026 17:34:21' -> '17:34'. The date is today's; it is noise."""
    when = _parse_received(raw)
    return when.strftime("%H:%M") if when else (raw or "?")


def _span(delta: dt.timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return "%d min" % minutes
    hours, rest = divmod(minutes, 60)
    return "%d h" % hours if not rest else "%d h %d min" % (hours, rest)


def _quiet_phrase(q: Dict, now: dt.datetime) -> str:
    """How long the laptop has been quiet, in words nobody has to decode.

    It used to read "last checked in 9/14/2026 17:34:21 (18:19 their time)",
    and the bracket looked like the check-in converted to their zone when it
    was really the clock NOW -- two Central times 45 minutes apart that read
    like a timezone bug. The gap is the thing worth saying, so say the gap.
    """
    when = _parse_received(q.get("last") or "")
    if when:
        # Against the machine clock, same as is_stale() -- the Sheet stamps
        # and the poster share a zone, which is how 'stale' was decided.
        return "last checked in at %s, %s ago" % (_clock(q["last"]),
                                                   _span(now - when))
    if q.get("last"):
        return "last checked in %s" % q["last"]
    return "has not checked in today (%s there)" % q.get("office_time", "?")


LUCY_REPORTING = "U0BCG8F9B5Z"


def assert_posting_as_lucy(log=print) -> None:
    """Refuse to send unless this machine posts as Lucy Reporting.

    THE SLACK TOKEN IS PER MACHINE. A Lucy holds Lucy's; Megan's laptop holds
    MEGAN's. A `--send` from the wrong box does not fail -- it posts credit
    checks into an ICD's channel under Megan's own name, which is both wrong
    and not something you can take back. This has happened before on another
    report (a sales_boards --post from the laptop landed in #a-players-b2b as
    Megan), so it is checked rather than remembered.
    """
    from automations.shared import slack_metrics_post as smp
    who = smp._client().auth_test()
    if who.get("user_id") != LUCY_REPORTING:
        raise SystemExit(
            "NOT SENDING. This machine's Slack token is %s / %s, not Lucy "
            "Reporting (%s) -- every alert would post under that name. Run "
            "the poster on the Lucy that holds Lucy's token, or drop --send "
            "to preview here."
            % (who.get("user_id"), who.get("user"), LUCY_REPORTING))
    log("posting as %s (%s)" % (who.get("user"), who.get("user_id")))


def _slack(channel_id: str, text: str,
           thread_ts: Optional[str] = None) -> Optional[str]:
    """Post, optionally into a thread, and return the message ts.

    The ts is what lets the NEXT nudge for an office land under the same
    parent instead of as another top-level post [[warn_quiet]].
    """
    from automations.shared import slack_metrics_post as smp
    # NO UNFURLING. These messages carry links on purpose, and Slack pasting a
    # screenshot of the sign-up form under every one of them buried the two
    # lines somebody actually has to act on (Megan 2026-09-13).
    kw = {"channel": channel_id, "text": text,
          "unfurl_links": False, "unfurl_media": False}
    if thread_ts:
        kw["thread_ts"] = thread_ts
    return (smp._client().chat_postMessage(**kw) or {}).get("ts")


def _dm(user_id: str, text: str) -> None:
    """Open a DM with one person and send. Opening is idempotent -- Slack
    returns the existing conversation rather than starting a second one."""
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    channel = client.conversations_open(users=user_id)["channel"]["id"]
    client.chat_postMessage(channel=channel, text=text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Post relayed ICD credit-check alerts")
    ap.add_argument("--send", action="store_true",
                    help="actually post to Slack (default is a dry run)")
    ap.add_argument("--office", help="limit to one office key, e.g. kash")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--watch", action="store_true",
                    help="also report offices whose laptop has gone quiet")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.day) if args.day else dt.date.today()
    try:
        with _Lock() as lock:
            if not lock.held:
                # Not an error. The previous tick is still working and it owns
                # 'Last Posted'; running anyway is how the same credit checks
                # get announced twice.
                print("another poster run is already going -- skipping this tick")
                return 0
            if args.send:
                assert_posting_as_lucy()
            run(day, send=args.send, only=args.office)
            if args.watch:
                # NO MORNING RECAP HERE, AND THERE NEVER WILL BE. The metrics
                # thread ALREADY carries yesterday's knocks board:
                # rashad_metrics.knocks_run defaults to yesterday and posts
                # into today's thread. A recap posted from this side would put
                # the same board in the same thread twice (Megan spotted it
                # before it ever fired, 2026-09-15).
                #
                # A morning_recap.py sat next to this file unwired for two
                # days, kept on the note that the USEFUL version was the other
                # direction -- for an office already relaying its own knocks,
                # render the metrics board from those rows instead of
                # impersonating them in ownerville. THAT IS BUILT AND LIVE:
                # rashad_metrics.knocks_relay, since 2026-09-17, with
                # icd_alerts.closeout re-reading the finished day on the
                # office's own machine first. The module was deleted rather
                # than left looking like an unfinished feature somebody might
                # helpfully finish.
                run_requested_approvals(send=args.send)
                notify_new_signups(send=args.send)
                notify_pending(send=args.send)
                notify_faults(day, send=args.send)
                warn_quiet(day, send=args.send)
                warn_stale_machines(day, send=args.send)
                # BOTH OF THESE EXISTED AND NOTHING CALLED THEM. A machine
                # going quiet was something Megan noticed by eye, and an
                # office that lost its approval looked exactly like one that
                # had never been given it.
                warn_machine_facts(day, send=args.send)
                warn_lost_approvals(day, send=args.send)
    except RelayNotConfigured as e:
        print(e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
