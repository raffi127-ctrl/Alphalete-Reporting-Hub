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

GREEN, YELLOW, RED, GREY = "green", "yellow", "red", "grey"
DOT = {GREEN: "#22A35A", YELLOW: "#E8A317", RED: "#D93A3A", GREY: "#9AA0A6"}

# Findings that put wrong information in front of an applicant.
WRONG_INFO = {"WRONG ROOM", "WRONG MEETING ID", "WRONG ADDRESS",
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


def speed(st, ttb=None):
    d = (st or {}).get("days") or {}
    t = "Time to book"
    if not d.get("ok"):
        return _line("speed", "⏱️", t, GREY, "Not checked")
    p = d["push_to_book"]
    facts = [
        ("Resume processed → booked, average",
         "{:.1f} days".format(p["avg_days"])),
        ("Typical (median)", _hrs(p["median_h"])),
        ("Booked the same day", _pct(d["same_day_share"])),
        ("Booked a day or more later", _pct(d["late_share"])),
        ("Show-up rate — within a day / later", "{} / {}".format(
            _pct(d["under_show"]), _pct(d["late_show"]))),
        ("Texts sent before the 1st round was set",
         "{:.1f} average".format(ttb["average"]) if ttb
         else "not checked"),
    ]
    late = d["late_share"]
    dot = GREEN if late <= LATE_OK else YELLOW if late <= LATE_BAD else RED
    short = "{:.1f} days average · {:.0f}% wait a day+".format(
        p["avg_days"], late)
    if ttb:
        short += " · {:.1f} texts".format(ttb["average"])
    text = ("People booked a day or more after processing show up {} vs "
            "{}. Clear the call list the same day.".format(
                _pct(d["late_show"]), _pct(d["under_show"])))
    action = None if dot == GREEN else (
        "Book everyone within 24 hours — {:.0f}% wait longer and show "
        "up {}".format(late, _pct(d["late_show"])))
    return _line("speed", "⏱️", t, dot, short, text, facts,
                 action=action)


# Carrier blocks on the office's own number, as a share of texts sent.
DELIVERY_OK, DELIVERY_BAD = 3.0, 6.0


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
    text = ("Carriers block texts from a number that is flagged as spam or "
            "not fully registered. Applicants then see the office as a scam.")
    action = None if dot == GREEN else (
        "{:.0f}% of your texts are blocked by carriers \u2014 check the "
        "number's registration (Aptel team)".format(r))
    return _line("delivery", "\U0001F4F5", title, dot, short, text, facts,
                 action=action)


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


def drivers(st):
    dr = list((st or {}).get("drivers") or [])
    title = "What moves show-ups most"
    if not dr:
        return _line("drivers", "\U0001F4C8", title, GREY, "Not enough data")
    facts = [(d["label"], "{} {:.0f}% vs {} {:.0f}%{}".format(
                d["best"][0], d["best"][1], d["worst"][0], d["worst"][1],
                "" if d["real"] else " (could be chance)"))
             for d in dr[:5]]
    top = [d for d in dr if d["real"]][:1]
    if not top:
        return _line("drivers", "\U0001F4C8", title, GREEN,
                     "Nothing stands out yet", "", facts)
    d = top[0]
    short = "{}: {} {:.0f}% vs {} {:.0f}%".format(
        d["label"], d["best"][0], d["best"][1], d["worst"][0], d["worst"][1])
    return _line("drivers", "\U0001F4C8", title, GREEN, short, "", facts)


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
          setup=None, slots=None, vitals=None, now=None):
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
.vn{font-weight:bold}
.vv{text-align:right;display:flex;flex-direction:column;line-height:1.2}
.vv b{font-size:1.2em}
.vv span{font-size:.82em}
.spark{display:block}
@media (max-width:420px){.vitals details.vital>summary{
     grid-template-columns:minmax(0,1fr) 6.5em}.spark{grid-column:1/-1;
     grid-row:2;width:100%}}
.up{color:#156E46;font-weight:bold}.down{color:#A8322A;font-weight:bold}
.steady{color:#b06d00;font-weight:bold}
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
        if delta is None or abs(delta) < (1 if pct else 0.5):
            way = "steady"
            chg = "<span class='steady'>\u2192 steady</span>"
        else:
            way = "up" if delta > 0 else "down"
            chg = "<span class='{}'>{} {}{}</span>".format(
                way, "\u25b2" if delta > 0 else "\u25bc",
                "+" if delta > 0 else "\u2212",
                "{:.0f}{}".format(abs(delta), " pts" if pct else ""))
        pts = [(lab, v.get(key)) for lab, (_d, v) in zip(labs, weeks)]
        rows = "".join("<tr><td>Week of {}</td><td>{}</td></tr>".format(
            lab, _vfmt(v, pct)) for lab, v in reversed(pts))
        out.append(
            "<details class='vital'><summary><span class='vn'>{}</span>"
            "{}<span class='vv'><b>{}</b>{}</span></summary>"
            "<div class='body'><table>{}</table></div></details>".format(
                _e(label), _spark(pts, pct, way), _vfmt(latest, pct), chg, rows))
    out.append("</div><p class='s'>Tap a vital for its week-by-week numbers. "
               "Weeks run Sunday to Saturday, dated by their Sunday. The "
               "change compares the latest week with the 3 before it.</p>")
    return "".join(out)


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
    if i["steps"]:
        out.append("<b>How:</b><ol>{}</ol>".format(
            "".join("<li>{}</li>".format(_e(s)) for s in i["steps"])))
    return "".join(out)


def _facts(facts):
    if not facts:
        return ""
    return "<table>{}</table>".format("".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(_e(k), _e(v))
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
        "<body>".format(_e(card["office"]), CSS + SP.CSS,
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
    add("<input type='radio' name='pg' id='pg0' checked>"
        "<input type='radio' name='pg' id='pg1'>"
        "<input type='radio' name='pg' id='pg2'>"
        "<div class='tabs'><label for='pg0'>Trend</label>"
        "<label for='pg1'>Grade card</label>"
        "<label for='pg2'>AppStream setup</label></div>"
        "<div class='page0'>{}</div>"
        "<div class='page1'>".format(trend_html(card.get("vitals"))))

    if card.get("grading"):
        add("<div class='truth'><b>Make sure these are correct.</b> This is "
            "what we're grading against.<table>")
        for row in card["grading"]:
            label, value = row[0], row[1]
            add("<tr><td>{}</td><td>{}</td></tr>".format(
                _e(label), _e(value) if value else "<i>not on file</i>"))
        add("</table></div>")

    if card["todo"]:
        add("<h2 class='k'>Fix these first</h2><div class='top'>")
        lines = {ln["key"]: ln for ln in card["lines"]}
        for n, t in enumerate(card["todo"], start=1):
            add("<details><summary><span class='num'>{}</span>"
                "<span class='t'>{}</span></summary><div class='body'>"
                .format(n, _e(t["text"])))
            if t["item"]:
                add(_fix_body(t["item"]))
            else:
                ln = lines.get(t["line"]) or {}
                add("<p class='why'>{}</p>{}".format(
                    _e(ln.get("text", "")), _facts(ln.get("facts"))))
            add("</div></details>")
        add("</div>")

    add("<h2 class='k'>Your scorecard</h2>")
    for ln in card["lines"]:
        if ln["key"] == "recruiters":
            continue
        add("<details><summary><span class='dot' style='background:{}'>"
            "</span><span class='row'><span class='t'>{} {}</span>"
            "<span class='s'>{}</span></span></summary><div class='body'>"
            .format(DOT[ln["dot"]], ln["icon"], _e(ln["title"]),
                    _e(ln["short"])))
        if ln["text"]:
            add("<p class='why'>{}</p>".format(_e(ln["text"])))
        add(_facts(ln["facts"]))
        if ln["items"]:
            add("<ul class='acts'>")
            for i in sorted(ln["items"], key=_rank):
                add("<li><details><summary>{}</summary><div class='body'>"
                    "{}</div></details></li>".format(
                        _e(i["action"]), _fix_body(i)))
            add("</ul>")
        add("</div></details>")

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
    add(SP.render(card.get("setup")))
    add("</div>{}</body></html>".format(SP.COPY_JS))
    return "\n".join(L)
