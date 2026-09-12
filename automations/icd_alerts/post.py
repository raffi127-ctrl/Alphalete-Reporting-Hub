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
from typing import Dict, List, Optional, Tuple

from automations.icd_alerts import offices as O
from automations.shared.credit_check_line import records_line

# The relay workbook: 'Lucy Access App' (Megan supplied it 2026-09-11). The
# Apps Script in resources/icd-alerts-relay.gs is bound to THIS workbook, and
# its 'Relay Keys' tab is the list of who may hand anything in at all.
# Sheet1 is Megan's and is left alone.
RELAY_SPREADSHEET_ID = "1_5YGHhZ0gCYVZzHl7TPnP-6_75xaI0kcjPinQdVTlKg"
RELAY_TAB = "ICD Relay"

CHANNELS_TAB = "Office Channels"
# Both halves are the same shape: what the office asked for, then what a
# human approved. A laptop writes only the asking columns.
CH_OFFICE, CH_OWNER, CH_ASKED, CH_ASKED_JSON, CH_ASKED_AT = 0, 1, 2, 3, 4
CH_APPROVED_JSON, CH_APPROVED = 5, 6
CH_KN_WANTED, CH_KN_JSON, CH_KN_HOURS = 7, 8, 9
CH_KN_APPROVED_JSON, CH_KN_APPROVED = 10, 11

COL_OFFICE, COL_DAY, COL_RECORDS = 0, 1, 2
COL_RECEIVED, COL_LOCAL_TIME, COL_AGENT = 3, 4, 5
COL_LAST_POSTED, COL_POSTED_AT = 6, 7
# APPENDED, not inserted. Sales arrived after offices were already relaying,
# and the deployed script and the sheet cannot be changed in the same instant
# -- so the new columns went on the END and every position above is untouched.
# An office still running the older agent simply leaves these blank.
COL_SALES, COL_LAST_POSTED_SALES = 8, 9

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

# Who has already been told an office went quiet today. ONCE PER OFFICE PER
# DAY: the poster ticks every ten minutes, and a closed laptop stays closed --
# a warning per tick would be 60 messages about one fact, which is how people
# learn to ignore the channel this is supposed to protect.
WARNED_PATH = Path.home() / ".config" / "recruiting-report" / "icd_alerts_quiet.json"
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
           last_posted: Optional[Dict[str, int]]) -> Tuple[List[str], Dict[str, int], bool]:
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
    records = {str(k): int(v) for k, v in (records or {}).items()}
    if last_posted is None:
        return [], records, True

    prev = {str(k): int(v) for k, v in last_posted.items()}
    merged = dict(prev)
    lines = []
    for rep, n in sorted(records.items()):
        was = prev.get(rep, 0)
        if n > was:
            lines.append(records_line(rep, n, n - was))
            merged[rep] = n
    return lines, merged, False


def decide_sales(sales: Dict, last_posted: Optional[Dict]
                 ) -> Tuple[List[str], Dict, bool]:
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

    sales = {str(k): {m: int(v.get(m, 0) or 0) for m in H.METRICS}
             for k, v in (sales or {}).items()}
    if last_posted is None:
        return [], sales, True

    prev = {str(k): {m: int(v.get(m, 0) or 0) for m in H.METRICS}
            for k, v in last_posted.items()}
    merged = {k: dict(v) for k, v in prev.items()}
    moved = []
    for rep, now_m in sorted(sales.items()):
        was = prev.get(rep) or {m: 0 for m in H.METRICS}
        if any(now_m.get(m, 0) > was.get(m, 0) for m in H.METRICS):
            moved.append(rep)
        merged[rep] = {m: max(now_m.get(m, 0), was.get(m, 0)) for m in H.METRICS}
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


def quiet_offices(day: Optional[dt.date] = None, minutes: int = STALE_MINUTES,
                  book=None) -> List[Dict]:
    """Enrolled offices whose laptop has not checked in lately, or at all.

    THE FAILURE THIS CATCHES IS SILENCE, and silence is the one an alerting
    system cannot see from the inside: a closed laptop and a quiet sales day
    produce exactly the same empty channel. Reported to us, never to the
    office -- they cannot act on it and it is not their job to.
    """
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


def run(day: Optional[dt.date] = None, *, send: bool = False,
        only: Optional[str] = None, log=print) -> Dict:
    day = day or dt.date.today()
    tab = _relay_tab()
    approved = approved_channels(tab.spreadsheet)
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
        lines, merged, baseline = decide(records, last)

        # Sales ride the same row and the same rules. An office still on the
        # older agent sends none, and this stays empty rather than erroring.
        sales = _loads(row[COL_SALES] if len(row) > COL_SALES else "") or {}
        last_sales = _loads(row[COL_LAST_POSTED_SALES]
                            if len(row) > COL_LAST_POSTED_SALES else "")
        sold, merged_sales, sales_baseline = decide_sales(sales, last_sales)
        hype_lines = []
        if sold:
            from automations.shared import sale_hype as H
            hype_lines = [H.hype(rep, sales.get(rep) or {}, day) for rep in sold]

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
    pending = pending_requests(book) + [
        dict(r, knocks=True) for r in pending_knocks(book)]
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
    _slack(O.HOLDING_DM, "\n".join(lines))

    ENROLLED_PATH.parent.mkdir(parents=True, exist_ok=True)
    for r in fresh:
        seen[r["_key"]] = dt.datetime.now().isoformat(timespec="seconds")
    ENROLLED_PATH.write_text(json.dumps(seen, indent=2, sort_keys=True))
    return fresh


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
    "  • the laptop is asleep or shut — wake it and leave the lid open\n"
    "  • it's unplugged — it has to be on power to stay awake\n"
    "  • it's off wifi\n\n"
    "Sort any of those and it picks itself up within a few minutes. Nothing is "
    "lost in the meantime. If it's none of those, just reply here.")


def _nudge_text(first: str, quiet: Dict) -> str:
    """The nudge, opening with whichever thing actually happened."""
    last = (quiet.get("last") or "").strip()
    if quiet.get("last") and "not checked in" not in (quiet.get("reason") or ""):
        # Just the clock, not the date -- they are reading this today.
        stamp = last.split(" ")[-1] if " " in last else last
        return OWNER_NUDGE % (first, NUDGE_STOPPED % stamp)
    return OWNER_NUDGE % (first, NUDGE_NEVER)


def warn_quiet(day: Optional[dt.date] = None, *, send: bool = False,
               now: Optional[dt.datetime] = None, log=print) -> List[Dict]:
    """Nudge the OFFICE, and tell us. 11am on their own clock.

    I built this to warn us only, reasoning that an ICD cannot act on it. That
    was wrong for THIS failure and Megan said so (2026-09-12): a laptop that is
    asleep, shut or unplugged is the one thing only they can fix, and it is
    fixed in ten seconds. Telling the person who can act is the whole point.

    They are nudged ONCE a day. A second message about a laptop somebody has
    already been asked to wake is nagging, and the first one stops being read.
    """
    now = now or dt.datetime.now()
    day = day or now.date()
    if now.weekday() == 6:               # nobody is selling on Sunday
        return []

    quiet = quiet_offices(day)
    if not quiet:
        return []

    data = _warned()
    already = set(data.get(day.isoformat()) or [])
    fresh = []
    for q in quiet:
        if q["office"] in already:
            continue
        office = O.get(q["office"])
        # Each office is judged on ITS OWN clock. An Eastern office is an hour
        # further into its morning than a Central one, and a single shared
        # cutoff would nag one of them early and let the other slide.
        local = O.office_now(office) if office else now
        if not (QUIET_WARN_AFTER_HOUR <= local.hour <= QUIET_WARN_UNTIL_HOUR):
            continue
        q["office_time"] = local.strftime("%H:%M")
        fresh.append(q)
    if not fresh:
        return []

    for q in fresh:
        log("QUIET: %-10s %s (%s their time)"
            % (q["office"], q["reason"], q.get("office_time", "?")))
    if not send:
        return fresh

    nudged = []
    for q in fresh:
        office = O.get(q["office"])
        if not (office and office.slack_user_id):
            continue
        first = (office.owner or "").split()[0] if office.owner else "there"
        try:
            _dm(office.slack_user_id, _nudge_text(first, q))
            nudged.append(q["office"])
        except Exception as e:  # noqa: BLE001 — a failed nudge must still reach us
            log("could not DM %s: %s: %s" % (q["office"], type(e).__name__,
                                             str(e)[:100]))

    lines = ["\n".join(
        ":warning: *%s* — the alerts computer %s (%s their time).%s"
        % (q["label"], q["reason"], q.get("office_time", "?"),
           "  _Nudged them._" if q["office"] in nudged
           else "  _No Slack id on file — nudge them yourself._")
        for q in fresh)]
    lines.append("_Nothing is lost: SaraPlus is cumulative, so whatever it "
                 "missed arrives when the laptop is back online._")
    _slack(O.HOLDING_DM, "\n\n".join(lines))

    WARNED_PATH.parent.mkdir(parents=True, exist_ok=True)
    data[day.isoformat()] = sorted(already | {q["office"] for q in fresh})
    # Keep only the last few days; nothing older is interesting.
    for k in sorted(data)[:-5]:
        data.pop(k, None)
    WARNED_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))
    return fresh


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


def _slack(channel_id: str, text: str) -> None:
    from automations.shared import slack_metrics_post as smp
    smp._client().chat_postMessage(channel=channel_id, text=text)


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
                notify_pending(send=args.send)
                warn_quiet(day, send=args.send)
    except RelayNotConfigured as e:
        print(e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
