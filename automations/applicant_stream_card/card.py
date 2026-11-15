# -*- coding: utf-8 -*-
"""Build and draw the Applicant Stream Grade Card.

Megan 2026-11-12, on the first draft: "This card is crazy long ... The top
should be like the top 3 focuses to fix ASAP ... short, simple. They need
to have action items and then they can click on something to explain why."
And: "just click the recruiter name and have their full scorecard show."

So the page is:

    Fix these first        3 one-line actions; click one -> why + steps
    Your scorecard         one short line per section; click -> numbers
                           and that section's own action list
    Recruiters             names; click one -> their FULL scorecard inline

Nothing else is open by default.

Rules it keeps (from the audit it is built on):
  * A section with no data is GREY — never green.
  * The booking data only holds people who booked, so the AI/recruiter
    split is "of everyone booked".
  * Wrong information (address, Zoom, phone, dead link) ranks first: it
    sends a real applicant to the wrong place today.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import datetime as dt
import html
import re

from automations.applicant_stream_card import fixes as F
from automations.applicant_stream_card import setup_page as SP
from automations.applicant_stream_card import changes as CH

GREEN, YELLOW, RED, GREY = "green", "yellow", "red", "grey"
DOT = {GREEN: "#22A35A", YELLOW: "#E8A317", RED: "#D93A3A", GREY: "#9AA0A6"}

# Findings that put wrong information in front of an applicant.
WRONG_INFO = {"WRONG ROOM", "WRONG MEETING ID", "WRONG ADDRESS", "WRONG CITY",
              "CHECK PHONE", "DEAD LINK", "MERGE", "ADDRESS"}
# A live template whose whole body is "test" is wording, not wrong info,
# but it reaches applicants today, so it ranks with the AI faults.
# The AI answering an applicant with nothing, or the wrong thing.
AI_BROKEN = {"SILENT AND BLANK", "DEFLECTS", "PROMISES A CALL",
             "PAY WORDING", "AI IS A REAL PERSON", "SAME NAME", "ROUTING"}
WORDING = {"SHOUTING", "BASE PAY", "NOT PLAIN TEXT", "TOO LONG", "GRAMMAR",
           "NO OPT-OUT", "TYPO", "HOUSE RULE"}

# A pull older than this is flagged. The AI Settings page changed completely
# on 29-30 Oct; an older pull grades an office on a setup it no longer has.
STALE_DAYS = 7
# Share booked a day or more after being processed.
LATE_OK, LATE_BAD = 15.0, 25.0
FOLD_AT = 3
TOP_N = 3


def _pct(x):
    return "-" if x is None else "{:.0f}%".format(x)


def _hrs(h):
    if h is None:
        return "-"
    if h < 1:
        return "{:.0f} min".format(h * 60)
    if h < 48:
        return "{:.1f} hrs".format(h)
    return "{:.1f} days".format(h / 24.0)


def _line(key, icon, title, dot, short, text="", facts=None, items=None,
          action=None):
    """`short` is the front of the card (a few words). `text`, `facts` and
    `items` only show when the line is clicked. `action` is a to-do this
    section adds to "Fix these first" when it is off target."""
    return {"key": key, "icon": icon, "title": title, "dot": dot,
            "short": short, "text": text, "facts": facts or [],
            "items": items or [], "action": action}


# ------------------------------------------------------- one-line actions

ACTION = {
    "WRONG ROOM": "Fix the Zoom link in {w}",
    "WRONG MEETING ID": "Fix the Zoom meeting ID in {w}",
    "WRONG ADDRESS": "Fix the address in {w}",
    "WRONG CITY": "Fix the city in {w}",
    "CHECK PHONE": "Check the phone number in {w}",
    "DEAD LINK": "Retype the broken link in {w}",
    "MERGE": "Fix the blank fill-in field in {w}",
    "PLACEHOLDER": "Replace the “test” message in {w}",
    "ADDRESS": "Send eStream your full address with the suite",
    "NO OPT-OUT": "Add “Reply STOP to opt out” to {w}",
    "SHOUTING": "Take the all-caps out of {w}",
    "BASE PAY": "Take “base pay” out of {w}",
    "NOT PLAIN TEXT": "Swap curly quotes and long dashes in {w}",
    "TOO LONG": "Shorten {w}",
    "GRAMMAR": "Fix the grammar in {w}",
    "SILENT AND BLANK": "The AI says nothing to “{w}”",
    "DEFLECTS": "Make the AI answer “{w}” instead of dodging",
    "PROMISES A CALL": "Take the call-time promise out of “{w}”",
    "PAY WORDING": "Fix the pay wording in “{w}”",
    "ROUTING": "Not all of our recommended AI replies are active and set "
               "to the right escalation type",
    "AI IS A REAL PERSON": "Rename the AI so it isn't a real teammate",
    "SAME NAME": "Make the escalation contact a real recruiter",
    "NAME MISMATCH": "Match the AI's name to your templates",
    "WRONG TITLE": "Change the escalation title to who really calls",
    "ONE INTERVIEW TYPE": "Set Interview Type to your 1st round",
    "PREF offered_buffer": "Set the AI's offered buffer to 60",
    "PREF accepted_buffer": "Set the AI's accepted buffer to 60",
    "PREF ghosting_threshold": "Set ghosting to 60 minutes",
}


def _short_where(item):
    w = item.get("where") or ""
    if item.get("count"):
        noun = "templates" if item["source"] == "Templates" else "rows"
        return "{} {}".format(item["count"], noun)
    w = w.split(" (the one")[0]
    if item["source"] == "Templates" and " / " in w:
        w = w.split(" / ")[0]
    return "“{}”".format(w) if item["source"] == "Templates" else w


def action_of(item):
    """One plain line; '(you or Aptel)' when Aptel can do it for them."""
    line = _action(item)
    return "{} (you or Aptel)".format(line) if item.get("owner") else line


def _action(item):
    """One plain line for an item, e.g. 'Fix the address in "Directions"'."""
    k = item["kind"]
    if k == "TYPO":
        return "Coach {}: {}".format(item["where"], item["title"].split(
            " — ")[0].lower())
    if k == "HOUSE RULE":
        return "Coach {}: {}".format(item["where"], item["title"].split(
            " — ")[0].lower())
    tpl = ACTION.get(k)
    if not tpl:
        return "{}: {}".format(item["title"], item["where"])
    w = _short_where(item)
    if item["source"] != "Templates":
        w = w.strip("“”")
    return tpl.format(w=w)


# ------------------------------------------------------------ sections

def who_books(st):
    w = (st or {}).get("who") or {}
    t = "AI vs recruiters"
    if not w.get("ok"):
        return _line("who", "\U0001F916", t, GREY, "Not checked")
    ai, hu = w["ai_show"], w["human_show"]
    facts = [
        ("Booked by the AI", "{:.0f}% ({:,})".format(w["ai_share"], w["ai_n"])),
        ("Booked by a recruiter", "{:.0f}% ({:,})".format(
            100 - w["ai_share"], w["human_n"])),
        ("Show-up rate — AI-booked", _pct(ai)),
        ("Show-up rate — recruiter-booked", _pct(hu)),
        ("Same, when booked within a day — AI / recruiter",
         "{} / {}".format(_pct(w.get("ai_fast_show")),
                          _pct(w.get("human_fast_show")))),
        ("Typical time to book — AI / recruiter", "{} / {}".format(
            _hrs(w["ai_median_hours"]), _hrs(w["human_median_hours"]))),
    ]
    if ai is None or hu is None:
        return _line("who", "\U0001F916", t, GREY, "Not enough data", "",
                     facts)
    short = "AI books {:.0f}% · show-ups {:.0f}% AI vs {:.0f}% " \
            "recruiters".format(w["ai_share"], ai, hu)
    real = w.get("p") is not None and w["p"] < 0.05
    action = None
    if real and ai > hu:
        gap_fast = ((w.get("ai_fast_show") or 0)
                    - (w.get("human_fast_show") or 0))
        why = ("It holds even at the same booking speed."
               if gap_fast >= 5 else
               "Part of it is the AI booking them sooner.")
        text = ("AI-booked applicants show up more. {} Fixing the AI's "
                "templates and replies lets it take more of the "
                "booking.".format(why))
        dot = YELLOW if w["ai_share"] < 70 else GREEN
        if w["ai_share"] < 70:
            action = ("Let the AI book more — its people show up "
                      "{:.0f}% vs {:.0f}%".format(ai, hu))
    elif real and hu > ai:
        dot = YELLOW
        text = "Recruiter-booked applicants show up more. Fix the AI's " \
               "replies before moving more booking to it."
    else:
        dot = GREEN
        text = "No real difference in who shows up."
    return _line("who", "\U0001F916", t, dot, short, text, facts,
                 action=action)


# Good / middle / bad colours for a number (Megan 2026-11-13: "color code
# the numbers of what is good (green) what is bad (red) - what is in the
# middle (orange)").
TONE = {"good": "#156E46", "mid": "#b06d00", "bad": "#A8322A"}


def _tone(v, good, bad, higher_is_better=True):
    """'good' / 'mid' / 'bad' for v against two cut-offs, or None."""
    if v is None:
        return None
    if higher_is_better:
        return "good" if v >= good else "bad" if v < bad else "mid"
    return "good" if v <= good else "bad" if v > bad else "mid"


# Time-to-book cut-offs (my first cut; same-day shows 57% vs 42% next day):
#   processed -> booked, average days   good <= 0.5   bad > 1
#   typical (median) hours              good <= 4     bad > 12
#   booked the same day %               good >= 70    bad < 50
#   booked a day or more later %        good <= 10    bad > 20
#   show-up rate %                      good >= 50    bad < 35
#   texts before the 1st round          good <= 3     bad > 6


def speed(st, ttb=None):
    d = (st or {}).get("days") or {}
    t = "Time to book"
    if not d.get("ok"):
        return _line("speed", "⏱️", t, GREY, "Not checked")
    p = d["push_to_book"]
    iv = d.get("interview_gap") or {k: {"share": None, "show": None}
                                     for k in (0, 1, 2)}
    show = lambda v: (_pct(v), _tone(v, 50, 35))
    facts = [
        ("Resume processed → booked, average",
         [("{:.1f} days".format(p["avg_days"]),
           _tone(p["avg_days"], 0.5, 1, False))]),
        ("Typical (median)", [(_hrs(p["median_h"]),
                               _tone(p["median_h"], 4, 12, False))]),
        # Megan 2026-11-15: counted by the day the 1st round is ON, from
        # the day the resume was processed.
        ("1st round the same day as processed",
         [(_pct(iv[0]["share"]), _tone(iv[0]["share"], 60, 40))]),
        ("1st round the next day", [(_pct(iv[1]["share"]), None)]),
        ("1st round 2+ days later",
         [(_pct(iv[2]["share"]), _tone(iv[2]["share"], 10, 20, False))]),
        ("Show-up rate \u2014 same day / next day / 2+ days",
         [show(iv[0]["show"]), (" / ", None), show(iv[1]["show"]),
          (" / ", None), show(iv[2]["show"])]),
        ("Number of texts sent before the 1st round was set",
         [("{:.1f} average".format(ttb["average"]),
           _tone(ttb["average"], 3, 6, False))] if ttb
         else "not checked"),
    ]
    late = iv[2]["share"] if iv[2]["share"] is not None else d["late_share"]
    dot = GREEN if late <= LATE_OK else YELLOW if late <= LATE_BAD else RED
    short = "{} same day · {} 2+ days out".format(
        _pct(iv[0]["share"]), _pct(iv[2]["share"]))
    if ttb:
        short += " · {:.1f} texts".format(ttb["average"])
    text = ("1st rounds held the same day the resume was processed show "
            "up {}; the next day {}; 2+ days later {}.".format(
                _pct(iv[0]["show"]), _pct(iv[1]["show"]),
                _pct(iv[2]["show"])))
    action = None if dot == GREEN else (
        "{:.0f}% of 1st rounds are 2+ days after the resume was processed, "
        "and they show up {}".format(late, _pct(iv[2]["show"])))
    return _line("speed", "⏱️", t, dot, short, text, facts,
                 action=action)


# Carrier blocks on the office's own number, as a share of texts sent.
DELIVERY_OK, DELIVERY_BAD = 3.0, 6.0


# What to do about each reason a text didn't arrive (Megan 2026-11-13:
# "Idk what held back by carrier is - can we give ways to fix this?").
# (what it means, what to do, who does it). No STOP line: not house practice.
# Megan 2026-11-15: "app stream controls the settings here for this phone
# number". The number's registration, sending limit and credits are set on
# ApplicantStream's side (Megan: "app stream not aptel for the phone
# number"), so ApplicantStream fixes those; the office only owns
# the wording of its texts.
# Megan 2026-11-15: say what the issue is, not what exactly to ask for -
# "reach out to app stream to see if there's anything we can do to
# decrease this number".
REACH_OUT = ("Reach out to ApplicantStream to see if there's anything that "
             "can be done to bring this number down.")
DELIVERY_FIX = {
    "Blocked by the phone carrier": (
        "The carrier (AT&T, T-Mobile, Verizon) refused the text, usually "
        "because it looks like spam or the number isn't fully registered.",
        REACH_OUT, "ApplicantStream"),
    "Held by the carrier, never delivered": (
        "The carrier slowed this number down and AppStream queued the text "
        "to try again. Almost none get through later.",
        REACH_OUT, "ApplicantStream"),
    "The account ran out of text credits": (
        "AppStream didn't send it because the account had no credits left.",
        REACH_OUT, "ApplicantStream"),
    "Applicant gave a fake number": (
        "The applicant typed in a made-up number.",
        "Nothing to fix on your side.", ""),
    "Not a real phone number": (
        "The number can't receive texts.",
        "Nothing to fix on your side.", ""),
}


def _fixes_html(fixes):
    if not fixes:
        return ""
    out = ["<p class='why'><b>What to do:</b></p><ul class='dfix'>"]
    for label, n, (means, todo, who) in fixes:
        out.append("<li><b>{}</b> <span class='s'>({:,})</span><br>{}<br>"
                   "<b>Fix:</b> {}{}</li>".format(
                       _e(label), n, _e(means), _e(todo),
                       "<br><span class='who'><b>Who:</b> {}</span>".format(
                           _e(who)) if who else ""))
    out.append("</ul>")
    return "".join(out)


def texts_arrived(dv):
    title = "Texts that didn't arrive"
    if not dv or not dv.get("ok"):
        return _line("delivery", "\U0001F4F5", title, GREY, "Not checked")
    facts = [("Texts sent", "{:,}".format(dv["sent"])),
             ("Didn't arrive", "{:,} ({:.0f}%)".format(dv["failed"],
                                                      dv["rate"]))]
    facts += [("  " + why, "{:,}".format(n)) for why, n in dv["reasons"]]
    for num, sent, rate in dv["numbers"]:
        facts.append(("From {}".format(num),
                      "{:.0f}% blocked of {:,}".format(rate, sent)))
    r = dv["ours_rate"]
    dot = GREEN if r <= DELIVERY_OK else YELLOW if r <= DELIVERY_BAD else RED
    short = "{:.0f}% never arrived \u00b7 {:.0f}% blocked by carriers".format(
        dv["rate"], r)
    text = ("When texts don't arrive, applicants never hear from you, and a "
            "number the carriers flag starts to look like a scam.")
    action = None if dot == GREEN else (
        "{:.0f}% of your texts never reach applicants".format(r))
    ln = _line("delivery", "\U0001F4F5", title, dot, short, text, facts,
               action=action)
    ln["fixes"] = [(why, n, DELIVERY_FIX[why]) for why, n in dv["reasons"]
                   if why in DELIVERY_FIX and DELIVERY_FIX[why][2]]
    return ln


# Coaching lines for the interview schedule (Megan 2026-11-13: "hey, you're
# not really giving the recruiters a lot of options, or maybe too much").
# My first cut at the numbers, to tune once a few offices are in:
FEW_SLOTS = 2          # under 2 morning or 2 afternoon times a day = few
EMPTY_FILL = 0.25      # under a quarter of seats booked = more than needed
FULL_FILL = 0.85       # over 85% booked = running out


def _share(x):
    return "{:.0f}%".format(100 * x)


def slot_line(sl):
    title = "Interview slots"
    if not sl:
        return _line("slots", "\U0001F4C5", title, GREY,
                     "Not pulled yet")
    am, pm = sl["morning"], sl["afternoon"]
    short = "1st rounds: {:.1f} morning · {:.1f} afternoon a day".format(am, pm)
    facts = [("Days with interviews", "{} a week".format(sl["days"])),
             ("Morning times a day (before noon)", "{:.1f}".format(am)),
             ("Afternoon times a day", "{:.1f}".format(pm)),
             ("Seats a day (people the slots can hold)",
              "{:.0f}".format(sl["seats"]))]
    if sl.get("fill") is not None:
        facts.append(("Booked a day, on average", "{:.1f} ({} of seats)".format(
            sl["booked"], _share(sl["fill"]))))
        short += " · {} booked".format(_share(sl["fill"]))
    for p in sl["per_day"]:
        facts.append((p["day"], "{} morning · {} afternoon".format(
            p["morning"], p["afternoon"])))
    facts.append(("2nd rounds", "Not pulled yet"))
    action, text, dot = None, "", GREEN
    few = [w for w, n in (("morning", am), ("afternoon", pm)) if n < FEW_SLOTS]
    if few:
        dot = YELLOW
        action = "Add more {} interview times so recruiters have options " \
                 "to offer".format(" and ".join(few))
        text = ("Recruiters and the AI can only offer what's open. With "
                "under {} {} times a day, an applicant who can't make those "
                "gets pushed to another day, and same-day bookings show up "
                "57% against 42% next day.".format(FEW_SLOTS,
                                                    " or ".join(few)))
    elif sl.get("fill") is not None and sl["fill"] < EMPTY_FILL:
        dot = YELLOW
        action = "Fewer interview times would fill the ones you keep"
        text = ("Only {} of seats get booked. Spreading applicants over "
                "many times leaves interviewers waiting on near-empty "
                "slots.".format(_share(sl["fill"])))
    elif sl.get("fill") is not None and sl["fill"] > FULL_FILL:
        dot = YELLOW
        action = "Add interview times: the ones you have are nearly full"
        text = ("{} of seats are booked, so applicants are being pushed to "
                "later days.".format(_share(sl["fill"])))
    return _line("slots", "\U0001F4C5", title, dot, short, text, facts,
                 action=action)


def best_times(st):
    t = (st or {}).get("times") or {}
    title = "Best times"
    if not t.get("ok"):
        return _line("times", "\U0001F552", title, GREY, "Not checked")
    facts = [("Most bookings happen at", ", ".join(
                "{} ({:.0f}%)".format(h, s) for h, _n, s in t["top_hours"])),
             ("Busiest booking day", t["top_day"][0])]
    if t.get("best_slot"):
        facts.append(("Interview time with the best show-up",
                      "{} ({:.0f}%)".format(*t["best_slot"][:2])))
    if t.get("worst_slot"):
        facts.append(("Interview time with the worst show-up",
                      "{} ({:.0f}%)".format(*t["worst_slot"][:2])))
    short = "Most booked at {}".format(t["top_hours"][0][0])
    if t.get("best_slot"):
        short += " · best show-up {} interviews".format(
            t["best_slot"][0])
    return _line("times", "\U0001F552", title, GREEN, short, "", facts)


CHANCE = "too few people to be sure"


def _driver_html(d):
    """One factor: best vs worst on the row; tap for every group."""
    # Megan 2026-11-15: "what's the % of?" - say it: showed up, out of
    # 1st rounds booked (not applications).
    rows = ("<tr><th></th><th>Showed up</th><th>1st rounds booked</th></tr>"
            + "".join("<tr><td>{}</td><td>{:.0f}%</td><td>{:,}</td></tr>"
                      .format(_e(v), r, n) for v, r, n in d["groups"]))
    return ("<details class='drv'><summary><span class='t'>{}</span>"
            "<span class='s'>best {} {:.0f}% vs worst {} {:.0f}%{}</span>"
            "</summary><div class='body'><table class='list'>{}</table>"
            "</div></details>".format(
                _e(d["label"]), _e(d["best"][0]), d["best"][1],
                _e(d["worst"][0]), d["worst"][1],
                "" if d["real"] else " ({})".format(CHANCE), rows))


# Megan 2026-11-15: open Bookings and show-ups with a plain summary - "based
# on the last 6 weeks you should aim to book ... your best show rate is from
# ...". Only gaps big enough to trust go in: a summary that sells noise is
# worse than a short one.
FULL_DAY = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday",
            "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday",
            "Sun": "Sunday"}
ADVICE = {
    "processed": lambda b: {
        "same day": "book the 1st round for the same day the resume is "
                    "processed",
        "next day": "book the 1st round for the day after the resume is "
                    "processed"}.get(b),
    "part": lambda b: "book {} time slots".format(b),
    "weekday": lambda b: "{} interviews show up best".format(
        FULL_DAY.get(b, b)),
    "board": lambda b: "candidates from {} show up best".format(b),
    "booker": lambda b: "people booked by {} show up best".format(b),
}


def _weeks_in(st):
    span = (st or {}).get("span")
    if not span:
        return None
    return max(1, round(((span[1] - span[0]).days + 1) / 7.0))


def advice(st, weeks=None):
    """One plain summary sentence for Bookings and show-ups, or None."""
    dr = [d for d in (st or {}).get("drivers") or [] if d["real"]]
    bits = []
    for d in dr:
        fn = ADVICE.get(d["key"])
        say = fn(d["best"][0]) if fn else None
        if say:
            bits.append("{} ({:.0f}% show up vs {:.0f}% {})".format(
                say, d["best"][1], d["worst"][1],
                "for " + FULL_DAY[d["worst"][0]] if d["worst"][0] in FULL_DAY
                else "at " + d["worst"][0]))
    best = ((st or {}).get("times") or {}).get("best_slot")
    if best:
        bits.append("your best show-up time is {} ({:.0f}%)".format(
            best[0], best[1]))
    if not bits:
        return None
    head = "Based on the last {} weeks".format(weeks) if weeks else \
        "Based on these weeks"
    if len(bits) == 1:
        body = bits[0]
    else:
        body = "; ".join(bits[:-1]) + "; and " + bits[-1]
    return "{}: {}.".format(head, body[0].lower() + body[1:])


def drivers(st):
    dr = list((st or {}).get("drivers") or [])
    title = "What moves show-ups most"
    if not dr:
        return _line("drivers", "\U0001F4C8", title, GREY, "Not enough data")
    # Megan 2026-11-15: each row is best vs worst; a tap shows every group.
    # "Could be chance" read as jargon: say what it means.
    text = ("Of the 1st rounds booked in these weeks, the share that showed "
            "up, for the best and worst group of each. Tap one to see every "
            "group. \u201c{}\u201d means the gap is small for how "
            "few people are in it, so it may just be luck.".format(CHANCE))
    top = [d for d in dr if d["real"]][:1]
    if not top:
        ln = _line("drivers", "\U0001F4C8", title, GREEN,
                   "Nothing stands out yet", text, [])
    else:
        d = top[0]
        short = "{}: {} {:.0f}% vs {} {:.0f}%".format(
            d["label"], d["best"][0], d["best"][1], d["worst"][0],
            d["worst"][1])
        ln = _line("drivers", "\U0001F4C8", title, GREEN, short, text, [])
    ln["extra_html"] = "".join(_driver_html(d) for d in dr[:6])
    return ln


def recruiters(rows):
    title = "Recruiters"
    if rows is None:
        return _line("recruiters", "\U0001F465", title, GREY, "Not checked")
    if not rows:
        return _line("recruiters", "\U0001F465", title, GREY,
                     "Nobody sent enough texts to grade")
    low = [r for r in rows if r["grade"] in ("D", "F")]
    dot = RED if low else YELLOW if any(r["grade"] == "C" for r in rows) \
        else GREEN
    short = "{} graded · {} below a C".format(len(rows), len(low))
    line = _line("recruiters", "\U0001F465", title, dot, short)
    line["people"] = rows
    if low:
        line["action"] = "Sit down with {}".format(
            ", ".join(r["name"] for r in low[:2]))
    return line


def fold(items):
    """Three or more of the same kind from the same source -> one item.

    Thirty "no opt-out" templates are one habit with one fix; listed
    separately they bury the one wrong address."""
    groups, order = {}, []
    for i in items:
        k = (i["source"], i["kind"])
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(i)
    out = []
    for k in order:
        g = groups[k]
        if len(g) < FOLD_AT or k[1] in ("TYPO", "HOUSE RULE"):
            out.extend(g)
            continue
        first = g[0]
        w = first["where"]
        steps = [s.replace("“{}”".format(w), "each one listed")
                 .replace(w, "each one listed") for s in first["steps"]]
        out.append(dict(first, where="{} of them".format(len(g)),
                        found="\n".join("• " + x["where"] for x in g),
                        steps=steps, count=len(g)))
    return out


def _checked_line(key, icon, title, items, skipped, red_kinds):
    items = fold(items)
    for i in items:
        i["action"] = action_of(i)
    if skipped and not items:
        return _line(key, icon, title, GREY, "Not checked",
                     "Missing: " + "; ".join(skipped))
    if not items:
        return _line(key, icon, title, GREEN, "All good")
    red = any(i["kind"] in red_kinds for i in items)
    n = sum(i.get("count", 1) for i in items)
    return _line(key, icon, title, RED if red else YELLOW,
                 "{} to fix".format(n),
                 ("Not checked: " + "; ".join(skipped)) if skipped else "",
                 items=items)


def _rank(item):
    k = item["kind"]
    if k in WRONG_INFO:
        return 0
    if k in AI_BROKEN or k == "PLACEHOLDER":
        return 1
    if k.startswith("PREF"):
        return 3
    if k in ("TYPO", "HOUSE RULE"):
        return 5
    return 4


def todo(lines, n=TOP_N):
    """The top n, as {'text', 'item' or None, 'line'}.

    Wrong information, then the AI, then the booking-speed habit, then the
    AI's buffers, then wording, then individual coaching."""
    cands = []
    for ln in lines:
        for i in ln["items"]:
            cands.append((_rank(i), {"text": i["action"], "item": i,
                                     "line": ln["key"]}))
        if ln.get("action"):
            r = {"delivery": 1.5, "speed": 2, "who": 2.5,
                 "slots": 2.7}.get(ln["key"], 6)
            cands.append((r, {"text": ln["action"], "item": None,
                              "line": ln["key"]}))
    cands.sort(key=lambda c: c[0])
    return [c[1] for c in cands[:n]]


def build(office, stats=None, ttb=None, recruiter_rows=None,
          info_items=(), info_skipped=(), word_items=(), word_skipped=(),
          ai_items=(), ai_skipped=(), sources=(), grading=(), delivery=None,
          setup=None, slots=None, vitals=None, changes=None, now=None):
    """The whole card as data. `sources` is [(what, date or None, where)]."""
    now = now or dt.datetime.now()
    fresh = []
    for what, when, where in sources:
        age = (now.date() - when).days if when else None
        fresh.append({"what": what, "when": when, "where": where,
                      "age": age,
                      "stale": age is None or age > STALE_DAYS})
    lines = [
        _checked_line("info", "\U0001F4CD", "Address, Zoom, phone",
                      list(info_items), list(info_skipped), WRONG_INFO),
        _checked_line("ai", "\U0001F4AC", "AI texts + escalations",
                      list(ai_items), list(ai_skipped), AI_BROKEN),
        _checked_line("words", "✍️", "Grammar + wording",
                      list(word_items), list(word_skipped), set()),
        texts_arrived(delivery),
        who_books(stats),
        speed(stats, ttb),
        best_times(stats),
        slot_line(slots),
        drivers(stats),
        recruiters(recruiter_rows),
    ]
    return {"office": office, "made": now, "lines": lines,
            "span": (stats or {}).get("span"),
            "booked": (stats or {}).get("n"),
            "todo": todo(lines), "sources": fresh,
            "grading": list(grading), "setup": setup, "vitals": vitals,
            "changes": changes,
            "advice": advice(stats, _weeks_in(stats)),
            "stale": [f for f in fresh if f["stale"]]}


# --------------------------------------------------------------- draw

CSS = """
:root{--ink:#1d1d1f;--muted:#6b6b6b;--line:#ece5d3;--card:#fff;
      --bg:#FBF8F1;--gold:#C9A227;--soft:#f6f2e8}
*{box-sizing:border-box}
body{font-family:Georgia,'Times New Roman',serif;color:var(--ink);
     background:var(--bg);max-width:40em;margin:1.6em auto;padding:0 16px;
     line-height:1.45}
h1{font-size:1.45em;margin:0}
.sub{color:var(--muted);font-size:.92em;margin:.15em 0 1.1em}
.stale{color:#A8322A;font-size:.9em;margin:0 0 1em}
h2.k{font-size:.8em;letter-spacing:.08em;text-transform:uppercase;
     color:var(--muted);margin:1.6em 0 .5em}
details{background:var(--card);border:1px solid var(--line);
        border-radius:10px;margin:.45em 0}
details>summary{list-style:none;cursor:pointer;padding:.7em .9em;
        display:flex;gap:.6em;align-items:center}
details>summary::-webkit-details-marker{display:none}
details>summary:after{content:'\\203A';margin-left:auto;color:var(--muted);
        font-size:1.3em;transition:transform .15s}
details[open]>summary:after{transform:rotate(90deg)}
.body{padding:0 .9em .8em 2.4em;font-size:.95em}
.top details{border-color:var(--gold);border-width:2px}
.num{flex:none;width:1.6em;height:1.6em;border-radius:50%;
     background:var(--ink);color:#fff;font-size:.85em;display:flex;
     align-items:center;justify-content:center}
.dot{flex:none;width:.8em;height:.8em;border-radius:50%}
.t{font-weight:bold}
.s{color:var(--muted);font-size:.92em}
.row{display:flex;flex-direction:column}
table{border-collapse:collapse;width:100%;margin:.2em 0 .5em}
td{padding:.3em .3em;border-top:1px solid var(--line);vertical-align:top}
td:last-child{text-align:right;white-space:nowrap}
.found{background:var(--soft);padding:.35em .55em;border-radius:6px;
       font-family:Menlo,Consolas,monospace;font-size:.82em;
       white-space:pre-wrap;word-break:break-word;margin:.3em 0}
.why{color:#444;margin:.3em 0}
ol{margin:.3em 0;padding-left:1.3em}
ul.acts{list-style:none;margin:.2em 0;padding:0}
ul.acts details{border-radius:8px;margin:.3em 0}
ul.acts summary{padding:.45em .7em;font-size:.95em}
ul.acts .body{padding-left:.9em}
.grade{flex:none;width:1.8em;font-weight:bold;text-align:center}
.g-A,.g-B{color:#156E46}.g-C{color:#8a6d00}.g-D,.g-F{color:#A8322A}
.sc{padding:.2em .9em .9em}
.names .sc .fix{background:#fdecea;border-color:#e3a6a0}
.truth{background:#fff;border:2px solid var(--ink);border-radius:10px;
       padding:.7em .9em;margin:0 0 .6em}
.truth td:last-child{text-align:left;white-space:normal;
       word-break:break-word}
.truth td:first-child{width:7.5em;color:var(--muted)}
.names{display:grid;grid-template-columns:1fr 1fr;gap:.35em 1em;
       background:#fff;border:1px solid var(--line);border-radius:10px;
       padding:.7em .9em}
.names details.rc{margin:0;border:0;background:none}
.names details.rc>summary{color:#1a56c4;font-weight:bold;cursor:pointer;
       list-style:none;display:flex;gap:.4em;align-items:baseline;
       padding:.1em 0}
.names details.rc>summary::-webkit-details-marker{display:none}
.names details.rc>summary::after{content:none}
.names details.rc>summary:hover{text-decoration:underline}
.names details.rc[open]{grid-column:1/-1;border:2px solid #1a56c4;
       border-radius:10px;background:#fff;padding:.3em .5em}
.names .grade{width:1.3em}
ol.replies li{margin:.45em 0}
.owner{margin:.4em 0;padding:.35em .6em;background:#eef3fb;
       border-radius:6px}
.vitals details.vital>summary{display:grid;
     grid-template-columns:minmax(0,1fr) auto 6.5em;gap:.7em;
     align-items:center}
.vitals details.vital>summary:after{display:none}
details.drv{margin:.3em 0}
details.drv>summary{flex-wrap:wrap;gap:.2em .6em}
.advice{background:#f1faf4;border:1px solid #9fd3b5;border-radius:10px;padding:.7em .9em;margin:.4em 0 .6em}
label.go{color:#1a56c4;font-weight:bold;cursor:pointer;text-decoration:underline}
.vn{font-weight:bold}
.vv{text-align:right;display:flex;flex-direction:column;line-height:1.2}
.vv b{font-size:1.2em}
.vv span{font-size:.82em}
.spark{display:block}
.vitals .body{padding:0 .9em .8em}
.weeks{display:grid;gap:.3em;border-top:1px solid var(--line);
     padding-top:.6em}
.wk{text-align:center;padding:.3em .1em;border-radius:6px}
.wk.now{background:var(--soft)}
.wk .wl{display:block;font-size:.75em;color:var(--muted)}
.wk b{font-size:1.05em}
@media (max-width:420px){.vitals details.vital>summary{
     grid-template-columns:minmax(0,1fr) 6.5em}.spark{grid-column:1/-1;
     grid-row:2;width:100%}}
.up{color:#156E46;font-weight:bold}.down{color:#A8322A;font-weight:bold}
.steady{color:#b06d00;font-weight:bold}
ul.dfix{padding-left:1.1em;margin:.2em 0}
ul.dfix li{margin:.5em 0}
.who{color:#1a56c4}
.foot{color:var(--muted);font-size:.85em;margin-top:2em}
"""


def _e(t):
    return html.escape(str(t if t is not None else ""))


TREND_WEEKS = 6


def _vfmt(v, pct):
    if v is None:
        return "<span class='s'>\u2014</span>"
    return "{:.0f}%".format(v) if pct else "{:.0f}".format(v)


# Megan 2026-11-13: colour along the line by how good each week was — the
# row's lowest weeks red, the middle orange, its best weeks green. Every
# vital here is higher-is-better. The arrow + words still say the direction.
LOW, MID, HIGH = "#c0392b", "#e08a00", "#1f8a4c"
_SPARK_N = [0]


def _mix(a, b, t):
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#{:02x}{:02x}{:02x}".format(*[round(x + (y - x) * t)
                                          for x, y in zip(a, b)])


def _heat(t):
    """0 = the row's worst week (red) .. 1 = its best (green)."""
    t = max(0.0, min(1.0, t))
    return _mix(LOW, MID, t / 0.5) if t < 0.5 else _mix(MID, HIGH,
                                                          (t - 0.5) / 0.5)


def _spark(points, pct, way="steady"):
    """Inline SVG line, red at the row's low weeks, orange in the middle,
    green at its best (a vertical gradient on the stroke). The latest week
    is the big dot. Each point carries a native hover tooltip."""
    W, H, P = 132, 34, 5
    vals = [v for _l, v in points if v is not None]
    if len(vals) < 2:
        return "<span class='s'>not enough weeks</span>"
    lo, hi = min(vals), max(vals)
    flat = hi == lo
    span = (hi - lo) or 1
    n = len(points)
    xy = []
    for i, (lab, v) in enumerate(points):
        x = P + i * (W - 2 * P) / (n - 1)
        if v is None:
            y = None
        elif flat:
            y = H / 2
        else:
            y = H - P - (v - lo) / span * (H - 2 * P)
        xy.append((x, y, lab, v))
    segs, cur = [], []
    for x, y, _l, _v in xy:
        if y is None:
            if len(cur) > 1:
                segs.append(cur)
            cur = []
        else:
            cur.append("{:.1f},{:.1f}".format(x, y))
    if len(cur) > 1:
        segs.append(cur)
    _SPARK_N[0] += 1
    gid = "g{}".format(_SPARK_N[0])
    # A week-on-week flat line has no best or worst: one orange.
    stroke = MID if flat else "url(#{})".format(gid)
    out = ["<svg class='spark' viewBox='0 0 {0} {1}' width='{0}' height='{1}' "
           "role='img' aria-label='trend'>".format(W, H)]
    if not flat:
        out.append("<defs><linearGradient id='{}' gradientUnits='userSpaceOnUse'"
                   " x1='0' y1='{}' x2='0' y2='{}'><stop offset='0' "
                   "stop-color='{}'/><stop offset='.5' stop-color='{}'/>"
                   "<stop offset='1' stop-color='{}'/></linearGradient></defs>"
                   .format(gid, H - P, P, LOW, MID, HIGH))
    for seg in segs:
        out.append("<polyline points='{}' fill='none' stroke='{}' "
                   "stroke-width='2.5' stroke-linejoin='round' "
                   "stroke-linecap='round'/>".format(" ".join(seg), stroke))
    last = max(i for i, p in enumerate(xy) if p[1] is not None)
    for i, (x, y, lab, v) in enumerate(xy):
        if y is None:
            continue
        fill = MID if flat else _heat((v - lo) / span)
        out.append("<circle cx='{:.1f}' cy='{:.1f}' r='{}' fill='{}' "
                   "stroke='#fff' stroke-width='1.5'><title>Week of {}: {}"
                   "</title></circle>".format(x, y, 4 if i == last else 2.8,
                                               fill, lab,
                                               html.unescape(_vfmt(v, pct))))
    out.append("</svg>")
    return "".join(out)


def trend_html(vitals):
    """Page 0: one tile per key vital — latest week, change, and a line of
    the last weeks for a glance at progression. Click a tile for the
    week-by-week numbers. `vitals` is (weeks, stamp) from vitals.read."""
    from automations.applicant_stream_card import vitals as V
    weeks, stamp = vitals or ([], None)
    if not weeks:
        return ("<h2 class='k'>Key vitals</h2><p class='s'>Not pulled yet. "
                "They come from AppStream's Retention Details report, week by week."
                "</p>")
    weeks = weeks[-TREND_WEEKS:]
    labs = ["{}/{}".format(d.month, d.day) for d, _v in weeks]
    out = ["<h2 class='k'>Key vitals \u00b7 last {} weeks</h2>".format(
        len(weeks)), "<div class='vitals'>"]
    for key, label, pct in V.VITALS:
        latest, delta = V.trend(weeks, key)
        if latest is None:
            way, chg = "steady", "<span class='s'>no data</span>"
        elif delta is None or abs(delta) < (1 if pct else 0.5):
            way = "steady"
            chg = "<span class='steady'>\u2192 steady</span>"
        else:
            way = "up" if delta > 0 else "down"
            chg = "<span class='{}'>{} {}{}</span>".format(
                way, "\u25b2" if delta > 0 else "\u25bc",
                "+" if delta > 0 else "\u2212",
                "{:.0f}{}".format(abs(delta), " pts" if pct else ""))
        pts = [(lab, v.get(key)) for lab, (_d, v) in zip(labs, weeks)]
        # Opened: the weeks left to right, oldest first, each number in the
        # colour of its dot (red = this vital's weakest week, green = best).
        have = [v for _l, v in pts if v is not None]
        lo, hi = (min(have), max(have)) if have else (0, 0)

        def tone(v):
            if v is None:
                return "#6b6b6b"
            return MID if hi == lo else _heat((v - lo) / (hi - lo))
        rows = "".join(
            "<div class='wk{}'><span class='wl'>{}</span>"
            "<b style='color:{}'>{}</b></div>".format(
                " now" if i == len(pts) - 1 else "", lab, tone(v),
                _vfmt(v, pct))
            for i, (lab, v) in enumerate(pts))
        out.append(
            "<details class='vital'><summary><span class='vn'>{}</span>"
            "{}<span class='vv'><b>{}</b>{}</span></summary>"
            "<div class='body'><div class='weeks' style='grid-template-columns:"
            "repeat({}, minmax(0,1fr))'>{}</div></div></details>".format(
                _e(label), _spark(pts, pct, way), _vfmt(latest, pct), chg,
                len(pts), rows))
    out.append("</div><p class='s'>Tap a vital for its week-by-week numbers. "
               "Weeks run Sunday to Saturday, dated by their Sunday. The "
               "change compares the latest week with the 3 before it.</p>")
    return "".join(out)


# Which tab holds each kind of fix (Megan 2026-11-15: "wouldn't these be on
# the templates section"). A <label> for the tab's radio switches tabs with
# no script and no #link.
TAB_OF = {"Templates": ("pg3", "Templates"), "AI Settings": ("pg2", "AI Settings"),
          "AI replies": ("pg2", "AI Settings")}


# Which tab each scorecard line sits on (Megan 2026-11-15).
HUMAN_KEYS = ("who",)                       # + recruiter typing, recruiters
VITALS_KEYS = ("speed", "times", "drivers")
AI_KEYS = ("slots",)
TEMPLATE_KEYS = ("delivery",)


def _line_html(ln):
    """One scorecard line as a tap-to-open row."""
    out = ["<details><summary><span class='dot' style='background:{}'>"
           "</span><span class='row'><span class='t'>{} {}</span>"
           "<span class='s'>{}</span></span></summary><div class='body'>"
           .format(DOT[ln["dot"]], ln["icon"], _e(ln["title"]),
                   _e(ln["short"]))]
    if ln["text"]:
        out.append("<p class='why'>{}</p>".format(_e(ln["text"])))
    out.append(_facts(ln["facts"]))
    out.append(ln.get("extra_html") or "")
    out.append(_fixes_html(ln.get("fixes")))
    if ln["items"]:
        out.append("<ul class='acts'>")
        for i in sorted(ln["items"], key=_rank):
            out.append("<li><details><summary>{}</summary><div class='body'>"
                       "{}</div></details></li>".format(
                           _e(i["action"]), _fix_body(i) + _tab_link(i)))
        out.append("</ul>")
    out.append("</div></details>")
    return "".join(out)


def _lines_html(card, keys, title, lead=None):
    lines = {ln["key"]: ln for ln in card["lines"]}
    got = [lines[k] for k in keys if k in lines]
    if not got:
        return ""
    return "<h2 class='k'>{}</h2>{}{}".format(
        _e(title), "<p class='advice'>{}</p>".format(_e(lead)) if lead
        else "", "".join(_line_html(ln) for ln in got))


def _todo_html(card):
    """The 'Fix these first' tab (Megan 2026-11-15: "we should have like a
    fix these first tab")."""
    if not card["todo"]:
        return ("<h2 class='k'>Fix these first</h2><p class='s'>Nothing "
                "urgent this week.</p>")
    out = ["<h2 class='k'>Fix these first</h2><p class='s'>The few things "
           "that will help most this week. Tap one to see why and how.</p>"
           "<div class='top'>"]
    lines = {ln["key"]: ln for ln in card["lines"]}
    for n, t in enumerate(card["todo"], start=1):
        out.append("<details><summary><span class='num'>{}</span>"
                   "<span class='t'>{}</span></summary><div class='body'>"
                   .format(n, _e(t["text"])))
        if t["item"]:
            out.append(_fix_body(t["item"]) + _tab_link(t["item"]))
        else:
            ln = lines.get(t["line"]) or {}
            out.append("<p class='why'>{}</p>{}{}".format(
                _e(ln.get("text", "")), _facts(ln.get("facts")),
                _fixes_html(ln.get("fixes"))))
        out.append("</div></details>")
    out.append("</div>")
    return "".join(out)


def _tab_link(i):
    tab = TAB_OF.get(i.get("source"))
    if not tab:
        return ""
    return ("<p><label class='go' for='{}'>See it on the {} tab \u2192</label>"
            "</p>".format(*tab))


def _fix_body(i):
    out = []
    if i.get("found"):
        out.append("<div class='found'>{}</div>".format(_e(i["found"])))
    if i.get("why"):
        out.append("<p class='why'><b>Why:</b> {}</p>".format(_e(i["why"])))
    if i.get("owner"):
        out.append("<p class='owner'><b>Who fixes it:</b> {}</p>".format(
            _e(i["owner"])))
    if i.get("replies"):
        out.append("<b>Not set up yet:</b><ol class='replies'>{}</ol>".format(
            "".join("<li value='{}'><b>{}</b>{}</li>".format(
                n, _e(name), SP.options_html(F.reply_versions(name, msg),
                                             F.reply_link(name)))
                for n, name, msg in i["replies"])))
    rec = F.recommend(i)
    if rec:
        out.append("<p class='why'><b>We'd recommend:</b> {}</p>".format(
            _e(rec)))
    link = F.howto(i)
    if link:
        out.append("<p><a class='opts-link' href='{}' target='_blank' "
                   "rel='noopener'>{} \u2197</a></p>".format(
                       _e(link[1]), _e(link[0])))
    return "".join(out)


def _facts(facts):
    if not facts:
        return ""
    def cell(v):
        # A value can be [(text, tone)] parts, each coloured by its tone.
        if isinstance(v, list):
            return "".join(
                "<b style='color:{}'>{}</b>".format(TONE[t], _e(x)) if t
                else _e(x) for x, t in v)
        return _e(v)
    return "<table>{}</table>".format("".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(_e(k), cell(v))
        for k, v in facts))


def _scope_css(css, scope):
    """Prefix every selector of a stylesheet with `scope`, so a recruiter's
    full scorecard can sit inside this page without restyling it."""
    css = re.sub(r"@media[^{]+\{([^{}]*\{[^{}]*\})*\s*\}", "", css)
    out = []
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        sels = []
        for s in sel.split(","):
            s = s.strip()
            if not s:
                continue
            sels.append(scope if s == "body" else "{} {}".format(scope, s))
        out.append("{}{{{}}}".format(",".join(sels), body))
    return "\n".join(out)


def render(card, scorecard_css=""):
    L = []
    add = L.append
    span = card.get("span")
    sub = "Office {}".format(_e(card["office"]))
    if span:
        # No %-m: it does not exist on Windows.
        sub += " · {}/{} – {}/{}".format(
            span[0].month, span[0].day, span[1].month, span[1].day)
    add("<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Applicant Stream Card {}</title><style>{}{}</style></head>"
        "<body>".format(_e(card["office"]), CSS + SP.CSS + CH.CSS,
                        _scope_css(scorecard_css, ".sc")))
    add("<h1>Applicant Stream Grade Card</h1>")
    add("<div class='sub'>{}</div>".format(sub))
    if card.get("stale"):
        add("<div class='stale'>⚠ Old data: {} — re-pull before "
            "sending.</div>".format(_e(", ".join(
                f["what"].split(" (")[0] for f in card["stale"]))))
    # Page 2 (Megan 2026-11-13): what AppStream is set to. Radio tabs, so the
    # switch works with no script and no #links (dead in the app pane).
    # Trend first (Megan 2026-11-13: "a 'trend' section as the 1st page").
    # Megan 2026-11-15: AppStream setup split into AI Settings + Templates,
    # each tab showing its own flag count.
    setup = card.get("setup")

    def _tab(n):
        return " <span class='fl'>\u2691 {}</span>".format(n) if n else ""
    add("<input type='radio' name='pg' id='pg0' checked>"
        "<input type='radio' name='pg' id='pg1'>"
        "<input type='radio' name='pg' id='pg2'>"
        "<input type='radio' name='pg' id='pg3'>"
        "<input type='radio' name='pg' id='pg4'>"
        "<div class='tabs'><label for='pg0'>Vitals</label>"
        "<label for='pg4'>Fix these first{}</label>"
        "<label for='pg1'>Human Grade Card</label>"
        "<label for='pg2'>AI Settings{}{}</label>"
        "<label for='pg3'>Templates{}</label></div>"
        "<div class='page0'>{}</div>"
        "<div class='page4'>{}</div>"
        "<div class='page1'>".format(
            " <span class='fl'>{}</span>".format(len(card["todo"]))
            if card["todo"] else "",
            _tab(SP.flag_total(setup, SP.AI_PARTS)),
            " <span class='fl'>not set up</span>" if SP.no_ai(setup)
            else "",
            _tab(SP.flag_total(setup, SP.TEMPLATE_PARTS)),
            trend_html(card.get("vitals"))
            + _lines_html(card, VITALS_KEYS, "Bookings and show-ups",
                          card.get("advice"))
            + CH.html(card.get("changes"), card.get("vitals")),
            _todo_html(card)))


    # Megan 2026-11-15: the Human Grade Card grades PEOPLE. Template and AI
    # setup items live on their own tabs (each flag is already shown there,
    # next to the thing it's about); booking timing goes on Vitals.
    lines = {ln["key"]: ln for ln in card["lines"]}
    human = [lines[k] for k in HUMAN_KEYS if k in lines]
    words = lines.get("words")
    if words:
        mine = [i for i in words["items"]
                if i.get("source") == "Recruiter texts"]
        human.append(_checked_line("words", "\u270d\ufe0f",
                                   "Recruiter typing + wording", mine, [],
                                   set()))
    add("<h2 class='k'>Your scorecard</h2>")
    for ln in human:
        add(_line_html(ln))

    rc = next((ln for ln in card["lines"] if ln["key"] == "recruiters"), None)
    if rc:
        add("<h2 class='k' id='rcl'>Recruiters — tap a name</h2>")
        people = rc.get("people") or []
        if not people:
            add("<p class='s'>{}</p>".format(_e(rc["short"])))
        # Megan 2026-11-12: "names in blue, super simple bolded list ...
        # 2 columns ... with just their overall score", sorted A to D.
        # Each name is a <details>: click opens their full scorecard right
        # there, across both columns. No links or script, so it works in
        # any viewer (the old #anchor version did nothing in the app pane).
        if people:
            order = "ABCDF"
            people = sorted(people, key=lambda r: order.find(
                r["grade"]) if r["grade"] in order else len(order))
            add("<div class='names'>")
            for r in people:
                add("<details class='rc'><summary><span class='grade g-{0}'>"
                    "{0}</span>{1}</summary><div class='sc'>{2}</div>"
                    "</details>".format(
                        _e(r["grade"]), _e(r["name"]),
                        r.get("body") or "<p class='s'>Booked {} \u00b7 "
                        "showed {}</p>".format(_e(r["booked"]),
                                               _e(r["retention"]))))
            add("</div>")

    if card.get("sources"):
        add("<details class='foot'><summary>Where the numbers come from"
            "</summary><div class='body'><table>")
        for f in card["sources"]:
            add("<tr><td>{}</td><td>{}</td></tr>".format(
                _e(f["what"]),
                "{}/{}/{}".format(f["when"].month, f["when"].day,
                                  f["when"].year)
                if f["when"] else "date unknown"))
        add("</table><p class='s'>Read-only. Grey means not checked, never "
            "passed.</p></div></details>")
    add("</div><div class='page2'>")
    add(_lines_html(card, AI_KEYS, "At a glance"))
    add(SP.render_ai(setup))
    add("</div><div class='page3'>")
    if card.get("grading"):
        # What the template checks grade against (moved off the Human
        # Grade Card, Megan 2026-11-15).
        add("<div class='truth'><b>Make sure these are correct.</b> This is "
            "what we check your templates against.<table>")
        for row in card["grading"]:
            label, value = row[0], row[1]
            add("<tr><td>{}</td><td>{}</td></tr>".format(
                _e(label), _e(value) if value else "<i>not on file</i>"))
        add("</table></div>")
    add(_lines_html(card, TEMPLATE_KEYS, "At a glance"))
    add(SP.render_templates(setup))
    add("</div>{}</body></html>".format(SP.COPY_JS))
    return "\n".join(L)
