"""Lucy's hourly call-out: who has been off the doors 15+ minutes with no
fresh credit check.

Carlos, 2026-09-26: "lucy is already checking credit checks. What would be
cool is if lucy started commenting on people's 15 min gaps when it doesn't
see credit checks ... nick, christian, jose... 40 minutes without a dispo...
once an hour she makes comments based off the gaps and whether there's a
recent credit check or not." Megan: "Let's build in some call outs from
Lucy."

WHAT IT READS. Nothing new is scraped: the office's own machine already
relays the knocks board (per-rep last knock) and SaraPlus's credit checks
(per-rep count today). A rep is called out when BOTH are quiet: 15+ minutes
since their last knock AND their credit-check count has not moved since the
last call-out hour. A rep in a house pitching (no knocks, but a credit check
just ran) is left alone -- that is the whole point of crossing the two.

ONCE AN HOUR PER OFFICE, field hours only, and never an empty message: a
quiet hour with nobody over the line posts nothing (never post blank).

PER OFFICE, OPT-IN. The voice goes to every office that is switched on, so
it is mild by design (Megan: "unsure of how spicy to make her because she
goes to everyone's offices"). Carlos asked; his two offices are on. Adding an
office is one key in CALLOUT_OFFICES. The lines live in one pool below.

    python -m automations.icd_alerts.gap_callouts            # dry run
    python -m automations.icd_alerts.gap_callouts --send
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Optional

from automations.icd_alerts import knocks_map as M, knocks_post as K, offices as O, post as P

# AT&T offices only: the cross-check IS the credit check. A Box office has no
# SaraPlus, so every gap would qualify and a Saturday afternoon read as
# twelve names -- a wall, not a call-out (seen in the first dry run).
CALLOUT_OFFICES = {"carlos-b2batt"}
MAX_NAMES = 5
CALLOUT_EVERY_MIN = 60
GAP_MIN = 15
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "icd_gap_callouts.json"

# THE VOICE. Mild enough for any office, pointed enough to land. {names} is
# "Nick, Christian and Jose", {m} is the shortest gap among them.
LINES = (
    "{names} — {m}+ min without a dispo and nothing in SaraPlus. Y'all taking a group nap out there?",
    "Quiet check: {names}. {m}+ min since a door and no credit check. Doors don't knock themselves.",
    "{names}: {m}+ min, no dispo, no credit check. Coffee break's over — go find the money.",
    "No doors and no credit checks from {names} for {m}+ min. Everything okay, or just admiring the neighborhood?",
    "{names} — {m}+ min off the doors. The board's not going to fill itself.",
    "{m}+ minutes and not a single dispo from {names}. I'm watching 👀",
    "{names} — {m}+ min of silence. Knock something.",
)


def _key(name: str) -> str:
    return " ".join(str(name or "").split()).lower()


def _first(name: str) -> str:
    from automations.shared import name_case
    first = str(name or "").split()[0] if str(name or "").strip() else ""
    return name_case.titlecase_name(first) if first else ""


def pick(rows: List[Dict], records_now: Dict[str, int], records_prev: Dict[str, int],
         now: dt.datetime) -> List[Dict]:
    """Reps to call out: 15+ min since their last knock AND no new credit
    check since the previous call-out. Pure. `rows` are knocks_map.to_rows
    rows ('Rep', 'Last Knock' on the office's clock); records are SaraPlus
    credit-check counts by rep, now and at the last call-out."""
    now_n = {_key(k): int(v or 0) for k, v in (records_now or {}).items()}
    prev_n = {_key(k): int(v or 0) for k, v in (records_prev or {}).items()}
    out = []
    for r in rows:
        name = str(r.get("Rep") or "").strip()
        last = str(r.get("Last Knock") or "").strip()
        if not name or not last:
            continue
        mins = K._minutes_since(last, now)
        if mins is None or mins < GAP_MIN:
            continue
        if now_n.get(_key(name), 0) > prev_n.get(_key(name), 0):
            continue                       # pitching, not idle
        out.append({"name": name, "mins": int(mins)})
    out.sort(key=lambda x: -x["mins"])
    return out


def line(office_key: str, callouts: List[Dict], now: dt.datetime) -> str:
    """One sentence in the house voice, chosen by office + hour so a re-run
    repeats itself and neighbouring hours don't."""
    if not callouts:
        return ""
    firsts = []
    for c in callouts:
        f = _first(c["name"])
        if f and f not in firsts:
            firsts.append(f)
    if len(firsts) > MAX_NAMES:
        firsts = firsts[:MAX_NAMES - 1] + ["%d more" % (len(firsts) - MAX_NAMES + 1)]
    names = firsts[0] if len(firsts) == 1 else ", ".join(firsts[:-1]) + " and " + firsts[-1]
    m = min(c["mins"] for c in callouts)
    m = (m // 5) * 5                       # "40+", not "43+"
    seed = "callout|%s|%s|%d" % (office_key, now.date().isoformat(), now.hour)
    return LINES[zlib.crc32(seed.encode("utf-8")) % len(LINES)].format(names=names, m=m)


def _state() -> Dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save(state: Dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))
    except OSError:
        pass


def due(state_for_office: Optional[Dict], now: dt.datetime) -> bool:
    if not state_for_office or state_for_office.get("day") != now.date().isoformat():
        return True
    last = P._parse_when(state_for_office.get("last_at") or "")
    return last is None or (now - last) >= dt.timedelta(minutes=CALLOUT_EVERY_MIN)


def run(day: Optional[dt.date] = None, *, send: bool = False, book=None,
        log=print, only: Optional[str] = None) -> List[str]:
    from automations.recruiting_report.fill import open_by_key
    day = day or dt.date.today()
    book = book or open_by_key(P.RELAY_SPREADSHEET_ID)
    knocks = {r[K.KN_OFFICE].strip().lower(): r for r in book.worksheet(K.KNOCKS_TAB).get_all_values()[1:]
              if len(r) > K.KN_RECEIVED and P._day_key(r[K.KN_DAY]) == day.isoformat()}
    relay = {r[0].strip().lower(): r for r in book.worksheet(P.RELAY_TAB).get_all_values()[1:]
             if len(r) > P.COL_RECEIVED and P._day_key(r[1]) == day.isoformat()}
    approved_ch = P.approved_channels()
    approved_tx = P.approved_texts()
    state = _state()
    said = []
    for key in sorted(CALLOUT_OFFICES):
        if only and key != only:
            continue
        office = O.get(key)
        if not office:
            continue
        now = K._office_now(office)
        if not K.in_field_hours(office, now):
            log("%-14s outside field hours (%s their time)" % (key, now.strftime("%a %H:%M")))
            continue
        # THE KNOCKS ROW: this office's, or the sibling office on the same
        # machine (khalil / khalil-nds relay under one key).
        krow = knocks.get(key) or next((r for k, r in knocks.items() if k.startswith(key) or key.startswith(k)), None)
        if not krow or K._too_old(krow[K.KN_RECEIVED]):
            log("%-14s no fresh knocks relay" % key)
            continue
        try:
            rows = M.to_rows(json.loads(krow[K.KN_ROWS] or "[]"), json.loads(krow[K.KN_TRACKER] or "[]"))
        except ValueError:
            continue
        rrow = relay.get(key) or next((r for k, r in relay.items() if k.startswith(key) or key.startswith(k)), None)
        try:
            records = json.loads(rrow[P.COL_RECORDS] or "{}") if rrow else {}
        except ValueError:
            records = {}
        st = state.get(key) or {}
        if not due(st, now):
            continue
        prev = st.get("records") or {} if st.get("day") == now.date().isoformat() else {}
        callouts = pick(rows, records, prev, now)
        text = line(key, callouts, now)
        state[key] = {"day": now.date().isoformat(), "last_at": now.isoformat(timespec="seconds"),
                      "records": records}
        if not text:
            log("%-14s nobody over %d min without a credit check -- nothing to say" % (key, GAP_MIN))
            continue
        dests = [c.id for c in (approved_ch.get(key) or [])]
        texts = approved_tx.get(key) or []
        log("%-14s -> %s%s: %s" % (key, ", ".join(dests) or "-", "".join(" + text %r" % t["channel_name"] for t in texts), text))
        said.append(text)
        if not send:
            continue
        for ch in dests:
            try:
                P._slack(ch, text)
            except Exception as e:  # noqa: BLE001
                log("%-14s FAILED to post to %s: %s" % (key, ch, type(e).__name__))
        from automations.b2b_dispositions import text_post as tp
        for t in texts:
            try:
                tp.send_text_to_group(t["channel_name"], text, dry_run=False, dest=t)
            except Exception as e:  # noqa: BLE001
                log("%-14s FAILED to text %r: %s: %s" % (key, t["channel_name"], type(e).__name__, str(e)[:120]))
    if send:
        _save(state)
    return said


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lucy's hourly gap call-outs")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--office")
    args = ap.parse_args(argv)
    run(send=args.send, only=args.office)
    if not args.send:
        print("DRY RUN -- nothing posted, nothing remembered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
