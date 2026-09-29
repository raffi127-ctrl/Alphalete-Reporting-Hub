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
# ... except offices that ASKED. Ryan asked and is in (2026-09-26).
#
# ROSHAN ASKED TO BE TAKEN BACK OUT, same day she went in (Raf, 2026-09-26:
# "Roshan wants her call outs from Lucy stopped" → "Just stop the call outs").
# Removing the key is the whole switch: her campaign is `b2b_box`, which is not
# in CALLOUT_CAMPAIGNS, so both gates below now skip her — the 30-minute gap
# call-out AND the positive end-of-day one.
#
# DELIBERATELY NOT DONE ANY OTHER WAY. Her channel stays approved and her
# relay untouched, so she KEEPS her credit-check/sales alerts and her hourly
# knock board — same room, #sapphire-office-sales, both from other modules.
# Un-approving her channel or clearing a "Wanted" column would have stopped
# all three and the relay would have fought it back: writing an office's own
# columns is what cleared Cyrus's approval (2026-09-15) and Colten's
# (2026-09-22). This constant is ours, in git, and nothing on her laptop can
# revert it.
CALLOUT_EXTRA_OFFICES = {"ryan"}
INLINE_NAMES = 3      # more than this and every name goes on its own bullet (Megan: name them, no '6 more')
# CARLOS'S NUMBERS (2026-09-26): "30 mins plus. But if they've had a credit
# check in the last 30 mins they're not finger popping." So the check runs
# every 30 and the snapshot it compares against is 30 minutes old.
CALLOUT_EVERY_MIN = 30
GAP_MIN = 30
GAP_MAX = 180        # past this they went home; a call-out every hour would be noise
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "icd_gap_callouts.json"

# THE VOICE. Mild enough for any office, pointed enough to land. {names} is
# "Nick, Christian and Jose", {m} is the shortest gap among them.
# THE HOUSE SLANG (Megan 2026-09-26): "Snicklemeberries" is Lucy's, like
# "Snicklepop!!" on the sale line; a "finger popper" -- "master finger
# popper", "finger poppin' ninja" -- is somebody NOT working, and the offices
# say it constantly, so Lucy does too.
LINES = (
    "Snicklemeberries! 🫐 {names} — {m}+ min without a dispo. Finger poppin' or knocking? 🚪👀",
    "{names}: {m}+ min off the doors and nothing on the board 📋❌ Master finger poppers in the making 🤌",
    "🥷 Finger poppin' ninjas spotted: {names}. {m}+ min since a door. Doors don't knock themselves 🚪",
    "{names} — {m}+ min, no dispo, no sale. ☕ Coffee break's over — go find the money 💰",
    "Snicklemeberries 🫐 {names}. {m}+ min of silence 🤫 Knock something 🚪",
    "⏱️ {m}+ minutes and not a single dispo from {names}. I'm watching 👀",
    "No doors 🚪 and no sales 💸 from {names} for {m}+ min. Everything okay, or just admiring the neighborhood? 🏡",
    "{names} — {m}+ min off the doors. The board's not going to fill itself 📋⚡",
    "Quiet check 🤫 {names} — {m}+ min without a door. Y'all finger poppin' each other out there? 🤌🤌",
    "{names} — {m}+ min without a dispo. Lucy sees you, finger poppers 👀🤌",
    # BENEFIT OF THE DOUBT (Megan 2026-09-26): a quiet rep may be inside with
    # a customer. Half the pool leaves that door open.
    "{names} — {m}+ min without a dispo. Must be cooking up something good in there… right? 👨‍🍳🔥",
    "No dispo from {names} in {m}+ min. In a house with a customer? 🏠",
    "{names} — {m}+ min quiet. If that's a sale being cooked 🍳 take your time. If not… 👀",
    # EN ESPAÑOL TAMBIÉN (Megan 2026-09-26: "make lucy bilingual"). Same
    # pool, so some hours land in Spanish and some in English.
    "¡Snicklemeberries! 🫐 {names} — {m}+ min sin dispo. ¿Finger poppin' o tocando puertas? 🚪👀",
    "{names}: {m}+ min sin tocar una puerta 🚪 Las puertas no se tocan solas 🤷",
    "{names} — {m}+ min sin dispo y sin venta. ☕ Se acabó el cafecito — a buscar el dinero 💰",
    "⏱️ {m}+ minutos y ni un dispo de {names}. Los estoy viendo 👀",
    "{names} — {m}+ min callados 🤫 Si están cocinando una venta 🍳 tómense su tiempo. Si no… 👀",
    "Ojo 👁️ {names}: {m}+ min sin puertas. ¿Trabajando una venta 💰 o de finger poppers? 🤌",
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


_SPANISH_MARKERS = ("¡", "¿", " sin ", "puertas", "ustedes", "estoy", "Ojo,", "callados")


def _is_spanish(template: str) -> bool:
    return any(mk in template for mk in _SPANISH_MARKERS)


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
    spanish = _is_spanish(template)
    if len(firsts) <= INLINE_NAMES:
        joiner = " y " if spanish else " and "
        names = firsts[0] if len(firsts) == 1 else ", ".join(firsts[:-1]) + joiner + firsts[-1]
        return template.format(names=names, m=m)
    # A CROWD IS A LIST, NOT A COUNT (Megan 2026-09-26: "it shouldn't say
    # '6 more' it should name them"). The sentence addresses the group; every
    # name sits on its own bullet with its own minutes, longest gap first.
    crowd = ("%d de ustedes" if spanish else "%d of y'all") % len(firsts)
    head = template.format(names=crowd, m=m)
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


# A GUEST OFFICE'S CALL-OUT GOES TO ITS OWN SLACK ROOM, not the text chains
# (Megan to Carlos, 2026-09-26: "moving to be on the main slack channel
# only"). The guest name as the host's roster spells it -> the ECO office
# key whose approved alert channel gets it.
GUEST_SLACK_KEY = {"carlos hidalgo": "carlos"}

# A HOST OFFICE'S OWN REPS (Megan 2026-09-26: "when will the first call outs
# post for Raf?"): the gap_alerts host, whose credit checks the sales board
# sweep reads, posted to its main room. gap_alerts key -> Slack channel.
HOST_SLACK = {"rafael": "C068PH3RFSM"}       # #alphalete-sales


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


# THE POSITIVE ONE (Megan 2026-09-26: "a positive call out for someone avg
# 25+ doors/hour knocked"). Knocks/Hr the way the board reads it -- total
# knocks over the raw span, first knock to last (render.py, per Raf and
# Megan) -- and only once the span is an hour, so five doors in ten minutes
# is not "30 an hour". Each rep is praised ONCE a day.
PACE_KNOCKS_PER_HOUR = 25
PACE_MIN_SPAN_MIN = 120     # 2+ hours of the target (Megan 2026-09-26: one hour is one hour of data)
# BOX IS JUDGED ON ACTUAL TALK-TO'S, NOT DOORS (Ryan McSpadden 2026-09-26:
# "change the Knocks per hour to actual TT per hour and make the recognition
# anyone that is average 10+ per hour"; Megan: for all Box campaigns).
# Actual Talk To's is the Box board's own number: Total Knocks minus the
# buckets where nobody was spoken to (render.BOX_ACTUAL_TALK_TO_SUBTRAHENDS).
PACE_BOX_TT_PER_HOUR = 10
BOX_TT_SUBTRAHENDS = ("Corp - No Opp", "Inaccessible", "Inaccurate Lead")

PACE_LINES = (
    "Snicklepop!! ⚡ {names} averaging {avg}+ {unit} an hour 🚪🚪🚪 That's how it's done 🔥",
    "{names} — {avg} {unit}/hr 🏃💨 Somebody's definitely not finger poppin' 🔥",
    "Pace check ⏱️ {names} at {avg} {unit} an hour. Keep that foot on the gas 🚀",
    "{avg} {unit}/hr from {names} 🚪🔥 The neighborhood knows your name by now 🏡",
    "¡Snicklepop! ⚡ {names} con {avg} {unit_es} por hora 🚪🚪🚪 Así se hace 🔥",
    "{names} a {avg} {unit_es} por hora 🏃💨 Eso no es finger poppin', eso es trabajo 💪",
)


def _span_minutes(first: str, last: str, now: dt.datetime):
    a = K._minutes_since(first, now)
    b = K._minutes_since(last, now)
    if a is None or b is None:
        return None
    return a - b


def _num(row: Dict, key: str) -> int:
    for k, v in row.items():
        if str(k).strip().lower() == key.lower():
            try:
                return int(str(v or "0").replace(",", "").strip() or 0)
            except ValueError:
                return 0
    return 0


def pace_metric(row: Dict, campaign=None) -> int:
    """The number a rep's hour is judged on: doors, or on Box the board's own
    Actual Talk To's (knocks minus the nobody-home buckets)."""
    knocks = _num(row, "Total Knocks")
    if str(campaign or "").strip().lower() == "b2b_box":
        return max(knocks - sum(_num(row, k) for k in BOX_TT_SUBTRAHENDS), 0)
    return knocks


def pace_target(campaign=None) -> int:
    return PACE_BOX_TT_PER_HOUR if str(campaign or "").strip().lower() == "b2b_box" else PACE_KNOCKS_PER_HOUR


def pace_units(campaign=None):
    """(english, spanish) for the line."""
    if str(campaign or "").strip().lower() == "b2b_box":
        return "talk-to's", "conversaciones"
    return "doors", "puertas"


def pace(rows: List[Dict], now: dt.datetime, campaign=None) -> List[Dict]:
    """[{name, avg}] for reps at the campaign's target, over 2+ hours."""
    out = []
    target = pace_target(campaign)
    for r in rows:
        name = str(r.get("Rep") or "").strip()
        n = pace_metric(r, campaign)
        span = _span_minutes(str(r.get("First Knock") or ""), str(r.get("Last Knock") or ""), now)
        if not name or not span or span < PACE_MIN_SPAN_MIN or n <= 0:
            continue
        avg = n / (span / 60.0)
        if avg >= target:
            out.append({"name": name, "avg": int(avg)})
    out.sort(key=lambda x: -x["avg"])
    return out


def pace_line(office_key: str, reps: List[Dict], now: dt.datetime, campaign=None) -> str:
    if not reps:
        return ""
    unit_en, unit_es = pace_units(campaign)
    seed = "pace|%s|%s|%d" % (office_key, now.date().isoformat(), now.hour)
    template = PACE_LINES[zlib.crc32(seed.encode("utf-8")) % len(PACE_LINES)]
    spanish = _is_spanish(template)
    firsts = []
    for r in reps:
        f = _first(r["name"])
        if f and f not in firsts:
            firsts.append(f)
    joiner = " y " if spanish else " and "
    names = firsts[0] if len(firsts) == 1 else ", ".join(firsts[:-1]) + joiner + firsts[-1]
    return template.format(names=names, avg=min(r["avg"] for r in reps), unit=unit_en, unit_es=unit_es)


def pace_callout(office_key: str, rows: List[Dict], now: dt.datetime, *, remember: bool = True, campaign=None) -> str:
    """The positive line, ONCE A DAY, on the day's numbers -- Megan 2026-09-26:
    "25+ doors should be if they are at that for the day - so after the final
    knock report it pulled". The caller decides when the day is over (the
    last tick of the office's window, or the last relay after the bell);
    this remembers that the day was judged so it is never judged twice, even
    when nobody hit the bar."""
    key = "pace:%s" % office_key
    state = _state()
    st = state.get(key) or {}
    if st.get("day") == now.date().isoformat():
        return ""
    text = pace_line(office_key, pace(rows, now, campaign), now, campaign)
    if remember:
        state[key] = {"day": now.date().isoformat(), "judged_at": now.isoformat(timespec="seconds")}
        _save(state)
    return text


# SATURDAY STOPS AT 5 (Raf, 2026-09-26: "Call outs need to stop at 5pm on
# Saturdays"). A HARD wall on the office's own clock, not a tweak to anybody's
# bell: Cyrus's Saturday bell is 17:15 and the after-the-bell window ran to
# 19:15, which is how call-outs were still landing at 6pm on a Saturday. Every
# office, both kinds of call-out, weekdays untouched.
SATURDAY = 5
SATURDAY_CUTOFF_H = 17


def callouts_allowed(now: dt.datetime) -> bool:
    """False once Saturday hits 5pm local. Weekdays are unaffected."""
    return not (now.weekday() == SATURDAY and now.hour >= SATURDAY_CUTOFF_H)


# NEVER THE SAME LINE TWICE INTO ONE ROOM INSIDE THIS MANY MINUTES. The backstop
# for "that cannot happen in any office" (Raf, 2026-09-26), and it is deliberately
# NOT our state file: it asks SLACK what is already in the room, so it still
# holds when the state file is missing, stale, unwritable or clobbered -- which
# is exactly the failure that put the same call-out in #ambient-sales-1 and
# #palace-sales every 60 seconds tonight. A de-dupe that depends on the thing
# that broke is not a backstop.
DUP_WINDOW_MIN = 90


def already_said(channel_id: str, text: str, now: dt.datetime, client=None) -> bool:
    """Is this EXACT line already in this room from the last DUP_WINDOW_MIN?

    FAILS CLOSED. If Slack cannot be read we report True (skip the post): one
    missed call-out costs a single tick and the next one retries, while guessing
    the other way is how a room gets ninety copies. That trade is the whole
    reason this exists.
    """
    try:
        if client is None:
            from automations.shared import slack_metrics_post as smp
            client = smp._client()
        oldest = (now - dt.timedelta(minutes=DUP_WINDOW_MIN)).timestamp()
        res = client.conversations_history(channel=channel_id, oldest=str(oldest),
                                           limit=60) or {}
        want = (text or "").strip()
        for m in res.get("messages") or []:
            if (m.get("text") or "").strip() == want:
                return True
        return False
    except Exception as e:  # noqa: BLE001
        print("[callouts] cannot read %s to de-dupe (%s: %s) — NOT posting; "
              "the next tick retries" % (channel_id, type(e).__name__, str(e)[:120]),
              flush=True)
        return True


def _say(channel_id: str, text: str, now: dt.datetime, log) -> None:
    """Post one call-out, unless that room already has this exact line."""
    if already_said(channel_id, text, now):
        log("%-14s already has this line in the last %d min — skipped"
            % (channel_id, DUP_WINDOW_MIN))
        return
    P._slack(channel_id, text)


def after_the_bell(office, now: dt.datetime, within_min: int = 120) -> bool:
    """Is `now` past this office's field day (today), and within `within_min`
    of it -- the window in which the day's last relay is the day's report?"""
    if now.weekday() == 6 or (now.weekday() == 5 and not getattr(office, "saturday", True)):
        return False
    end = office.sat_end if now.weekday() == 5 else office.day_end
    h, m = [int(x) for x in str(end).split(":")[:2]]
    end_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return end_at < now <= end_at + dt.timedelta(minutes=within_min)


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
        if (str(getattr(office, "campaign", "") or "att").strip().lower() not in CALLOUT_CAMPAIGNS
                and key not in CALLOUT_EXTRA_OFFICES):
            continue
        now = K._office_now(office)
        if not callouts_allowed(now):
            log("%-14s Saturday past %d:00 — call-outs are done for the week"
                % (key, SATURDAY_CUTOFF_H))
            continue
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
                _say(ch, text, now, log)
            except Exception as e:  # noqa: BLE001
                log("%-14s FAILED to post to %s: %s" % (key, ch, type(e).__name__))
    # THE POSITIVE ONE, after the bell: the day's numbers, once a day.
    for key in sorted(approved_ch):
        if only and key != only:
            continue
        office = O.get(key)
        if not office or (str(getattr(office, "campaign", "") or "att").strip().lower() not in CALLOUT_CAMPAIGNS
                          and key not in CALLOUT_EXTRA_OFFICES):
            continue
        now = K._office_now(office)
        if not callouts_allowed(now):
            continue
        if not after_the_bell(office, now):
            continue
        # THE DAY'S LAST RELAY IS THE DAY'S REPORT: the machine stops sweeping
        # at the bell, so "too old" does not apply here.
        krow = knocks.get(key) or next((r for k, r in knocks.items() if k.startswith(key) or key.startswith(k)), None)
        if not krow:
            continue
        try:
            rows = M.to_rows(json.loads(krow[K.KN_ROWS] or "[]"), json.loads(krow[K.KN_TRACKER] or "[]"))
        except ValueError:
            continue
        praise = pace_callout(key, rows, now, remember=send, campaign=getattr(office, "campaign", None))
        if not praise:
            continue
        dests = [c.id for c in (approved_ch.get(key) or [])]
        log("%-14s -> %s: %s" % (key, ", ".join(dests) or "-", praise))
        said.append(praise)
        if send:
            for ch in dests:
                try:
                    _say(ch, praise, now, log)
                except Exception as e:  # noqa: BLE001
                    log("%-14s FAILED to post to %s: %s" % (key, ch, type(e).__name__))
    if send:
        # MERGE, NEVER CLOBBER. `state` is the snapshot taken at the TOP of this
        # run, and pace_callout() persists its own `pace:<office>` marker
        # mid-run off a FRESH read. A plain _save(state) here wrote that marker
        # straight back out of existence, so the next tick saw the day as
        # unjudged and said the same thing again -- every 60 seconds, for the
        # whole 120-minute after_the_bell window. Cyrus's #ambient-sales-1 got
        # the identical "25 doors/hr" line five times at 5:43 PM (2026-09-26),
        # and aya and kash were in the same window.
        #
        # It clobbered BOTH WAYS: pace_callout's own _save writes a dict that
        # predates this run's negative-loop markers, and then this line threw
        # away its pace keys. Re-reading and layering this run's own updates on
        # top keeps both, and is safe because `state` cannot contain a pace key
        # written after it was loaded.
        merged = _state()
        merged.update(state)
        _save(merged)
    return said


# ONE COPY AT A TIME. On 2026-09-28 at 7:33pm the pace line landed FOUR times
# in #highline-b2b-box-sales and four times in #southshore-d2d-sales, all in
# the same minute: several poster runs overlapped, each asked Slack "is this
# line already there?" before any of the others had posted, and each said no.
# already_said() cannot see a message that does not exist yet, and the state
# file cannot stop a race it is written from inside of. post.py has held a
# pid lock since day one; this leg never did. An exclusive lock on one file,
# held for the run: a second copy finds it taken and leaves without posting.
LOCK_PATH = Path.home() / ".config" / "recruiting-report" / "icd_gap_callouts.lock"


def _take_lock():
    """The lock's open file handle, or None when another copy holds it."""
    import fcntl
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Lucy's hourly gap call-outs")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--office")
    args = ap.parse_args(argv)
    lock = _take_lock()
    if lock is None:
        print("[callouts] another copy is running -- leaving without posting", flush=True)
        return 0
    run(send=args.send, only=args.office)
    if not args.send:
        print("DRY RUN -- nothing posted, nothing remembered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
