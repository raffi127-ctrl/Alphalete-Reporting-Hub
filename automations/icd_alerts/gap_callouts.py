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

# EVERY OFFICE WITH AN APPROVED ALERT CHANNEL (Megan 2026-09-26: "roll out
# for everyone"), Slack only -- the room its SaraPlus / Service Cloud alerts
# already land in. Not the text groups. The cross-check is whatever the
# office's system relays: credit checks on AT&T, contracts on Box; a rep whose
# count moved this hour is working, not idle. Names capped so a slow Saturday
# is a call-out, not a roll call.
CALLOUT_CAMPAIGNS = {"att", "nds"}   # D2D only; B2B and Box offices are out (Megan 2026-09-26)
INLINE_NAMES = 3      # more than this and every name goes on its own bullet (Megan: name them, no '6 more')
CALLOUT_EVERY_MIN = 60
GAP_MIN = 15
GAP_MAX = 180        # past this they went home; a call-out every hour would be noise
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "icd_gap_callouts.json"

# THE VOICE. Mild enough for any office, pointed enough to land. {names} is
# "Nick, Christian and Jose", {m} is the shortest gap among them.
# THE HOUSE SLANG (Megan 2026-09-26): "Snicklemeberries" is Lucy's, like
# "Snicklepop!!" on the sale line; a "finger popper" -- "master finger
# popper", "finger poppin' ninja" -- is somebody NOT working, and the offices
# say it constantly, so Lucy does too.
LINES = (
    "Snicklemeberries! {names} — {m}+ min without a dispo. Finger poppin' or knocking?",
    "{names}: {m}+ min off the doors and nothing on the board. Master finger poppers in the making.",
    "Finger poppin' ninjas spotted: {names}. {m}+ min since a door. Doors don't knock themselves.",
    "{names} — {m}+ min, no dispo, no sale. Coffee break's over — go find the money.",
    "Snicklemeberries, {names}. {m}+ min of silence. Knock something.",
    "{m}+ minutes and not a single dispo from {names}. I'm watching 👀",
    "No doors and no sales from {names} for {m}+ min. Everything okay, or just admiring the neighborhood?",
    "{names} — {m}+ min off the doors. The board's not going to fill itself.",
    "Quiet check: {names} — {m}+ min without a door. Y'all finger poppin' each other out there?",
    "{names} — {m}+ min without a dispo. Lucy sees you, finger poppers.",
)


def _key(name: str) -> str:
    return " ".join(str(name or "").split()).lower()


def _first(name: str) -> str:
    from automations.shared import name_case
    first = str(name or "").split()[0] if str(name or "").strip() else ""
    return name_case.titlecase_name(first) if first else ""


def activity(records: Dict, sales: Dict, campaign=None) -> Dict[str, int]:
    """One number per rep that only rises while they work: credit checks plus
    sales on AT&T, contracts on Box (which has no credit checks)."""
    from automations.shared import sale_hype as H
    out = {}
    for k, v in (records or {}).items():
        out[_key(k)] = out.get(_key(k), 0) + int(v or 0)
    for k, m in (sales or {}).items():
        out[_key(k)] = out.get(_key(k), 0) + int(H.shape(campaign).total(m or {}))
    return out


def pick(rows: List[Dict], records_now: Dict[str, int], records_prev: Dict[str, int],
         now: dt.datetime) -> List[Dict]:
    """Reps to call out: 15+ min since their last knock AND their activity
    number has not moved since the previous call-out. Pure. `rows` are
    knocks_map.to_rows rows ('Rep', 'Last Knock' on the office's clock);
    the two dicts are activity() now and at the last call-out."""
    now_n = {_key(k): int(v or 0) for k, v in (records_now or {}).items()}
    prev_n = {_key(k): int(v or 0) for k, v in (records_prev or {}).items()}
    out = []
    for r in rows:
        name = str(r.get("Rep") or "").strip()
        last = str(r.get("Last Knock") or "").strip()
        if not name or not last:
            continue
        mins = K._minutes_since(last, now)
        if mins is None or mins < GAP_MIN or mins > GAP_MAX:
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
    m = min(c["mins"] for c in callouts)
    m = (m // 5) * 5                       # "40+", not "43+"
    seed = "callout|%s|%s|%d" % (office_key, now.date().isoformat(), now.hour)
    template = LINES[zlib.crc32(seed.encode("utf-8")) % len(LINES)]
    if len(firsts) <= INLINE_NAMES:
        names = firsts[0] if len(firsts) == 1 else ", ".join(firsts[:-1]) + " and " + firsts[-1]
        return template.format(names=names, m=m)
    # A CROWD IS A LIST, NOT A COUNT (Megan 2026-09-26: "it shouldn't say
    # '6 more' it should name them"). The sentence addresses the group; every
    # name sits on its own bullet with its own minutes, longest gap first.
    head = template.format(names="%d of y'all" % len(firsts), m=m)
    bullets = ["• %s — %d min" % (_first(c["name"]), c["mins"]) for c in callouts]
    return head + "\n" + "\n".join(bullets)


def pick_from_gaps(gaps: List[Dict], records_now: Dict[str, int], records_prev: Dict[str, int]) -> List[Dict]:
    """Like pick(), but from an already-computed gap list ({name,
    minutesSinceLastKnock}) -- what gap_alerts holds for Carlos's reps on Raf's
    OwnerVille. Same rule: over the line AND no activity since last hour."""
    now_n = {_key(k): int(v or 0) for k, v in (records_now or {}).items()}
    prev_n = {_key(k): int(v or 0) for k, v in (records_prev or {}).items()}
    out = []
    for g in gaps or []:
        name = str(g.get("name") or "").strip()
        try:
            mins = int(g.get("minutesSinceLastKnock") or 0)
        except (TypeError, ValueError):
            continue
        if not name or mins < GAP_MIN or mins > GAP_MAX:
            continue
        if now_n.get(_key(name), 0) > prev_n.get(_key(name), 0):
            continue
        out.append({"name": name, "mins": mins})
    out.sort(key=lambda x: -x["mins"])
    return out


def guest_callout(host_key: str, guest: str, gaps: List[Dict], records_now: Dict[str, int],
                  now: dt.datetime, *, remember: bool = True) -> str:
    """Lucy's hourly line for a GUEST office's reps (Carlos's 14 on Raf's
    OwnerVille, Megan 2026-09-26), to ride the gap text their rooms already
    get every 15 minutes. Once an hour; "" the rest of the time or when
    nobody qualifies. `records_now` is the host's SaraPlus credit checks per
    rep (the sales board sweep's), which is where those reps' checks land."""
    key = "guest:%s:%s" % (host_key, _key(guest).replace(" ", "-"))
    state = _state()
    st = state.get(key) or {}
    if not due(st, now):
        return ""
    prev = (st.get("records") or {}) if st.get("day") == now.date().isoformat() else dict(records_now or {})
    text = line(key, pick_from_gaps(gaps, records_now, prev), now)
    if remember:
        state[key] = {"day": now.date().isoformat(), "last_at": now.isoformat(timespec="seconds"),
                      "records": dict(records_now or {})}
        _save(state)
    return text


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
    approved_ch = {k: v for k, v in P.approved_channels().items() if v}
    state = _state()
    said = []
    for key in sorted(approved_ch):
        if only and key != only:
            continue
        office = O.get(key)
        if not office:
            continue
        # D2D AT&T AND NDS ONLY (Megan 2026-09-26: "Att & NDS", "not B2B").
        # The B2B offices -- Carlos's two, Ryan's and Roshan's Box -- are out.
        if str(getattr(office, "campaign", "") or "att").strip().lower() not in CALLOUT_CAMPAIGNS:
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
            sales = json.loads(rrow[P.COL_SALES] or "{}") if rrow and len(rrow) > P.COL_SALES else {}
        except ValueError:
            records, sales = {}, {}
        records = activity(records, sales, getattr(office, "campaign", None))
        st = state.get(key) or {}
        if not due(st, now):
            continue
        # FIRST HOUR OF THE DAY: no snapshot yet, so nobody can be "fresh"
        # against it -- judge on the gap alone. Comparing against {} instead
        # exempted everyone with a single credit check all morning.
        prev = (st.get("records") or {}) if st.get("day") == now.date().isoformat() else dict(records)
        callouts = pick(rows, records, prev, now)
        text = line(key, callouts, now)
        state[key] = {"day": now.date().isoformat(), "last_at": now.isoformat(timespec="seconds"),
                      "records": records}
        if not text:
            log("%-14s nobody over %d min without a credit check -- nothing to say" % (key, GAP_MIN))
            continue
        dests = [c.id for c in (approved_ch.get(key) or [])]
        log("%-14s -> %s: %s" % (key, ", ".join(dests) or "-", text))
        said.append(text)
        if not send:
            continue
        for ch in dests:
            try:
                P._slack(ch, text)
            except Exception as e:  # noqa: BLE001
                log("%-14s FAILED to post to %s: %s" % (key, ch, type(e).__name__))
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
