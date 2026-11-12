# -*- coding: utf-8 -*-
"""Build and draw the Applicant Stream Grade Card.

Same shape as the Lucy ECO social card (online_presence/simple_card.py):
one line per section with a green / yellow / red dot, "Do this first" (at
most 3), then every finding with the WHY and the numbered steps to fix it.

Rules it keeps (from the audit it is built on):
  * A section with no data is GREY and says what was missing — never green.
  * Every number says what it is "of". The booking data only holds people
    who booked, so the AI/recruiter split is "of everyone booked".
  * Wrong information (address, Zoom, phone, dead link) always ranks first:
    it sends a real applicant to the wrong place today.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import datetime as dt
import html

GREEN, YELLOW, RED, GREY = "green", "yellow", "red", "grey"
DOT = {GREEN: "#22A35A", YELLOW: "#E8A317", RED: "#D93A3A", GREY: "#9AA0A6"}

# Findings that put wrong information in front of an applicant.
WRONG_INFO = {"WRONG ROOM", "WRONG MEETING ID", "WRONG ADDRESS",
              "CHECK PHONE", "DEAD LINK", "MERGE", "ADDRESS", "PLACEHOLDER"}
# The AI answering an applicant with nothing, or the wrong thing.
AI_BROKEN = {"SILENT AND BLANK", "DEFLECTS", "PROMISES A CALL",
             "PAY WORDING", "AI IS A REAL PERSON", "SAME NAME", "ROUTING"}

# A pull older than this is shown as stale on the card. The AI Settings
# page changed completely on 29-30 Oct; a September pull of it would grade
# an office on a setup it no longer has.
STALE_DAYS = 7
WORDING = {"SHOUTING", "BASE PAY", "NOT PLAIN TEXT", "TOO LONG", "GRAMMAR",
           "NO OPT-OUT", "TYPO", "HOUSE RULE"}

# Most retention the office loses when booked a day or more after push.
LATE_OK, LATE_BAD = 15.0, 25.0


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


def _line(key, icon, title, dot, text, facts=None, items=None):
    return {"key": key, "icon": icon, "title": title, "dot": dot,
            "text": text, "facts": facts or [], "items": items or []}


# ------------------------------------------------------------ sections

def who_books(st):
    w = (st or {}).get("who") or {}
    if not w.get("ok"):
        return _line("who", "\U0001F916", "AI vs recruiters", GREY,
                     "Not checked: {}".format(w.get("why", "no booking pull")))
    ai, hu = w["ai_show"], w["human_show"]
    facts = [
        ("Booked by the AI", "{:.0f}% of everyone booked ({:,})".format(
            w["ai_share"], w["ai_n"])),
        ("Booked by a recruiter", "{:.0f}% ({:,})".format(
            100 - w["ai_share"], w["human_n"])),
        ("Showed up — AI-booked", _pct(ai)),
        ("Showed up — recruiter-booked", _pct(hu)),
        ("Typical time to book — AI / recruiter", "{} / {}".format(
            _hrs(w["ai_median_hours"]), _hrs(w["human_median_hours"]))),
    ]
    if w.get("ai_fast_show") is not None and w.get("human_fast_show") is not None:
        facts.append(("Showed up when booked within a day — AI / "
                      "recruiter", "{} / {}".format(
                          _pct(w["ai_fast_show"]), _pct(w["human_fast_show"]))))
    real = w.get("p") is not None and w["p"] < 0.05
    if ai is None or hu is None:
        dot, text = GREY, "Not enough show/no-show marks to compare."
    elif real and ai > hu:
        gap_fast = ((w.get("ai_fast_show") or 0)
                    - (w.get("human_fast_show") or 0))
        why = ("even when both book within a day"
               if gap_fast >= 5 else
               "partly because the AI books them sooner"
               if gap_fast >= 2 else
               "mostly because the AI books them sooner")
        dot = YELLOW if w["ai_share"] < 70 else GREEN
        text = ("AI-booked applicants show up {:.0f}% vs {:.0f}% for "
                "recruiters, {}. The AI books {:.0f}% — fix its "
                "templates and replies so it can take more.".format(
                    ai, hu, why, w["ai_share"]))
    elif real and hu > ai:
        dot = YELLOW
        text = ("Recruiter-booked applicants show up more ({:.0f}% vs "
                "{:.0f}%). Check the AI's replies below before moving more "
                "to it.".format(hu, ai))
    else:
        dot = GREEN if w["ai_share"] >= 70 else YELLOW
        text = ("No real difference in show-ups ({:.0f}% AI vs {:.0f}% "
                "recruiters). The AI books {:.0f}%.".format(
                    ai, hu, w["ai_share"]))
    return _line("who", "\U0001F916", "AI vs recruiters", dot, text, facts)


def speed(st, ttb=None):
    d = (st or {}).get("days") or {}
    if not d.get("ok"):
        return _line("speed", "⏱️", "Time to book", GREY,
                     "Not checked: {}".format(d.get("why", "no booking pull")))
    p = d["push_to_book"]
    facts = [
        ("Resume processed → booked, average",
         "{:.1f} days ({:.0f} hrs)".format(p["avg_days"], p["avg_h"])),
        ("Resume processed → booked, typical (median)",
         _hrs(p["median_h"])),
        ("Booked the same day they were processed",
         _pct(d["same_day_share"])),
        ("Booked a day or more after", _pct(d["late_share"])),
        ("Showed up — booked within a day / after",
         "{} / {}".format(_pct(d["under_show"]), _pct(d["late_show"]))),
    ]
    if ttb:
        facts.append(("Texts sent before the 1st round was set",
                      "{:.1f} on average (typical {:g})".format(
                          ttb["average"], ttb["median"])))
    else:
        facts.append(("Texts sent before the 1st round was set",
                      "not checked — no SMS log pulled"))
    late = d["late_share"]
    dot = GREEN if late <= LATE_OK else YELLOW if late <= LATE_BAD else RED
    text = ("{:.0f}% are booked a day or more after their resume is "
            "processed. They show up {} vs {} when booked within a "
            "day.".format(late, _pct(d["late_show"]), _pct(d["under_show"])))
    return _line("speed", "⏱️", "Time to book", dot, text, facts)


def best_times(st):
    t = (st or {}).get("times") or {}
    if not t.get("ok"):
        return _line("times", "\U0001F552", "Best times", GREY,
                     "Not checked: {}".format(t.get("why", "no booking pull")))
    top = ", ".join("{} ({:.0f}%)".format(h, s) for h, _n, s in t["top_hours"])
    facts = [("Most bookings happen at", top),
             ("Busiest booking day", "{} ({:.0f}% of the week)".format(
                 *t["top_day"]))]
    if t.get("best_slot"):
        facts.append(("Interview time people show up to most",
                      "{} ({:.0f}%)".format(*t["best_slot"][:2])))
    if t.get("worst_slot"):
        facts.append(("Interview time people show up to least",
                      "{} ({:.0f}%)".format(*t["worst_slot"][:2])))
    text = "Most bookings land at {}.".format(t["top_hours"][0][0])
    if t.get("best_slot") and t.get("worst_slot"):
        text += " {} interviews show up {:.0f}%, {} only {:.0f}%.".format(
            t["best_slot"][0], t["best_slot"][1],
            t["worst_slot"][0], t["worst_slot"][1])
    return _line("times", "\U0001F552", "Best times", GREEN, text, facts)


def drivers(st):
    dr = [d for d in ((st or {}).get("drivers") or [])]
    if not dr:
        return _line("drivers", "\U0001F4C8", "What moves show-ups most",
                     GREY, "Not checked: too few marked interviews.")
    facts = []
    for d in dr[:5]:
        facts.append((d["label"], "{} {:.0f}% vs {} {:.0f}%{}".format(
            d["best"][0], d["best"][1], d["worst"][0], d["worst"][1],
            "" if d["real"] else " (could be chance)")))
    top = [d for d in dr if d["real"]][:1]
    if top:
        d = top[0]
        text = ("Biggest lever: {} — {} show up {:.0f}%, {} "
                "{:.0f}%.".format(d["label"].lower(), d["best"][0],
                                  d["best"][1], d["worst"][0], d["worst"][1]))
    else:
        text = "Nothing stands out beyond chance yet."
    return _line("drivers", "\U0001F4C8", "What moves show-ups most",
                 GREEN, text, facts)


def recruiters(rows):
    if rows is None:
        return _line("recruiters", "\U0001F465", "Recruiter report cards",
                     GREY, "Not checked: no weekly text + booking pulls.")
    if not rows:
        return _line("recruiters", "\U0001F465", "Recruiter report cards",
                     GREY, "No recruiter sent enough texts to grade.")
    low = [r for r in rows if r["grade"] in ("D", "F")]
    dot = RED if low else YELLOW if any(r["grade"] == "C" for r in rows) \
        else GREEN
    text = ("{} recruiter{} graded. {}".format(
        len(rows), "" if len(rows) == 1 else "s",
        "Needs a talk: " + ", ".join(r["name"] for r in low) if low
        else "Nobody below a C."))
    facts = [(r["name"], "{} · booked {} · showed {} · work "
              "on: {}".format(r["grade"], r["booked"], r["retention"],
                              r["focus"])) for r in rows]
    return _line("recruiters", "\U0001F465", "Recruiter report cards", dot,
                 text, facts)


FOLD_AT = 3


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
        steps = [s.replace("“{}”".format(w), "each one listed above")
                 .replace(w, "each one listed above") for s in first["steps"]]
        out.append(dict(first, where="{} of them".format(len(g)),
                        found="\n".join("• " + x["where"] for x in g),
                        steps=steps, count=len(g)))
    return out


def _checked_line(key, icon, title, items, skipped, ok_text, red_kinds):
    items = fold(items)
    if skipped and not items:
        return _line(key, icon, title, GREY,
                     "Not checked: " + "; ".join(skipped))
    if not items:
        return _line(key, icon, title, GREEN, ok_text)
    red = any(i["kind"] in red_kinds for i in items)
    n = sum(i.get("count", 1) for i in items)
    text = "{} thing{} to fix.".format(n, "" if n == 1 else "s")
    if skipped:
        text += " Not checked: " + "; ".join(skipped)
    return _line(key, icon, title, RED if red else YELLOW, text,
                 items=items)


def build(office, stats=None, ttb=None, recruiter_rows=None,
          info_items=(), info_skipped=(), word_items=(), word_skipped=(),
          ai_items=(), ai_skipped=(), sources=(), now=None):
    """The whole card as data. `sources` is [(what, date or None, where)]."""
    now = now or dt.datetime.now()
    fresh = []
    for what, when, where in sources:
        age = (now.date() - when).days if when else None
        fresh.append({"what": what, "when": when, "where": where,
                      "age": age,
                      "stale": age is None or age > STALE_DAYS})
    lines = [
        _checked_line("info", "\U0001F4CD", "Address, Zoom link, phone",
                      list(info_items), list(info_skipped),
                      "Everything matches what the office gave us.",
                      WRONG_INFO),
        _checked_line("ai", "\U0001F4AC", "AI texts and escalations",
                      list(ai_items), list(ai_skipped),
                      "AI is set up to the standard.", AI_BROKEN),
        _checked_line("words", "✍️", "Grammar and wording",
                      list(word_items), list(word_skipped),
                      "No spelling, grammar or wording problems found.",
                      set()),
        who_books(stats),
        speed(stats, ttb),
        best_times(stats),
        drivers(stats),
        recruiters(recruiter_rows),
    ]
    return {"office": office, "made": now, "lines": lines,
            "span": (stats or {}).get("span"),
            "booked": (stats or {}).get("n"),
            "todo": todo(lines), "sources": fresh,
            "stale": [f for f in fresh if f["stale"]]}


def _rank(item):
    k = item["kind"]
    if k in WRONG_INFO:
        return 0
    if k in AI_BROKEN:
        return 1
    if k.startswith("PREF"):
        return 2
    return 3


def todo(lines, n=3):
    """At most n, wrong information first, then the AI, then the buffers,
    then the booking-speed habit."""
    items = [i for ln in lines for i in ln["items"]]
    items.sort(key=_rank)
    out = [{"text": "{}: {}".format(i["title"], i["where"]),
            "item": i} for i in items[:n]]
    if len(out) < n:
        sp = next((ln for ln in lines if ln["key"] == "speed"), None)
        if sp and sp["dot"] in (YELLOW, RED):
            out.append({"text": "Clear the call list the same day: book "
                                "everyone within 24 hours of being "
                                "processed.", "item": None})
    return out[:n]


# --------------------------------------------------------------- draw

CSS = """
body{font-family:Georgia,'Times New Roman',serif;color:#1d1d1f;
     background:#FBF8F1;max-width:46em;margin:2em auto;padding:0 16px;
     line-height:1.5}
h1{font-size:1.6em;margin:0}
.sub{color:#555;margin:.2em 0 1.4em}
.sec{background:#fff;border:1px solid #e6dfcf;border-radius:10px;
     padding:.9em 1.1em;margin:.7em 0}
.sec h2{font-size:1.1em;margin:0;display:flex;gap:.5em;align-items:center}
.dot{width:.85em;height:.85em;border-radius:50%;display:inline-block;
     flex:none}
.sec p{margin:.35em 0 0}
table{border-collapse:collapse;width:100%;margin-top:.5em;font-size:.95em}
td{padding:.25em .4em;border-top:1px solid #f0ead9;vertical-align:top}
td:first-child{color:#555;width:48%}
.todo{background:#1d1d1f;color:#fff;border-radius:10px;padding:1em 1.2em}
.todo h2{margin:0 0 .3em;font-size:1.15em;color:#E6C46A}
.todo ol{margin:0;padding-left:1.3em}
.fix{border-left:4px solid #E6C46A;padding:.2em 0 .2em .9em;margin:1em 0}
.fix h3{margin:0;font-size:1em}
.found{background:#f6f2e8;padding:.3em .5em;border-radius:6px;
       font-family:Menlo,Consolas,monospace;font-size:.85em;
       white-space:pre-wrap;word-break:break-word}
.why{color:#444}
@media (max-width:520px){td:first-child{width:auto}}
"""


def _e(t):
    return html.escape(str(t if t is not None else ""))


def render(card):
    L = []
    add = L.append
    span = card.get("span")
    sub = "Office {}".format(_e(card["office"]))
    if span:
        # No %-m: it does not exist on Windows.
        sub += " · interviews {}/{} – {}/{}".format(
            span[0].month, span[0].day, span[1].month, span[1].day)
    if card.get("booked"):
        sub += " · {:,} booked".format(card["booked"])
    add("<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Applicant Stream Card {}</title><style>{}</style></head>"
        "<body>".format(_e(card["office"]), CSS))
    add("<h1>Applicant Stream Grade Card</h1>")
    add("<div class='sub'>{}</div>".format(sub))

    if card.get("stale"):
        add("<div class='sec' style='border-color:#D93A3A'><b>Re-pull "
            "before sending:</b> {}</div>".format(_e("; ".join(
                "{} ({})".format(f["what"], "{} days old".format(f["age"])
                                 if f["age"] is not None else "date unknown")
                for f in card["stale"]))))

    if card["todo"]:
        add("<div class='todo'><h2>Do this first</h2><ol>")
        for t in card["todo"]:
            add("<li>{}</li>".format(_e(t["text"])))
        add("</ol></div>")

    for ln in card["lines"]:
        add("<div class='sec'><h2><span class='dot' style='background:{}'>"
            "</span>{} {}</h2><p>{}</p>".format(
                DOT[ln["dot"]], ln["icon"], _e(ln["title"]), _e(ln["text"])))
        if ln["facts"]:
            add("<table>")
            for k, v in ln["facts"]:
                add("<tr><td>{}</td><td>{}</td></tr>".format(_e(k), _e(v)))
            add("</table>")
        add("</div>")

    fixes = [i for ln in card["lines"] for i in ln["items"]]
    if fixes:
        add("<h2 style='margin-top:1.6em'>How to fix each one</h2>")
        for n, i in enumerate(sorted(fixes, key=_rank), start=1):
            add("<div class='fix'><h3>{}. {} — {}</h3>".format(
                n, _e(i["title"]), _e(i["where"])))
            if i.get("found"):
                add("<div class='found'>{}</div>".format(_e(i["found"])))
            if i.get("why"):
                add("<p class='why'><b>Why:</b> {}</p>".format(_e(i["why"])))
            add("<ol>")
            for s in i["steps"]:
                add("<li>{}</li>".format(_e(s)))
            add("</ol></div>")
    if card.get("sources"):
        add("<h2 style='margin-top:1.6em'>Where every number comes from"
            "</h2><table>")
        for f in card["sources"]:
            add("<tr><td>{}</td><td>{} \u00b7 {}</td></tr>".format(
                _e(f["what"]),
                "pulled {}/{}/{}".format(f["when"].month, f["when"].day,
                                         f["when"].year)
                if f["when"] else "pull date unknown",
                _e(f["where"])))
        add("</table>")
    add("<p class='sub' style='margin-top:2em'>Read-only audit of what is "
        "already pulled from ApplicantStream. Grey means not checked, "
        "never passed.</p>")
    add("</body></html>")
    return "\n".join(L)
