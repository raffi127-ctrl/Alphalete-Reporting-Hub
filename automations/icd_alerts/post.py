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
import sys
from typing import Dict, List, Optional, Tuple

from automations.icd_alerts import offices as O
from automations.shared.credit_check_line import records_line

# The relay workbook: 'Lucy Access App' (Megan supplied it 2026-09-11). The
# Apps Script in resources/icd-alerts-relay.gs is bound to THIS workbook, and
# its 'Relay Keys' tab is the list of who may hand anything in at all.
# Sheet1 is Megan's and is left alone.
RELAY_SPREADSHEET_ID = "1_5YGHhZ0gCYVZzHl7TPnP-6_75xaI0kcjPinQdVTlKg"
RELAY_TAB = "ICD Relay"

COL_OFFICE, COL_DAY, COL_RECORDS = 0, 1, 2
COL_RECEIVED, COL_LOCAL_TIME, COL_AGENT = 3, 4, 5
COL_LAST_POSTED, COL_POSTED_AT = 6, 7

# A laptop that has not checked in for this long is asleep, shut, or off wifi.
# Worth SAYING, never worth alerting the office about -- they cannot act on it
# and it is not their job to.
STALE_MINUTES = 45


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


def is_stale(received: Optional[dt.datetime], now: Optional[dt.datetime] = None,
             minutes: int = STALE_MINUTES) -> bool:
    if not received:
        return True
    now = now or dt.datetime.now()
    return (now - received) > dt.timedelta(minutes=minutes)


# --- the sheet ---------------------------------------------------------------
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

        if baseline:
            log("%-10s first relay of %s -- recording %d rep(s), posting nothing"
                % (key, day.isoformat(), len(records)))
        elif not lines:
            log("%-10s nothing new (%d rep(s) tracked)" % (key, len(records)))
        else:
            targets, held = O.destinations(office)
            log("%-10s %d new credit check line(s) -> %s%s"
                % (key, len(lines), ", ".join(t.name for t in targets),
                   "   [HELD -- no channel decided for this office]" if held else ""))
            for line in lines:
                log("    %s" % line)

        if not send:
            continue
        if lines:
            text = "\n".join(lines)
            targets, held = O.destinations(office)
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
        if lines or baseline:
            tab.update_cell(rownum, COL_LAST_POSTED + 1, json.dumps(merged))
            tab.update_cell(rownum, COL_POSTED_AT + 1,
                            dt.datetime.now().isoformat(timespec="seconds"))

    if not send:
        log("\nDRY RUN -- nothing posted and nothing recorded. Re-run with "
            "--send once the above looks right.")
    return {"offices": considered, "posted": posted}


def _slack(channel_id: str, text: str) -> None:
    from automations.shared import slack_metrics_post as smp
    smp._client().chat_postMessage(channel=channel_id, text=text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Post relayed ICD credit-check alerts")
    ap.add_argument("--send", action="store_true",
                    help="actually post to Slack (default is a dry run)")
    ap.add_argument("--office", help="limit to one office key, e.g. kash")
    ap.add_argument("--day", help="YYYY-MM-DD (default: today)")
    args = ap.parse_args(argv)
    day = dt.date.fromisoformat(args.day) if args.day else dt.date.today()
    try:
        run(day, send=args.send, only=args.office)
    except RelayNotConfigured as e:
        print(e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
