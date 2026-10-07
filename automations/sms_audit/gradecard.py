# -*- coding: utf-8 -*-
"""The grade card that opens the ICD audit.

Megan 2026-10-06: "we need to be able to point this audit at an account -
have it pull a grade card for the week - the top should breakdown what the
most important things to address are."

Everything here is already measured elsewhere in the audit. This module does
one job: score each area against a stated target, grade it, and rank the
misses so the first thing anyone reads is what to fix.

Two rules it keeps:

  * **A check with no data is NOT a pass.** It comes back as "not measured"
    and is listed apart, so a missing pull can never read as a clean bill.
  * **Every target is written down.** The grade is the number against the
    target on the same row, so nobody has to trust a letter they cannot
    check.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

from automations.sms_audit import call_list as CL
from automations.sms_audit import leadtime as LT
from automations.sms_audit import retention as R

# How many of the office's own texts a typing fault rate is worth reading at.
MIN_TEXTS = 100
# The show rate across all four accounts, six weeks to 25 Sep 2026 (7,260
# bookings). A single office is graded against the group, not an invented
# number — update it when the group moves.
SHOW_BENCHMARK = 48.0

LEVELS = ("critical", "serious", "watch")


def _band(value, good, ok, poor, higher_is_better=True):
    """A letter from the thresholds given, not from a curve.

    good/ok/poor are the cut-offs for A/B/C; anything past `poor` is a D, and
    more than half again past it is an F."""
    if value is None:
        return None
    steps = [(good, "A"), (ok, "B"), (poor, "C")]
    for cut, letter in steps:
        if (value >= cut) if higher_is_better else (value <= cut):
            return letter
    worst = poor * (0.5 if higher_is_better else 1.5)
    if (value >= worst) if higher_is_better else (value <= worst):
        return "D"
    return "F"


def _level(grade):
    return {"A": None, "B": None, "C": "watch",
            "D": "serious", "F": "critical"}.get(grade)


def _item(area, grade, number, target, action, level=None):
    return {"area": area, "grade": grade, "number": number,
            "target": target, "action": action,
            "level": level or _level(grade)}


# --------------------------------------------------------------- the checks

def _conversion(conv):
    """Call list retention. Megan: "the MAIN thing we need to get as high as
    possible - goal at 80%+"."""
    if not conv or not conv.get("ok"):
        return None, ("Call List Retention",
                      (conv or {}).get("why", "no call list or activity pull"))
    rate = conv.get("rate")
    if rate is None:
        return None, ("Call List Retention", "no rate in the pull")
    g = _band(rate, CL.GOAL, CL.GOAL - 10, CL.GOAL - 20)
    return _item(
        "Call List Retention", g,
        "{:.0f}%".format(rate),
        "{:.0f}%".format(CL.GOAL),
        "Work the call list stage losing them."), None


def _show_rate(rows):
    """Did the people we booked turn up."""
    if not rows:
        return None, ("1st Round Retention", "no bookings pulled")
    # retention.load gives tuples ending in the shown flag; a raw thread dump
    # gives dicts with a status. Find the flag by TYPE, not by position — the
    # tuple grew a date column and its docstring still says three fields, so
    # r[2] silently read the booker's name and graded every office 100%.
    def _shown(r):
        if not isinstance(r, (tuple, list)):
            return R.shown(r)
        flags = [x for x in r if isinstance(x, bool)]
        return flags[-1] if flags else None
    marks = [_shown(r) for r in rows]
    marks = [m for m in marks if m is not None]
    if not marks:
        return None, ("1st Round Retention", "no show/no-show flag")
    shown = sum(1 for m in marks if m)
    n = len(marks)
    if not n:
        return None, ("1st Round Retention", "no bookings in the window")
    rate = 100.0 * shown / n
    g = _band(rate, SHOW_BENCHMARK + 7, SHOW_BENCHMARK, SHOW_BENCHMARK - 8)
    return _item(
        "1st Round Retention", g, "{:.0f}%".format(rate),
        "{:.0f}% (all accounts)".format(SHOW_BENCHMARK),
        "Book them sooner. See booking lead time below."), None


def _lead_time(res):
    """How far ahead interviews are booked — the largest lever measured."""
    if not res or not res.get("ok"):
        return None, ("Booking lead time",
                      (res or {}).get("why", "not measured"))
    share = res["late_share"]
    g = _band(share, LT.TARGET, LT.TARGET + 10, LT.TARGET + 20,
              higher_is_better=False)
    by = {b["label"]: b for b in res["buckets"]}
    near = by.get("under 2 hrs") or by.get("2-6 hrs")
    far = by.get("more than a day")
    cost = "Booking too far out. Book them same or next day."
    if near and far:
        cost = ("Booking too far out. Book them same or next day: {:.0f}% show up "
                "against {:.0f}%.".format(near["rate"], far["rate"]))
    return _item(
        "Booking Lead Time", g,
        "{:.0f}% booked over a day ahead".format(share),
        "under {:.0f}%".format(LT.TARGET), cost), None


def _booker_drops(moved):
    """A booker whose show rate fell against their OWN trailing average."""
    if not moved:
        return None, None
    big = [m for m in moved if m[1] - m[2] <= -R.DROP]
    if not big:
        return None, None
    worst = min(big, key=lambda m: m[1] - m[2])
    return _item(
        "Retention Down", "D",
        "{} down to {:.0f}% from {:.0f}%".format(
            worst[0], worst[1], worst[2]),
        "no drop over {:.0f} points".format(R.DROP),
        "Talk to {}.".format(worst[0])), None


def _messages(msgs):
    """House-rule breaches, dodged questions and typing, from the week's log."""
    out, skipped = [], []
    if not msgs:
        return out, [("Recruiter texts", "no SMS log pulled")]
    people = msgs.get("people") or 0

    errs = msgs.get("errors") or []
    g = _band(len(errs), 0, 3, 10, higher_is_better=False)
    # Megan 2026-10-06: "what is house rules in texts?" — it was not house
    # rules at all. msgs["errors"] is text_errors: grammar, spelling, a
    # doubled word. The house rules (wrong address, no suite, "base" pay,
    # pushing a job question to the hiring manager) are who_to_talk_to, and
    # were not on the card at all. Two different faults with two different
    # fixes: a typo is coached, a wrong address is a saved reply to edit.
    out.append(_item(
        "Typing and Grammar Mistakes", g,
        "{} message{}".format(len(errs), "" if len(errs) == 1 else "s"), "0",
        "Coach the sender. Listed below."))

    coaching = msgs.get("coaching") or []
    nh = sum(int(e.get("count") or 0) for e in coaching)
    if coaching or errs:
        g = _band(nh, 0, 2, 6, higher_is_better=False)
        worst = max(coaching, key=lambda e: e.get("count") or 0, default=None)
        out.append(_item(
            "House Rules Broken", g,
            "{} text{}".format(nh, "" if nh == 1 else "s"), "0",
            "{}. Fix the saved reply.".format(worst["issue"]) if worst
            else "Fix the saved replies."))

    dod = msgs.get("dodged") or {}
    nd = sum(len(v) for v in dod.values()) if isinstance(dod, dict) else len(dod)
    rate = (100.0 * nd / people) if people else None
    if rate is not None:
        g = _band(rate, 2, 5, 12, higher_is_better=False)
        out.append(_item(
            "Questions Answered", g,
            "{} unanswered".format(nd), "under 2%",
            "Write a standard answer for each."))

    deliv = msgs.get("delivery") or {}
    failed = deliv.get("failed") if isinstance(deliv, dict) else None
    total = deliv.get("total") if isinstance(deliv, dict) else None
    if failed and total:
        frate = 100.0 * failed / total
        g = _band(frate, 3, 6, 11, higher_is_better=False)
        out.append(_item(
            "Texts that arrived", g,
            "{:.0f}% never arrived".format(frate), "under 3%",
            "Carrier is flagging the number."))
    return [o for o in out if o], skipped


def _settings(ai):
    """The AI Settings page — the acceptance window above all."""
    out, skipped = [], []
    if not ai:
        return out, [("AI settings", "nothing pulled from the AI Settings page")]
    win = ai.get("window")
    pulled = not any(f and f[0] == "NOT PULLED"
                     for f in (ai.get("settings") or []))
    if win is None:
        # When the whole page is unpulled, the "AI settings" line below
        # already says so — one line about the page, not one per field.
        if pulled:
            skipped.append(("Time to accept a slot",
                            "the two time settings are not on file"))
    else:
        # 15 is the floor worth calling serious; below ~7 the
        # window is shorter than almost anyone replies, which is
        # what 11280 ran at (5 min against a 26 min median).
        g = _band(win, 45, 25, 15)
        out.append(_item(
            "Time to accept a slot", g,
            "{} minutes".format(win),
            "longer than people usually take to reply",
            "Give applicants longer to take the time offered. "
            "In AI Settings, lower the 'accepted' buffer."))
    setting = ai.get("settings") or []
    if any(f and f[0] == "NOT PULLED" for f in setting):
        skipped.append(("AI settings",
                        "AI Settings not pulled"))
        setting = []
    bad = [f for f in setting if f and f[0] != "OK"]
    if bad:
        out.append(_item(
            "AI settings", "D", "{} fault{}".format(len(bad), "" if len(bad) == 1 else "s"),
            "0",
            "Fix in AI Settings. Listed below."))
    esc = [f for f in (ai.get("escalations") or []) if f and f[0] != "OK"]
    if any(f[0] == "NOT PULLED" for f in esc):
        skipped.append(("What the AI replies to applicants",
                        "escalation rows not pulled"))
    elif esc:
        out.append(_item(
            "What the AI replies to applicants", "D", "{} to fix".format(len(esc)), "0",
            "Edit them in AI Settings, Escalations. Listed below."))
    return [o for o in out if o], skipped


def _templates(tmpl):
    if tmpl is None:
        return None, ("Templates", "templates not pulled")
    found = tmpl[0] if tmpl else []
    if not found:
        return None, None
    g = _band(len(found), 0, 2, 6, higher_is_better=False)
    return _item("Templates", g, "{} to fix".format(len(found)), "0",
                 "Edit the templates."), None


# ------------------------------------------------------------------- public

def build(office, conv=None, msgs=None, ai=None, rows=None, moved=None,
          tmpl=None, gaps=None, lead=None):
    """{'items': ranked findings, 'skipped': checks with no data, 'overall'}"""
    items, skipped = [], []
    for fn, arg in ((_conversion, conv), (_show_rate, rows),
                    (_lead_time, lead), (_booker_drops, moved),
                    (_templates, tmpl)):
        item, skip = fn(arg)
        if item:
            items.append(item)
        if skip:
            skipped.append(skip)
    for fn, arg in ((_messages, msgs), (_settings, ai)):
        got, skips = fn(arg)
        items.extend(got)
        skipped.extend(skips)
    for g in (gaps or []):
        skipped.append(("Office setup", g))

    # A check that produced no grade is missing data, not a finding. It
    # crashed the sort once; drop it here rather than trust every caller.
    items = [i for i in items if i and i["grade"] in "ABCDF"]
    fix = sorted([i for i in items if i["level"]],
                 key=lambda i: (LEVELS.index(i["level"]),
                                "FDCBA".index(i["grade"])))
    ok = sorted([i for i in items if not i["level"]],
                key=lambda i: "ABCDF".index(i["grade"]))
    worst = fix[0]["grade"] if fix else (ok and "B" or "A")
    if skipped and worst in ("A",):
        worst = "B"   # a check that did not run is never a clean A
    return {"items": fix, "holding": ok, "skipped": skipped,
            "overall": worst,
            "counts": {lv: sum(1 for i in fix if i["level"] == lv)
                       for lv in LEVELS}}


CSS = """
.card{border:2px solid #111;border-radius:6px;padding:1em 1.2em;margin:1.4em 0}
.card h2{margin-top:0;border:0}
.gradebox{display:flex;gap:1.2em;align-items:baseline;flex-wrap:wrap}
.letter{font-size:3.4em;font-weight:bold;line-height:1}
.letter.A,.letter.B{color:#156E46}
.letter.C{color:#8a6d00}
.letter.D,.letter.F{color:#A8322A}
.verdict{font-size:1.05em}
tr.critical td{background:#fdeaea}
tr.serious td{background:#fff4e5}
tr.watch td{background:#fbfbe8}
td.lv{font-weight:bold;white-space:nowrap}
td.gr{font-weight:bold;text-align:center;font-size:1.1em}
.skipped{color:#555;font-size:.95em}
"""


def render(card, esc):
    """The grade card as HTML. `esc` is the caller's escaper."""
    L = []
    add = L.append
    add("<div class='card'>")
    add("<h2>Grade card</h2>")
    add("<div class='gradebox'><div class='letter {0}'>{0}</div>".format(
        card["overall"]))
    # Megan 2026-10-06: no running commentary beside the grade. The table
    # below is the count and the order, so saying both again is noise. The
    # empty case still needs a word, or the card is a bare letter.
    if not card["items"]:
        add("<div class='verdict'>Nothing to fix this week.</div>")
    add("</div>")

    if card["items"]:
        add("<div class='scroll'><table>")
        add("<tr><th>#</th><th>What</th><th>Grade</th><th>Now</th>"
            "<th>Target</th><th>Do this</th></tr>")
        for n, i in enumerate(card["items"], start=1):
            add("<tr class='{}'><td class='n'>{}</td><td>{}</td>"
                "<td class='gr'>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>"
                .format(i["level"], n, esc(i["area"]), i["grade"],
                        esc(i["number"]), esc(i["target"]), esc(i["action"])))
        add("</table></div>")

    if card.get("holding"):
        add("<p class='skipped'><b>OK</b></p><div class='scroll'><table>")
        add("<tr><th>What</th><th>Grade</th><th>Now</th>"
            "<th>Target</th></tr>")
        for i in card["holding"]:
            add("<tr><td>{}</td><td class='gr'>{}</td><td>{}</td>"
                "<td>{}</td></tr>".format(
                    esc(i["area"]), i["grade"], esc(i["number"]),
                    esc(i["target"])))
        add("</table></div>")

    if card["skipped"]:
        add("<p class='skipped'><b>Not checked</b> — no data, so not a "
            "pass:</p><ul class='skipped'>")
        for area, why in card["skipped"]:
            add("<li>{} — {}</li>".format(esc(area), esc(why)))
        add("</ul>")
    add("</div>")
    return "\n".join(L)
