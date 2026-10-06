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
    """Applied -> booked. Megan: "the MAIN thing we need to get as high as
    possible - goal at 80%+"."""
    if not conv or not conv.get("ok"):
        return None, ("Applied → booked",
                      (conv or {}).get("why", "no call list or activity pull"))
    rate = conv.get("rate")
    if rate is None:
        return None, ("Applied → booked", "no rate in the pull")
    g = _band(rate, CL.GOAL, CL.GOAL - 10, CL.GOAL - 20)
    return _item(
        "Applied → booked", g,
        "{:.0f}% ({} of {})".format(rate, conv.get("booked", "?"),
                                    conv.get("applied", "?")),
        "{:.0f}%".format(CL.GOAL),
        "Every point here is an applicant nobody spoke to. Work the call "
        "list stage that is losing them."), None


def _show_rate(rows):
    """Did the people we booked turn up."""
    if not rows:
        return None, ("Showed up", "no booking records pulled")
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
        return None, ("Showed up", "booking records carry no show/no-show flag")
    shown = sum(1 for m in marks if m)
    n = len(marks)
    if not n:
        return None, ("Showed up", "no bookings in the window")
    rate = 100.0 * shown / n
    g = _band(rate, SHOW_BENCHMARK + 7, SHOW_BENCHMARK, SHOW_BENCHMARK - 8)
    return _item(
        "Showed up", g, "{:.0f}% ({} of {})".format(rate, shown, n),
        "{:.0f}% across all accounts".format(SHOW_BENCHMARK),
        "Read this with the booking lead time row, which carries this "
        "office's own figures: booking nearer the slot moves it further "
        "than coaching anyone."), None


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
    cost = ""
    if near and far:
        cost = (" Booked {}, {:.0f}% showed; booked more than a day ahead, "
                "{:.0f}%.".format(near["label"], near["rate"], far["rate"]))
    return _item(
        "Booking lead time", g,
        "{:.0f}% booked more than a day ahead ({} of {})".format(
            share, res["late"], res["matched"]),
        "under {:.0f}%".format(LT.TARGET),
        "Book nearer the slot.{} Association, not proof — people who book "
        "far ahead may differ — but it is the biggest gap in the "
        "report.".format(cost)), None


def _booker_drops(moved):
    """A booker whose show rate fell against their OWN trailing average."""
    if not moved:
        return None, None
    big = [m for m in moved if m[1] - m[2] <= -R.DROP]
    if not big:
        return None, None
    worst = min(big, key=lambda m: m[1] - m[2])
    return _item(
        "Show rate by booker", "D",
        "{} fell to {:.0f}% from {:.0f}%".format(worst[0], worst[1], worst[2]),
        "no drop beyond {:.0f} points".format(R.DROP),
        "{} booker(s) dropped against their own average. A booker who is "
        "always low is not news; a fall is.".format(len(big))), None


def _messages(msgs):
    """House-rule breaches, dodged questions and typing, from the week's log."""
    out, skipped = [], []
    if not msgs:
        return out, [("Recruiter texts", "no SMS log pulled for this office")]
    people = msgs.get("people") or 0

    errs = msgs.get("errors") or []
    g = _band(len(errs), 0, 3, 10, higher_is_better=False)
    out.append(_item(
        "House rules in texts", g, "{} breach(es)".format(len(errs)), "0",
        "Wrong address, shouting, a pay line that says \"base\" — each "
        "one is a saved reply to correct, not a person to retrain."))

    dod = msgs.get("dodged") or {}
    nd = sum(len(v) for v in dod.values()) if isinstance(dod, dict) else len(dod)
    rate = (100.0 * nd / people) if people else None
    if rate is not None:
        g = _band(rate, 2, 5, 12, higher_is_better=False)
        out.append(_item(
            "Questions answered", g,
            "{} unanswered across {} conversations".format(nd, people), "2%",
            "Pay, dress code, what the job is and how long it takes have no "
            "standard answer today, so every recruiter improvises."))

    deliv = msgs.get("delivery") or {}
    failed = deliv.get("failed") if isinstance(deliv, dict) else None
    total = deliv.get("total") if isinstance(deliv, dict) else None
    if failed and total:
        frate = 100.0 * failed / total
        g = _band(frate, 3, 6, 11, higher_is_better=False)
        out.append(_item(
            "Texts that arrived", g,
            "{:.0f}% never arrived ({} of {})".format(frate, failed, total),
            "under 3%",
            "An undelivered reminder looks exactly like a no-show. The "
            "failure rate climbs with each text sent to the same number."))
    return [o for o in out if o], skipped


def _settings(ai):
    """The AI Settings page — the acceptance window above all."""
    out, skipped = [], []
    if not ai:
        return out, [("AI settings", "nothing pulled from the AI Settings page")]
    win = ai.get("window")
    if win is None:
        skipped.append(("Acceptance window",
                        "AI Settings not pulled, so the two timeslot buffers "
                        "are unknown"))
    else:
        # 15 is the floor worth calling serious; below ~7 the
        # window is shorter than almost anyone replies, which is
        # what 11280 ran at (5 min against a 26 min median).
        g = _band(win, 45, 25, 15)
        out.append(_item(
            "Acceptance window", g, "{} minutes".format(win),
            "at least as long as this office's median reply",
            "This is how long an applicant has to accept the time the AI "
            "offers. Widen it by lowering the ACCEPTED buffer, not by "
            "pushing the offered time out, which spills bookings to "
            "tomorrow."))
    setting = ai.get("settings") or []
    if any(f and f[0] == "NOT PULLED" for f in setting):
        skipped.append(("AI settings",
                        "the AI Settings page has not been pulled for this "
                        "office"))
        setting = []
    bad = [f for f in setting if f and f[0] != "OK"]
    if bad:
        out.append(_item(
            "AI settings", "D", "{} fault(s)".format(len(bad)),
            "0",
            "; ".join(str(f[1])[:90] for f in bad[:3])))
    esc = [f for f in (ai.get("escalations") or []) if f and f[0] != "OK"]
    if any(f[0] == "NOT PULLED" for f in esc):
        skipped.append(("The AI's canned answers",
                        "no escalation rows pulled for this office"))
    elif esc:
        out.append(_item(
            "The AI's canned answers", "D", "{} to fix".format(len(esc)), "0",
            "; ".join(str(f[1])[:90] for f in esc[:3])))
    return [o for o in out if o], skipped


def _templates(tmpl):
    if tmpl is None:
        return None, ("Templates", "templates were not pulled this run")
    found = tmpl[0] if tmpl else []
    if not found:
        return None, None
    g = _band(len(found), 0, 2, 6, higher_is_better=False)
    return _item("Templates", g, "{} to fix".format(len(found)), "0",
                 "A template fault repeats on every send, so one edit is "
                 "worth more than any amount of coaching."), None


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
    c = card["counts"]
    add("<div class='card'>")
    add("<h2>Grade card</h2>")
    add("<div class='gradebox'><div class='letter {0}'>{0}</div>".format(
        card["overall"]))
    if card["items"]:
        bits = ["{} {}".format(c[lv], lv) for lv in LEVELS if c[lv]]
        add("<div class='verdict'>{} to address — {}.<br>"
            "The table is in the order I would work it.</div>".format(
                len(card["items"]), ", ".join(bits)))
    else:
        add("<div class='verdict'>Nothing above the line this week.</div>")
    add("</div>")

    if card["items"]:
        add("<div class='scroll'><table>")
        add("<tr><th>#</th><th>What</th><th>Grade</th><th>This week</th>"
            "<th>Target</th><th>Why it matters / what to do</th></tr>")
        for n, i in enumerate(card["items"], start=1):
            add("<tr class='{}'><td class='n'>{}</td><td>{}</td>"
                "<td class='gr'>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>"
                .format(i["level"], n, esc(i["area"]), i["grade"],
                        esc(i["number"]), esc(i["target"]), esc(i["action"])))
        add("</table></div>")

    if card.get("holding"):
        add("<p class='skipped'><b>Holding up</b> \u2014 measured and on "
            "target:</p><div class='scroll'><table>")
        add("<tr><th>What</th><th>Grade</th><th>This week</th>"
            "<th>Target</th></tr>")
        for i in card["holding"]:
            add("<tr><td>{}</td><td class='gr'>{}</td><td>{}</td>"
                "<td>{}</td></tr>".format(
                    esc(i["area"]), i["grade"], esc(i["number"]),
                    esc(i["target"])))
        add("</table></div>")

    if card["skipped"]:
        add("<p class='skipped'><b>Not measured</b> — these are missing "
            "data, not passes:</p><ul class='skipped'>")
        for area, why in card["skipped"]:
            add("<li>{} — {}</li>".format(esc(area), esc(why)))
        add("</ul>")
    add("</div>")
    return "\n".join(L)
