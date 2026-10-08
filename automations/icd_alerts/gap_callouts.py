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
import re
import os
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Optional

from automations.icd_alerts import knocks_map as M, knocks_post as K, offices as O, post as P
from automations.icd_alerts import config as C

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
# ... and offices that asked OUT although their campaign is in. Colten
# 2026-09-29 (via Megan): "knock boards and call outs removed from his slack
# channel. He should only have sara+ alerts there". His knock board was
# switched off on the tab the same minute; this is the call-out half, both
# the 30-minute gap line and the end-of-day pace line.
CALLOUT_OPT_OUT = {"colten"}
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
    "Quiet check 🤫 {names} — {m}+ min without a door. Y'all finger poppin' out there? 🤌🤌",
    "{names} — {m}+ min without a dispo. Lucy sees you, finger poppers 👀🤌",
    # Megan 2026-10-07: "I like this one".
    "{names}: {m}+ min. The doors are right there. I can see them from here 👀🚪",
    # GIRLY ONES (Megan 2026-10-07: "we need some girly ones too"). Lucy's a she.
    "{names}, bestie 💅 {m}+ min without a door. The doors miss you 🚪",
    "It's giving coffee break ☕💅 {names} — {m}+ min, no dispo. Cute. Now knock 🚪",
    "Hi {names} 👋💁‍♀️ {m}+ min quiet. Not mad, just disappointed 😌 Knock something",
    "{names} — {m}+ min off the doors. Not to be dramatic but 💅 the board is waiting 📋",
    # Leila Hormozi's line, as the hashtag only (Megan 2026-10-07: "Lucy should
    # also use the #FYMFTP somewhere"). The acronym is the brand; spelling it
    # out is not Lucy's voice in every office's room.
    "{names} — {m}+ min off the doors. Not feeling it? Doesn't matter. #FYMFTP 🚪",
    "Mood says couch, plan says doors 🚪 {names}: {m}+ min. #FYMFTP",
    # The pony (Megan 2026-10-07): a sale is "found their pony", so a gap is
    # still digging for it.
    "{names} — {m}+ min off the doors. Still looking for that pony? 🐴 It's behind a door 🚪",
    "{names}: {m}+ min. The pony's not in the car 🐴 Go find it 🚪",
    "{names}: {m}+ min. Volume negates luck — and right now there's no volume 🚪",
    "{names} — {m}+ min off the doors. Obsessed or average? Your call 🚪 #BOBA",
    "{names}: {m}+ min. Time for massive action 🚪🔥",
    "{names} — {m}+ min off the doors. Average is a failing formula 🚪",
    "{names}: {m}+ min. Discipline equals freedom — and freedom's behind a door 🚪",
    "{names}: {m}+ min. Where focus goes, energy flows. Focus on a door 🚪",
    "{names}: {m}+ min. Discomfort builds the callous. Knock 🚪",
    # Megan 2026-10-07 (approved 1 and 3 of the scripture set).
    "{names} — {m}+ min. Knock and the door will be opened 🚪",
    "{names}: {m}+ min. Faith without works is dead 🚪 Go do the works",
    # BENEFIT OF THE DOUBT (Megan 2026-09-26): a quiet rep may be inside with
    # a customer. Half the pool leaves that door open.
    "{names} — {m}+ min without a dispo. Must be cooking up something good in there… right? 👨‍🍳🔥",
    "No dispo from {names} in {m}+ min. In a house with a customer? 🏠",
    "{names} — {m}+ min quiet. If that's a sale being cooked 🍳 take your time. If not… 👀",
    # EN ESPAÑOL TAMBIÉN (Megan 2026-09-26: "make lucy bilingual"). Same
    # pool, so some hours land in Spanish and some in English.
    "¡Snicklemeberries! 🫐 {names} — {m}+ min without a dispo. Finger poppin' or knocking? ¡Vamos! 🚪👀",
    "{names}: {m}+ min without a door 🚪 Doors don't knock themselves, ¡ándale! 🤷",
    "{names} — {m}+ min, no dispo, no sale. ☕ Cafecito's over — go find the dinero 💰",
    "⏱️ {m}+ minutes and not a single dispo from {names}. Lucy's watching, ¿eh? 👀",
    "{names} — {m}+ min quiet 🤫 If you're cooking up a sale 🍳 take your time. If not… ¡a trabajar! 👀",
    "Ojo 👁️ {names}: {m}+ min without a door. Working a sale 💰 or finger poppin'? 🤌",
)

# B2B / BOX TALK (Ryan McSpadden 2026-09-30: "Can we change these to more B2B
# talk? 'Just admiring the businesses?' 'Just hanging out with gatekeepers?'").
# A Box rep walks into businesses, not up to houses, so the doors/neighborhood
# lines above read wrong there. Same voice, same {names}/{m}; picked instead of
# LINES when the office's campaign is b2b_box. The D2D offices keep LINES.
B2B_LINES = (
    "No walk-ins 🏢 and no sales 💸 from {names} for {m}+ min. Everything okay, or just admiring the businesses? 👀",
    "{names} — {m}+ min without a dispo. Just hanging out with gatekeepers? 🚧🤝",
    "Snicklemeberries! 🫐 {names} — {m}+ min without a dispo. Finger poppin' or talking to owners? 🏢👀",
    "{names}: {m}+ min and nothing on the board 📋❌ The decision maker isn't going to find you 🤌",
    "🥷 Finger poppin' ninjas spotted: {names}. {m}+ min since a business. Storefronts don't walk in themselves 🏪",
    "{names} — {m}+ min, no dispo, no sale. ☕ Coffee break's over — go find the owner 💼",
    "⏱️ {m}+ minutes and not a single dispo from {names}. Front desk got you stuck? 👀",
    "{names} — {m}+ min quiet. Window shopping on Main Street? 🛍️ Walk in 🏢",
    "{names} — {m}+ min without a dispo. Must be in with the owner cooking up something good… right? 👨‍🍳🔥",
    "No dispo from {names} in {m}+ min. Sitting down with a decision maker? 💼",
    "{names} — {m}+ min without a dispo. Lucy sees you, finger poppers 👀🤌",
    "{names}: {m}+ min. The storefronts are right there. I can see them from here 👀🏢",
    "{names}, bestie 💅 {m}+ min without a walk-in. The owners miss you 🏢",
    "It's giving long lunch 🥗💅 {names} — {m}+ min, no dispo. Cute. Now walk in 🏢",
    "{names} — {m}+ min, no walk-ins. Mood's not the plan 🏢 #FYMFTP",
    "{names}: {m}+ min. The pony's not in the parking lot 🐴 It's inside 🏢",
    "{names}: {m}+ min. Volume negates luck — and right now there's no volume 🏢",
    "{names} — {m}+ min, no walk-ins. Obsessed or average? Your call 🏢 #BOBA",
    "{names}: {m}+ min. Time for massive action 🏢🔥",
    "{names} — {m}+ min, no walk-ins. Average is a failing formula 🏢",
    "{names}: {m}+ min. Discipline equals freedom — and freedom's inside a business 🏢",
    "{names}: {m}+ min. Where focus goes, energy flows. Focus on a storefront 🏢",
    "{names}: {m}+ min. Discomfort builds the callous. Walk in 🏢",
    "{names} — {m}+ min. Knock and the door will be opened 🏢",
    "{names}: {m}+ min. Faith without works is dead 🏢 Go do the works",
    # ...and the same Spanish phrases sprinkled in, like LINES.
    "¡Snicklemeberries! 🫐 {names} — {m}+ min without a dispo. Finger poppin' or talking to owners? ¡Vamos! 🏢👀",
    "{names} — {m}+ min, no dispo, no sale. Chatting up the recepcionista? 🚧",
    "⏱️ {m}+ minutes and not a single dispo from {names}. Lucy's watching, ¿eh? 👀",
    "{names} — {m}+ min quiet 🤫 If you're in with the owner 💼 take your time. If not… ¡a trabajar! 👀",
)


def is_box(campaign=None) -> bool:
    """Is this office's activity read from My Service Cloud?

    Keyed on config.SERVICECLOUD_CAMPAIGNS. Decides the Box-only maths: the
    pace is judged on the board's Actual Talk To's, not doors. The WORDING is
    wider than this -- see is_b2b (every B2B enrollment, Megan 2026-10-01).
    """
    return str(campaign or "").strip().lower() in C.SERVICECLOUD_CAMPAIGNS


def is_b2b(campaign=None) -> bool:
    """Does this office sell to businesses? ANY B2B enrollment, whatever the
    campaign (Megan 2026-10-01) -- config.is_b2b_campaign is the one rule."""
    return C.is_b2b_campaign(campaign)


def lines_for(campaign=None):
    """The call-out pool for an office's campaign: B2B talk for every B2B
    office, doors for D2D."""
    return B2B_LINES if is_b2b(campaign) else LINES


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


# ENGLISH WITH A FEW SPANISH PHRASES, NOT SPANISH SENTENCES (Megan 2026-10-06:
# "Lucy shouldn't talk in Spanish fully - just throw in a few Spanish
# phrases"). Every line is English and reads with "and"; the Spanish rides as
# a phrase (¡Vamos!, ¡ándale!, cafecito, dinero, ¡a trabajar!, eso es
# trabajo). No marker makes a line Spanish-only any more, so the " y " joiner
# and "N de ustedes" never fire; the code is kept so a Spanish-only line could
# be added back deliberately.
_SPANISH_MARKERS = ()


def _is_spanish(template: str) -> bool:
    return any(mk in template for mk in _SPANISH_MARKERS)


def line(office_key: str, callouts: List[Dict], now: dt.datetime, campaign=None) -> str:
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
    pool = lines_for(campaign)
    template = pool[zlib.crc32(seed.encode("utf-8")) % len(pool)]
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


# RECEIPTS (Megan 2026-10-07, "do 1"): reps answer the call-outs like a
# person -- "Lucy im in a cc chill", "I makin a sale", "Lucy you a liar" -- and
# their teammates pile on. When a rep Lucy called out last tick has a credit
# check (AT&T) or a sale (any campaign) behind the quiet by the next tick, she
# says so, by name, before anything else. It is the only line that makes her
# both funnier and more credible: the argument they already start, she now
# lets them win. Same voice, same seed-by-hour choice as LINES, English with a
# Spanish phrase here and there.
RECEIPT_LINES = (
    "Told you I was watching 👀 {names} just ran a credit check. Carry on 🫡",
    "{names} said 'I'm working'… and the board agrees 📋💰 Receipts. Respect 🫡",
    "Receipts are in 🧾 {names} had a credit check behind that quiet. Lucy stands corrected 🙌",
    "Called it quiet, {names} called it a pitch 🏠 Credit check's on the board. ¡Eso! 🔥",
    "{names}: quiet on the doors, loud on the board 📋💰 My bad, carry on 🫡",
    "Okay okay 🙌 {names} was in a house, not finger poppin'. Lucy takes it back… this time 👀",
    "Update: {names} wasn't admiring the neighborhood 🏡 Credit check ran. ¡Bien hecho! 🔥",
    "{names} just ran a credit check 📋 Called it too soon — now go get the sale 💰",
    "You showed me 🫡 {names} — credit check behind the quiet. ¡Así se hace! 💰",
    "Okay {names}, I see you 💅 Credit check behind the quiet. Period. 💰",
    "Say less 💁‍♀️ {names} was working the whole time. Lucy apologizes 🫡",
    "{names} proved me wrong 🧾 and I love being wrong 🫡 Credit check's on the board — go close it 💰",
    "{names} — credit check behind the quiet. The work works 🫡💰",
    "{names} had a credit check behind the quiet. Good. 🫡",
    "{names} executed 📋💰 The board agrees. Ideas are easy, execution is everything 🫡",
    "{names} had a credit check behind the quiet. Ordinary people choosing extraordinary 🫡",
)
# The same idea for a business office: no credit checks on Box, so what moves
# is a sale.
B2B_RECEIPT_LINES = (
    "Told you I was watching 👀 {names} just put one on the board. Carry on 🫡",
    "{names} said 'I'm with the owner'… and walked out with a sale 💼💰 Receipts. Respect 🫡",
    "Receipts are in 🧾 {names} had a deal behind that quiet. Lucy stands corrected 🙌",
    "Okay okay 🙌 {names} was with a decision maker, not finger poppin'. Lucy takes it back… this time 👀",
    "{names}: quiet on the storefronts, loud on the board 📋💰 My bad, carry on 🫡",
    "You showed me 🫡 {names} — a sale behind the quiet. ¡Así se hace! 💼",
    "Okay {names}, I see you 💅 Deal behind the quiet. Period. 💼",
    "{names} proved me wrong 🧾 and I love being wrong 🫡 Deal's on the board 💼",
    "{names} — deal behind the quiet. The work works 🫡💼",
    "{names} had a deal behind the quiet. Good. 🫡",
    "{names} executed 📋💼 The board agrees. Ideas are easy, execution is everything 🫡",
    "{names} had a deal behind the quiet. Ordinary people choosing extraordinary 🫡",
)


def receipt_lines_for(campaign=None):
    return B2B_RECEIPT_LINES if is_b2b(campaign) else RECEIPT_LINES


def receipts(called: List[str], records_now: Dict[str, int], records_prev: Dict[str, int]) -> List[str]:
    """Who, of the reps called out LAST tick, has activity now that they did
    not have then. Pure. Order kept from the call-out (longest gap first)."""
    now_n = {_key(k): int(v or 0) for k, v in (records_now or {}).items()}
    prev_n = {_key(k): int(v or 0) for k, v in (records_prev or {}).items()}
    out = []
    for name in called or []:
        n = str(name or "").strip()
        if n and now_n.get(_key(n), 0) > prev_n.get(_key(n), 0):
            out.append(n)
    return out


def receipt_line(office_key: str, names: List[str], now: dt.datetime, campaign=None) -> str:
    """One receipts sentence, in the house voice, seeded like line()."""
    firsts = []
    for n in names or []:
        f = _first(n)
        if f and f not in firsts:
            firsts.append(f)
    if not firsts:
        return ""
    pool = receipt_lines_for(campaign)
    seed = "receipt|%s|%s|%d" % (office_key, now.date().isoformat(), now.hour)
    template = pool[zlib.crc32(seed.encode("utf-8")) % len(pool)]
    joined = firsts[0] if len(firsts) == 1 else ", ".join(firsts[:-1]) + " and " + firsts[-1]
    return template.format(names=joined)


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
    if not due(st, now, CALLOUT_EVERY_OVERRIDES.get(key)):
        return ""
    prev = (st.get("records") or {}) if st.get("day") == now.date().isoformat() else dict(records_now or {})
    text = line(key, pick_from_gaps(gaps, records_now, prev), now)
    if remember:
        _remember(key, {"day": now.date().isoformat(), "last_at": now.isoformat(timespec="seconds"),
                        "records": dict(records_now or {})})
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
    "¡Snicklepop! ⚡ {names} averaging {avg} {unit} an hour 🚪🚪🚪 ¡Así se hace! 🔥",
    "{names} at {avg} {unit}/hr 🏃💨 That's not finger poppin', eso es trabajo 💪",
    # Alex Hormozi's (Megan 2026-10-07): volume negates luck.
    "{names} — {avg} {unit}/hr 🏃💨 Volume negates luck 🔥",
    # Grant Cardone's, as the hashtag (Megan 2026-10-07: "we can use the #BOBA
    # in places too"): Be Obsessed or Be Average.
    "{names} at {avg} {unit}/hr 🔥 Obsessed, not average. #BOBA",
    # Megan 2026-10-07 "approve ALL the other ones": Cardone, Eric Thomas, Goggins.
    "{names} — {avg} {unit}/hr 🏃💨 That's 10X energy 🔥",
    "{names} at {avg} {unit}/hr. Wanting it as bad as you want to breathe 🔥",
    "{names} — {avg} {unit}/hr 🚣🔥 Who's gonna carry the boats? You are.",
    # Goggins (Megan 2026-10-07: "taking souls for sure").
    "{names} at {avg} {unit}/hr. Taking souls 🔥",
    "{names} — {avg} {unit}/hr. So much winning 🔥",
    # Naruto (Megan 2026-10-07).
    "{names} at {avg} {unit}/hr. Hokage pace 🍥🔥",
)

# The same recognition in business talk for the Service Cloud offices (Megan
# 2026-10-01). The D2D pool above says doors and neighborhoods; a Box rep is
# judged on talk-to's inside businesses.
B2B_PACE_LINES = (
    "Snicklepop!! ⚡ {names} averaging {avg}+ {unit} an hour 🏢🏢🏢 That's how it's done 🔥",
    "{names} — {avg} {unit}/hr 🏃💨 Somebody's definitely not finger poppin' 🔥",
    "Pace check ⏱️ {names} at {avg} {unit} an hour. Keep walking in 🚀",
    "{avg} {unit}/hr from {names} 🏢🔥 Every owner on the block knows your name by now 💼",
    "¡Snicklepop! ⚡ {names} averaging {avg} {unit} an hour 🏢🏢🏢 ¡Así se hace! 🔥",
    "{names} at {avg} {unit}/hr 🏃💨 That's not finger poppin', eso es trabajo 💪",
    "{names} — {avg} {unit}/hr 🏃💨 Volume negates luck 🔥",
    "{names} at {avg} {unit}/hr 🔥 Obsessed, not average. #BOBA",
    "{names} — {avg} {unit}/hr 🏃💨 That's 10X energy 🔥",
    "{names} at {avg} {unit}/hr. Wanting it as bad as you want to breathe 🔥",
    "{names} — {avg} {unit}/hr 🚣🔥 Who's gonna carry the boats? You are.",
    "{names} at {avg} {unit}/hr. Taking souls 🔥",
    "{names} — {avg} {unit}/hr. So much winning 🔥",
    "{names} at {avg} {unit}/hr. Hokage pace 🍥🔥",
)


def pace_lines_for(campaign=None):
    """The pace-recognition pool: business talk for Box, doors for D2D."""
    return B2B_PACE_LINES if is_b2b(campaign) else PACE_LINES


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
    if is_box(campaign):
        return max(knocks - sum(_num(row, k) for k in BOX_TT_SUBTRAHENDS), 0)
    return knocks


def pace_target(campaign=None) -> int:
    return PACE_BOX_TT_PER_HOUR if is_box(campaign) else PACE_KNOCKS_PER_HOUR


def pace_units(campaign=None):
    """(english, spanish) for the line."""
    if is_box(campaign):
        return "talk-to's", "conversaciones"
    if is_b2b(campaign):
        return "walk-ins", "visitas"
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
    pool = pace_lines_for(campaign)
    template = pool[zlib.crc32(seed.encode("utf-8")) % len(pool)]
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
        _remember(key, {"day": now.date().isoformat(), "judged_at": now.isoformat(timespec="seconds")})
    return text


# SATURDAY STOPS AT 5 (Raf, 2026-09-26: "Call outs need to stop at 5pm on
# Saturdays"). A HARD wall on the office's own clock, not a tweak to anybody's
# bell: Cyrus's Saturday bell is 17:15 and the after-the-bell window ran to
# 19:15, which is how call-outs were still landing at 6pm on a Saturday. Every
# office, both kinds of call-out. Weekdays have their own wall, just below.
SATURDAY = 5
SATURDAY_CUTOFF_H = 17

# MONDAY-FRIDAY STOPS AT 8:30 (Raf, 2026-09-28: an 8:30 PM cutoff for Lucy's
# call-outs, every office, on the office's own clock, "unless they've asked for
# a different time"). Same hard wall as Saturday's, both kinds of call-out --
# the gap line and the positive pace line. Boards, metrics and the gap list on
# the board caption are NOT call-outs and are untouched. Sunday is untouched
# too: field hours already keep it silent.
WEEKDAY_CUTOFF = "20:30"
# AN OFFICE THAT ASKED FOR A DIFFERENT WEEKDAY TIME: office key -> "HH:MM" on
# their own clock. Empty on purpose -- as of 2026-09-28 no office has asked
# (Carlos's `sat_stop` 17:30 in gap_alerts/config.py is a Saturday cap on his
# guest rooms' boards and lists, and it still applies). The keys are the ECO
# office keys, plus gap_alerts' host key ("rafael") for Raf's own reps.
CALLOUT_CUTOFF_OVERRIDES: Dict[str, str] = {}


def callout_cutoff(now: dt.datetime, office_key: Optional[str] = None):
    """(hour, minute) past which no call-out leaves today, on the office's own
    clock -- or None when there is no wall (Sunday)."""
    if now.weekday() == SATURDAY:
        return (SATURDAY_CUTOFF_H, 0)
    if now.weekday() == 6:
        return None
    text = CALLOUT_CUTOFF_OVERRIDES.get(str(office_key or "").strip().lower()) or WEEKDAY_CUTOFF
    return O._hm(text)


def callouts_allowed(now: dt.datetime, office_key: Optional[str] = None) -> bool:
    """False at or after the day's cutoff on the office's clock: 5pm Saturday,
    8:30pm Monday-Friday (or the office's own weekday time). `now` must already
    be the OFFICE's local time."""
    cut = callout_cutoff(now, office_key)
    return cut is None or (now.hour, now.minute) < cut


def cutoff_label(now: dt.datetime, office_key: Optional[str] = None) -> str:
    cut = callout_cutoff(now, office_key)
    return "no cutoff" if cut is None else "%d:%02d" % cut


# THE PRAISE LANDS BEFORE THE WALL (Raf, 2026-09-28: "Keep the praise one").
# The positive pace line used to wait for the bell, and almost every office's
# bell is at or after the cutoff -- so the wall silenced it. When the field day
# runs up to (or past) the cutoff, the praise goes in the last PRAISE_LEAD_MIN
# before it instead; an office whose day ends earlier keeps its after-the-bell
# timing, still capped by the wall. The gap call-outs are NOT moved: they stop
# hard at the cutoff. ONCE A DAY is still pace_callout's `pace:<office>` marker
# (plus the lock and the room de-dupe) -- this only decides WHEN it may fire.
PRAISE_LEAD_MIN = 10


def _at(now: dt.datetime, hm) -> dt.datetime:
    return now.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)


def praise_window(office, now: dt.datetime, office_key: Optional[str] = None,
                  lead_min: int = PRAISE_LEAD_MIN) -> bool:
    """May the day's positive line go out now? For the every-minute poster.
    `now` is the office's local time."""
    cut = callout_cutoff(now, office_key)
    if cut is None or (now.weekday() == SATURDAY and not getattr(office, "saturday", True)):
        return False
    cut_at = _at(now, cut)
    if now >= cut_at:
        return False
    end_at = _at(now, O._hm(office.sat_end if now.weekday() == SATURDAY else office.day_end))
    if end_at < cut_at - dt.timedelta(minutes=lead_min):
        return after_the_bell(office, now)
    return now >= cut_at - dt.timedelta(minutes=lead_min)


def praise_tick(now: dt.datetime, office_key: Optional[str], window_end_hm,
                tick_min: int) -> bool:
    """The same rule for a fixed-cadence runner (gap_alerts, every tick_min):
    is this the LAST tick before whichever comes first -- the office window's
    end (inclusive, the old last-tick-of-day rule) or the call-out cutoff
    (exclusive)? `now` is the office's local time."""
    cut = callout_cutoff(now, office_key)
    if cut is None or not window_end_hm:
        return False
    cut_at, end_at = _at(now, cut), _at(now, window_end_hm)
    step = dt.timedelta(minutes=tick_min)
    if end_at < cut_at:
        return now <= end_at < now + step
    return cut_at - step <= now < cut_at


# NEVER THE SAME LINE TWICE INTO ONE ROOM INSIDE THIS MANY MINUTES. The backstop
# for "that cannot happen in any office" (Raf, 2026-09-26), and it is deliberately
# NOT our state file: it asks SLACK what is already in the room, so it still
# holds when the state file is missing, stale, unwritable or clobbered -- which
# is exactly the failure that put the same call-out in #ambient-sales-1 and
# #palace-sales every 60 seconds tonight. A de-dupe that depends on the thing
# that broke is not a backstop.
DUP_WINDOW_MIN = 90


def _norm(text) -> str:
    """Words only. Slack hands a posted line back with its emoji turned into
    :shortcodes: (our ⏱️ came back as ':stopwatch:'), so an exact comparison
    never matched and already_said() said "not yet" to a line already in the
    room twenty times (2026-09-28). Letters, digits and spaces are what the
    two copies have in common, so that is what is compared."""
    import re as _re
    plain = _re.sub(r":[a-z0-9_+\-]+:", " ", (text or "").lower())   # :stopwatch: -> gone
    keep = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in plain)
    return " ".join(keep.split())


def _content_key(text) -> str:
    """The reps and the numbers in a line, wording dropped -- '' when it has
    neither, so a line with no names and no numbers is compared by its words."""
    import re as _re
    raw = text or ""
    names = sorted({w for w in _re.findall(r"[A-Z][a-z]+", raw)
                    if w not in ("Lucy", "Pace", "Quiet", "Keep", "Eso", "Ojo", "Y", "Cx", "Nl")})
    nums = sorted(_re.findall(r"\d+", _norm(raw)))
    if not names and not nums:
        return ""
    return " ".join(names) + "|" + " ".join(nums)


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
        want = _norm(text)
        want_key = _content_key(text)
        for m in res.get("messages") or []:
            said = m.get("text") or ""
            if _norm(said) == want:
                return True
            # SAME REPS, SAME NUMBERS, DIFFERENT WORDING is still the same
            # call-out. The lines are picked at random, so a repeat rarely
            # matches word for word (Maxamad's room, 2026-09-28 20:25: two
            # templates about the same eight reps in one minute).
            if want_key and _content_key(said) == want_key:
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
    """The markers: which office was called out when, and which day's pace
    was judged. A CORRUPT FILE IS SET ASIDE AND SAID OUT LOUD, never silently
    read as empty: on 2026-09-28 four overlapping runs wrote it at once, the
    result was not JSON, every read after that returned {} -- no office had
    ever been judged -- and Colten's room got the same pace line twenty times
    over the next hour, on every tick, lock or no lock."""
    try:
        return json.loads(STATE_PATH.read_text())
    except OSError:
        return {}
    except ValueError:
        try:
            aside = STATE_PATH.with_suffix(".corrupt-%s.json" % dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
            STATE_PATH.replace(aside)
            print("[callouts] STATE FILE WAS NOT JSON -- moved to %s and starting "
                  "empty; today's markers are gone" % aside.name, flush=True)
        except OSError:
            pass
        return {}


def _remember(key: str, value: Dict) -> None:
    """Write ONE marker: fresh read, set the key, save. Never a snapshot.

    THE 2026-09-28 REPEATS, THIRD CAUSE. run() loaded the whole file at its
    top, pace_callout() wrote today's `pace:<office>` mid-run, and run()'s
    end-of-run merge layered its top-of-run snapshot back over the file --
    including that office's pace marker from YESTERDAY, which it had loaded.
    Next tick: not judged today. Post. Every tick, for every office that had
    ever been judged before. A marker is written by re-reading the file and
    setting only itself, so nothing can put an old value back."""
    fresh = _state()
    fresh[key] = value
    _save(fresh)


def _save(state: Dict) -> None:
    """Whole file or nothing: write beside it, then rename into place, so a
    reader never sees half a file and two writers cannot interleave."""
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp-%d" % os.getpid())
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, STATE_PATH)
    except OSError as e:
        print("[callouts] could not save the state file: %s: %s" % (type(e).__name__, e), flush=True)


# Per-key cadence, where a room asked for its own (Carlos 2026-10-03: his
# crew's call-outs "about every hour"). Keys as the state file spells them.
CALLOUT_EVERY_OVERRIDES = {"guest:rafael:carlos-hidalgo": 60}


def due(state_for_office: Optional[Dict], now: dt.datetime,
        every: Optional[int] = None) -> bool:
    if not state_for_office or state_for_office.get("day") != now.date().isoformat():
        return True
    last = P._parse_when(state_for_office.get("last_at") or "")
    return last is None or (now - last) >= dt.timedelta(
        minutes=every or CALLOUT_EVERY_MIN)


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
        if key in CALLOUT_OPT_OUT:
            continue
        # A RETIRED KEY STILL HAS AN APPROVAL ROW. Jennifer's form minted
        # jennifer + jennifer-att into one room; the duplicate key was retired
        # 2026-10-06, yet the loop ran it off the sibling's relay row and
        # #figspire got every call-out twice. Only live offices speak.
        if not getattr(office, "active", True):
            continue
        if (str(getattr(office, "campaign", "") or "att").strip().lower() not in CALLOUT_CAMPAIGNS
                and key not in CALLOUT_EXTRA_OFFICES):
            continue
        now = K._office_now(office)
        if not callouts_allowed(now, key):
            log("%-14s past the %s call-out cutoff (%s their time) — done for the day"
                % (key, cutoff_label(now, key), now.strftime("%a %H:%M")))
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
        # RECEIPTS FIRST: whoever Lucy named last tick and who has since run a
        # credit check or put up a sale gets told so, before today's list.
        called_before = list(st.get("called") or []) if st.get("day") == now.date().isoformat() else []
        proven = receipts(called_before, records, prev)
        receipt = receipt_line(key, proven, now, getattr(office, "campaign", None))
        callouts = pick(rows, records, prev, now)
        text = line(key, callouts, now, getattr(office, "campaign", None))
        state[key] = {"day": now.date().isoformat(), "last_at": now.isoformat(timespec="seconds"),
                      "records": records, "called": [c["name"] for c in callouts]}
        if send:
            _remember(key, state[key])
        dests = [c.id for c in (approved_ch.get(key) or [])]
        for msg in (receipt, text):
            if not msg:
                continue
            log("%-14s -> %s: %s" % (key, ", ".join(dests) or "-", msg))
            said.append(msg)
            if not send:
                continue
            for ch in dests:
                try:
                    _say(ch, msg, now, log)
                except Exception as e:  # noqa: BLE001
                    log("%-14s FAILED to post to %s: %s" % (key, ch, type(e).__name__))
        if not text and not receipt:
            log("%-14s nobody over %d min without a credit check -- nothing to say" % (key, GAP_MIN))
    # THE POSITIVE ONE, at the end of the day: the day's numbers, once a day --
    # in the last minutes before the cutoff, or after the bell when the day
    # ends earlier than that (praise_window).
    for key in sorted(approved_ch):
        if only and key != only:
            continue
        office = O.get(key)
        if key in CALLOUT_OPT_OUT or not getattr(office, "active", True):
            continue
        if not office or (str(getattr(office, "campaign", "") or "att").strip().lower() not in CALLOUT_CAMPAIGNS
                          and key not in CALLOUT_EXTRA_OFFICES):
            continue
        now = K._office_now(office)
        if not callouts_allowed(now, key):
            continue
        if not praise_window(office, now, key):
            continue
        # THE DAY'S LAST RELAY IS THE DAY'S REPORT: the machine stops sweeping
        # at the bell, so "too old" does not apply here. Before the bell it is
        # simply the latest relay.
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
    # ANSWER BACK, last: a rep who replied "snitch" or "liar" under a recent
    # call-out hears from Lucy once in that thread. Read-only on Slack except
    # for that one reply; never blocks the call-outs above.
    try:
        said.extend(answer_back(dt.datetime.now(), send=send, log=log))
    except Exception as e:  # noqa: BLE001
        log("answer_back skipped: %s" % type(e).__name__)
    # NO SNAPSHOT SAVE HERE. Every marker was written the moment it was
    # decided (_remember), off a fresh read; saving this run's top-of-run
    # snapshot now would put yesterday's pace markers back (2026-09-28).
    return said


# ONE COPY AT A TIME. On 2026-09-28 at 7:33pm the pace line landed FOUR times
# in #highline-b2b-box-sales and four times in #southshore-d2d-sales, all in
# the same minute: several poster runs overlapped, each asked Slack "is this
# line already there?" before any of the others had posted, and each said no.
# already_said() cannot see a message that does not exist yet, and the state
# file cannot stop a race it is written from inside of. post.py has held a
# pid lock since day one; this leg never did. An exclusive lock on one file,
# held for the run: a second copy finds it taken and leaves without posting.
# ANSWERING BACK (Megan 2026-10-07, "do 4 ... 'Not snitching, HYPING! Keep
# going!' or 'giving you an intro'"). Reps reply to the call-outs -- "lucy
# snitched already", "Lucy you a liar", "Lucy u lying on me" -- and their
# teammates pile on. When a reply under one of Lucy's call-outs says so, she
# answers ONCE in that thread, in the same voice. Never top-level, never
# twice, never to herself.
SNITCH_TRIGGER = re.compile(r"\bsnitch", re.I)
LIAR_TRIGGER = re.compile(r"\b(liar|lying|lyin|lie|cap|capping|cappin)\b", re.I)
SNITCH_REPLIES = (
    "Not snitching, HYPING 📣 Keep going! 🔥",
    "Not snitching — giving you an intro 🚪😉 Now go close it 💰",
    "Snitch? Nah. Hype man 📣",
    "Lucy doesn't snitch. Lucy announces 📣 Your move 💰",
    "¡Tranquilo! Not snitching, hyping 📣 Go knock another! 🚪",
    "Not snitching, hyping, bestie 💅📣 Keep going!",
)
# A business room hears the same, minus the doors.
SNITCH_REPLIES_B2B = tuple(
    t.replace("Go knock another! 🚪", "Go get another one! 🏢").replace(" 🚪😉", " 😉")
    for t in SNITCH_REPLIES)
LIAR_REPLIES = (
    "Not lying, just reading the board 📋 Show me 👀💰",
    "The board said it, not me 📋🤷‍♀️ Put one up and I'll say so 🫡",
    "Lucy's never lied, Lucy's just early 😌 Go make me say receipts 🧾",
    "¡Ojo! Not lying — the board moves when you do 📋💰 Show me",
    "Me? Lie? 💅 The board doesn't lie 📋 Show me 👀",
)
ANSWER_BACK_EVERY_MIN = 10        # how often the threads are scanned
ANSWER_BACK_LOOKBACK_MIN = 180    # how far back a call-out can be answered


def answer_for(reply_text: str, seed: str, campaign=None) -> str:
    """The one-line answer a rep's reply earns, or "" when it earns none."""
    t = str(reply_text or "")
    if SNITCH_TRIGGER.search(t):
        pool = SNITCH_REPLIES_B2B if is_b2b(campaign) else SNITCH_REPLIES
    elif LIAR_TRIGGER.search(t):
        pool = LIAR_REPLIES
    else:
        return ""
    return pool[zlib.crc32(seed.encode("utf-8")) % len(pool)]


def _is_ours(msg: Dict, me: str) -> bool:
    return bool(msg.get("bot_id")) or (bool(me) and msg.get("user") == me)


def answer_back(now: dt.datetime, *, send: bool, log=print, channels=None, client=None) -> List[str]:
    """Scan Lucy's recent call-outs in every live room for a reply that calls
    her a snitch or a liar, and answer once per thread. Returns what it said
    (or would say). Throttled to ANSWER_BACK_EVERY_MIN; state keeps the
    threads already answered so a second scan never doubles up."""
    state = _state()
    st = state.get("answer_back") or {}
    last = P._parse_when(st.get("last_at") or "")
    if send and last is not None and (now - last) < dt.timedelta(minutes=ANSWER_BACK_EVERY_MIN):
        return []
    answered = dict(st.get("answered") or {})
    cutoff = (now - dt.timedelta(minutes=ANSWER_BACK_LOOKBACK_MIN * 2)).isoformat(timespec="seconds")
    answered = {k: v for k, v in answered.items() if str(v) >= cutoff}
    try:
        if client is None:
            from automations.shared import slack_metrics_post as smp
            client = smp._client()
        me = ""
        try:
            me = (client.auth_test() or {}).get("user_id") or ""
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        log("answer_back: no Slack client (%s) -- skipped" % type(e).__name__)
        return []
    approved_all = P.approved_channels()
    if channels is None:
        channels = sorted({c.id for k, cs in approved_all.items()
                           if cs and O.is_enrolled(k) for c in cs})
    # Which campaign a room belongs to, for the wording (doors vs. storefronts).
    room_campaign: Dict[str, str] = {}
    for k, cs in approved_all.items():
        office = O.get(k)
        if not cs or not office or not getattr(office, "active", True):
            continue
        for c in cs:
            room_campaign.setdefault(c.id, str(getattr(office, "campaign", "") or "att"))
    said = []
    oldest = str((now - dt.timedelta(minutes=ANSWER_BACK_LOOKBACK_MIN)).timestamp())
    for ch in channels:
        try:
            res = client.conversations_history(channel=ch, oldest=oldest, limit=40) or {}
        except Exception as e:  # noqa: BLE001
            log("answer_back: cannot read %s (%s)" % (ch, type(e).__name__))
            continue
        for m in res.get("messages") or []:
            ts = str(m.get("ts") or "")
            if not ts or not _is_ours(m, me) or int(m.get("reply_count") or 0) == 0:
                continue
            tkey = "%s:%s" % (ch, ts)
            if tkey in answered:
                continue
            try:
                rep = client.conversations_replies(channel=ch, ts=ts, limit=30) or {}
            except Exception as e:  # noqa: BLE001
                log("answer_back: cannot read thread %s (%s)" % (tkey, type(e).__name__))
                continue
            replies = [r for r in (rep.get("messages") or []) if str(r.get("ts")) != ts]
            if any(_is_ours(r, me) for r in replies):
                answered[tkey] = now.isoformat(timespec="seconds")   # already spoke here
                continue
            answer = ""
            for r in replies:
                answer = answer_for(r.get("text") or "", "answer|%s|%s" % (ch, ts),
                                    room_campaign.get(ch))
                if answer:
                    break
            if not answer:
                continue
            log("answer_back %s -> %s" % (tkey, answer))
            said.append(answer)
            if send:
                try:
                    P._slack(ch, answer, thread_ts=ts)
                    answered[tkey] = now.isoformat(timespec="seconds")
                except Exception as e:  # noqa: BLE001
                    log("answer_back: FAILED to reply in %s (%s)" % (tkey, type(e).__name__))
    if send:
        _remember("answer_back", {"last_at": now.isoformat(timespec="seconds"), "answered": answered})
    return said


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
