# -*- coding: utf-8 -*-
"""One weekly scorecard per recruiter, week over week.

Megan 2026-10-06: "maybe each recruiter gets their own scorecard for the
week- with a breakdown of what they need to work on week over week stats".

Everything here is already measured somewhere in the audit; this slices it
by PERSON and by WEEK so one recruiter can be handed their own page.

Two traps this module exists to avoid:

**The same person has two names.** Bookings come back as "L. Robinson"
(the Retention Report's initial-and-surname form) while texts come back as
"Leticia Robinson". Keyed naively, every scorecard shows bookings with no
texts or texts with no bookings. `key_of` folds both to first-initial +
surname, and `display` keeps the longest spelling seen.

**A week with no pull must stay blank.** analyze.load_log warns that a
suffixed run with no matching log quietly borrows the current week — which
is how two different weeks once ended up identical. A week is skipped
entirely unless BOTH its booking dump and its log are on disk.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import argparse
import collections
import datetime as dt
import re
import statistics
import sys
from pathlib import Path

from automations.sms_audit import analyze as A
from automations.sms_audit import gradecard as GC
from automations.sms_audit import offices as O
from automations.sms_audit import retention as R

OUTPUT = Path(__file__).resolve().parents[2] / "output"
AI_NAMES = {"a messaging", "ai messaging", "lucy resume pushing", "system",
            "scheduled sms"}
# Below this many texts in a week a rate is one bad morning, not a trend.
MIN_TEXTS = 25
# And below this many MATCHED bookings, a far-out percentage is noise: one
# week of Aisha Ceron's read 100% off two bookings and the next read 0%.
MIN_MATCHED = 10


_FACTS_DONE = set()


def _load_office_facts(oid):
    """Point the per-office checks at THIS office before scoring its texts.

    The scorecard scores the same messages as the audit, so it needs the
    same facts; without them every office is marked against whichever one
    was configured last."""
    if oid in _FACTS_DONE:
        return
    _FACTS_DONE.add(oid)
    try:
        from automations.sms_audit import icd_audit as IA
        row = [o for o in (O.load()[0] or []) if o.get("office") == oid]
        if row:
            IA.apply_address_history(row[0])
    except Exception:  # noqa: BLE001 — a missing config is a gap, not a crash
        pass


def key_of(name):
    """'L. Robinson' and 'Leticia Robinson' -> the same key.

    A trailing team tag is dropped before the surname is taken, but only
    when a real surname is left behind. Without that, "Max Jimenez APT"
    keys on APT, and so do "Anthony Zelaya APT" and "Abdiel Amador APT" —
    three people on one scorecard. With it, "C. NLR" and "Caitlyn NLR"
    still pair, because stripping NLR there would leave nothing to match
    on."""
    n = re.sub(r"[^A-Za-z .'-]", " ", (name or "")).strip()
    if not n:
        return ""
    parts = [p for p in re.split(r"\s+", n) if p]
    if len(parts) >= 3 and parts[-1].isupper() and 2 <= len(parts[-1]) <= 4:
        parts = parts[:-1]
    if len(parts) == 1:
        return parts[0].lower().strip(".")
    first, last = parts[0], parts[-1]
    return "{}.{}".format(first[0].lower(), last.lower())


def is_ai(name):
    n = re.sub(r"[^a-z ]", "", (name or "").lower()).strip()
    return n in AI_NAMES or key_of(name) in {key_of(x) for x in AI_NAMES}


def _median(xs):
    return statistics.median(xs) if xs else None


def week_stats(office, tag):
    """{key: {...}} for one week, or {} when that week was not pulled."""
    oid = office if isinstance(office, str) else office["office"]
    _load_office_facts(oid)
    recs, _s = A.load_office(oid, tag)
    log, _s2 = A.load_log(oid, tag)
    if not recs or not log:
        return {}                      # never borrow another week's answer
    convos = A.log_conversations(log, A.booked_index(recs))

    out = collections.defaultdict(lambda: {
        "display": "", "booked": 0, "shown": 0, "texts": 0,
        "typing": 0, "house": 0, "dodged": 0, "replies": [],
        "far_out": 0, "matched": 0,
        "issues": collections.Counter(), "examples": [], "asked": [],
        "kinds": collections.Counter(), "typos": []})

    def slot(name):
        k = key_of(name)
        if not k:
            return None
        d = out[k]
        def _fullness(x):
            return (sum(c.isalpha() for c in x or ""), len(x or ""))
        if _fullness(name) > _fullness(d["display"]):
            d["display"] = name
        return d

    for r in recs:
        d = slot(r.get("booked_by"))
        if d is None:
            continue
        d["booked"] += 1
        if "No Show" not in (r.get("status") or ""):
            d["shown"] += 1

    for row in log:
        if (row.get("type") or "").strip() != "Out":
            continue
        d = slot(row.get("sent_by") or row.get("source"))
        if d is not None:
            d["texts"] += 1

    for e in A.text_errors(convos):
        d = slot(e.get("sender"))
        if d is None:
            continue
        d["typing"] += 1
        kind = e.get("kind") or "typing"
        d["kinds"][kind] += 1
        if len(d["typos"]) < 40:
            d["typos"].append((kind.capitalize(), needle_of(e.get("detail")),
                               e.get("body") or "", e.get("name") or "",
                               ""))

    who_said = {}
    for c in convos.values():
        for m in c.get("msgs") or ():
            b = " ".join((m.get("body") or "").split())
            if b and b not in who_said:
                who_said[b] = c.get("name") or ""

    def applicant(body):
        return who_said.get(" ".join((body or "").split()), "")

    for e in A.who_to_talk_to(convos, oid):
        d = slot(e.get("sender"))
        if d is None:
            continue
        n = int(e.get("count") or 0)
        d["house"] += n
        d["issues"][e.get("issue") or "?"] += n
        for ex in (e.get("examples") or [])[:3]:
            d["examples"].append((e.get("issue") or "?", ex.get("hit") or "",
                                  ex.get("body") or "",
                                  applicant(ex.get("body")), ""))

    for e in A.dodged_questions(convos):
        d = slot(e.get("sender"))
        if d is None:
            continue
        d["dodged"] += 1
        if e.get("question") and len(d["asked"]) < 6:
            d["asked"].append((
                "Did not answer: {}".format(e.get("bucket") or "a question"),
                "they asked: {}".format(e["question"]),
                e.get("reply") or "", e.get("name") or "",
                why_dodged(e.get("bucket"), e.get("kind"),
                           e.get("question"), e.get("reply"))))

    for st in A.reply_speed_by_sender(convos, min_n=1):
        d = slot(st.get("who"))
        if d is not None:
            d["replies"] = st

    # How far ahead each person booked, from the confirmation text that set
    # the appointment. Megan 2026-10-06 asked whether a falling show rate
    # really was someone booking further out — without this the scorecard
    # was asserting a cause it had not checked.
    from automations.sms_audit import leadtime as LT
    lead = LT.measure(oid, recs=recs, log=log)
    if lead.get("ok"):
        for row in lead["rows"]:
            d = slot(row.get("by"))
            if d is None:
                continue
            d["matched"] += 1
            if LT.bucket_of(row["lead"]) == "more than a day":
                d["far_out"] += 1
    return dict(out)


def collect(office, weeks=None):
    """{key: {'display', 'weeks': {tag: stats}}} across every pulled week."""
    weeks = weeks or R.WEEKS
    people = {}
    for tag in weeks:
        for k, d in week_stats(office, tag).items():
            p = people.setdefault(k, {"display": "", "weeks": {}})
            if (sum(c.isalpha() for c in d["display"]),
                    len(d["display"])) > (
                    sum(c.isalpha() for c in p["display"]),
                    len(p["display"])):
                p["display"] = d["display"]
            p["weeks"][tag] = d
    return people


# ----------------------------------------------------------- what to fix

def _rate(d, num, den):
    n, t = d.get(num) or 0, d.get(den) or 0
    return (100.0 * n / t) if t else None


def work_on(person, weeks):
    """[(area, now, before, grade, what to do)] worst first.

    Megan 2026-10-06: "The AI should have a report card too". It books
    more than anyone, so it belongs here — but you do not coach it. Every
    instruction below is rewritten for it: a person reads their text back,
    the AI gets its message edited in AppStream."""
    got = [w for w in weeks if w in person["weeks"]]
    if not got:
        return []
    bot = is_ai(person.get("display"))
    now = person["weeks"][got[-1]]
    before = person["weeks"][got[-2]] if len(got) > 1 else None
    items = []

    def add(area, value, grade, text, prev=None):
        if grade and grade not in "AB":
            items.append({"area": area, "now": value, "before": prev,
                          "grade": grade, "do": text})

    show = _rate(now, "shown", "booked")
    if show is not None and (now.get("booked") or 0) >= 5:
        prev = _rate(before, "shown", "booked") if before else None
        far = (_rate(now, "far_out", "matched")
               if (now.get("matched") or 0) >= MIN_MATCHED else None)
        farwas = (_rate(before, "far_out", "matched")
                  if before and (before.get("matched") or 0) >= MIN_MATCHED
                  else None)
        if far is not None and farwas is not None and far - farwas >= 5:
            why = ("You're booking further out than you were \u2014 {:.0f}% "
                   "over a day ahead, was {:.0f}%. Use fear of loss and book "
                   "them same or next day.".format(far, farwas))
        elif far is not None and far >= 25:
            why = ("{:.0f}% of your bookings are over a day out. Use fear of "
                   "loss and book them same or next day.".format(far))
        elif bot:
            why = "Offer sooner interview times."
        else:
            why = "Not your booking lead \u2014 look at the texts below."
        add("Show rate", "{:.0f}%".format(show),
            GC._band(show, 55, 48, 40), why,
            "{:.0f}%".format(prev) if prev is not None else None)

    if (now.get("texts") or 0) >= MIN_TEXTS:
        per100 = 100.0 * (now.get("typing") or 0) / now["texts"]
        prevp = (100.0 * (before.get("typing") or 0) / before["texts"]
                 if before and before.get("texts") else None)
        add("Typing and grammar", "{}".format(now.get("typing")),
            GC._band(per100, 0.5, 2, 5, higher_is_better=False),
            "Fix the wording in AppStream." if bot
            else "Read it back before sending.",
            "{}".format(before.get("typing")) if before else None)

    house = now.get("house") or 0
    if house:
        worst = now["issues"].most_common(1)[0][0]
        add("House rules", "{}".format(house),
            GC._band(house, 0, 2, 6, higher_is_better=False),
            "{}. The exact texts are below.".format(worst),
            "{}".format((before or {}).get("house")) if before else None)

    sp = now.get("replies") or {}
    if sp and sp.get("n", 0) >= 10:
        med = sp.get("median")
        prevmed = (before.get("replies") or {}).get("median") if before else None
        add("Reply speed", A_mins(med),
            GC._band(med, 5, 15, 45, higher_is_better=False),
            "Already instant." if bot else "Answer inside 5 minutes.",
            A_mins(prevmed) if prevmed is not None else None)

    dodged = now.get("dodged") or 0
    if dodged:
        add("Questions not answered", str(dodged),
            GC._band(dodged, 0, 2, 6, higher_is_better=False),
            "Give it a real answer in AI Settings, Escalations." if bot
            else "Answer it, then book. The exact ones are below.",
            str((before or {}).get("dodged")) if before else None)

    items.sort(key=lambda i: "FDCBA".index(i["grade"]))
    return items


def A_mins(m):
    if m is None:
        return "—"
    m = float(m)
    if m < 60:
        return "{:.0f} min".format(m)
    return "{:.0f} hr {:.0f} min".format(m // 60, m % 60)


# -------------------------------------------------------------- rendering

CSS = """
body{font-family:Georgia,'Times New Roman',serif;color:#111;max-width:46em;
     margin:2em auto;padding:0 1.1em;line-height:1.5}
h1{font-size:1.5em;margin:0 0 .1em}
h2{font-size:1.1em;margin:1.8em 0 .5em;border-bottom:2px solid #111;
   padding-bottom:.2em}
.date{color:#666;margin:0 0 1.4em}
table{border-collapse:collapse;font-size:.95em;width:100%}
th,td{border:1px solid #ccc;padding:.3em .6em;text-align:left}
th{background:#f2f2f2}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;margin:.6em 0 1em}
.fix{border:2px solid #111;border-radius:6px;padding:.8em 1em;margin:1.2em 0}
.fix h2{margin-top:0;border:0}
tr.F td,tr.D td{background:#fdeaea}
tr.C td{background:#fff4e5}
.up{color:#156E46;font-weight:bold}
.down{color:#A8322A;font-weight:bold}
blockquote{margin:.4em 0 .4em 1em;padding:.3em .7em;border-left:3px solid #bbb;
           background:#f7f7f7;font-size:.95em}
.none{color:#666;font-style:italic}
.bad{color:#A8322A;font-weight:bold;background:#fdeaea}
.asked{color:#555;font-size:.9em;font-style:italic}
.who{color:#555;font-weight:normal}
.why{color:#A8322A;font-weight:bold;margin-top:.35em}
details{margin:.35em 0;border:1px solid #ddd;border-radius:4px;
        padding:.4em .7em;background:#fafafa}
details[open]{background:#fff}
summary{cursor:pointer;font-weight:bold}
summary::marker{color:#888}
@media (max-width:640px){body{margin:1em auto;font-size:15px}}
"""


def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


ASKED = re.compile(r"^\s*they asked:\s*", re.I)


# What each question bucket is actually ASKING, so the fault can be stated
# in words rather than left for the reader to work out. Megan 2026-10-06:
# "we need why this is wrong in red ... Didn't answer the driving question
# or where the location was. Answer isn't relevant to what was asked."
TOPICS = {
    "Is this remote / where is the office?":
        "whether the job is remote and where the office is",
    "What is the pay?": "the pay",
    "Which role / which company is this?": "which role and company this is",
    "What is the job / what do you do?": "what the job actually is",
    "Hours, training, is it paid?":
        "the hours and whether training is paid",
    "How long is the interview / what's next?":
        "how long the interview is",
    "What should I wear / bring?": "what to wear or bring",
    "When will you call me / what number?": "when we would call",
    "How do I join the Zoom / link trouble?": "how to join the Zoom",
    "Can we reschedule / a different time?": "a different time",
    "I can't make it / I'm sick / running late":
        "that they could not make it",
    "Is this a real job / who are you?": "whether this is a real job",
    "I never got the email": "the email they never got",
    "Am I still being considered?":
        "whether they are still being considered",
    "Are you there? (chasing us for a reply)": "their chase for a reply",
}


YES_NO = re.compile(r"^\s*(is|are|was|were|do|does|did|can|could|will|would|"
                    r"should|has|have|am)\b", re.I)
SAYS_YES_NO = re.compile(r"\b(yes|yep|yeah|no|nope|not|isn'?t|aren'?t|"
                         r"doesn'?t|don'?t|won'?t|correct|incorrect)\b", re.I)


def why_dodged(bucket, kind="", question="", reply=""):
    """One red line saying what went wrong with THIS reply.

    Megan 2026-10-06, shown four dodges carrying one identical sentence:
    "this isn't all the same...". They were not. One reply gave the
    interview length to someone asking where the job is; two answered a
    yes-or-no question without saying yes or no. The line is derived from
    what the reply actually does, and falls back to the weakest honest
    claim rather than asserting irrelevance it cannot show."""
    topic = TOPICS.get(bucket) or (bucket or "the question").rstrip("?").lower()
    if kind == "deflected":
        return ("Pushed {} to someone else instead of answering it."
                .format(topic))
    if kind == "informal":
        return "Texting shorthand going out under the company's name."

    q, r = question or "", reply or ""
    # Answered a different question entirely.
    if A.GIVES_DURATION.search(r) and not A.ASKS_DURATION.search(q):
        return ("Gave how long the interview is. They asked about {}."
                .format(topic))
    if A.GIVES_TIME.search(r) and not A.ASKS_WHEN.search(q):
        return "Gave a time. They asked about {}.".format(topic)
    # A yes-or-no question answered sideways. Megan 2026-10-06 on "Is the
    # position in a store?" -> "This is a residential campaign":
    # "technically this does answer but is a bit dodgy, should ask
    # something back". So name it as vague rather than as unanswered, and
    # say what to do — the same shape as ruling 3, answer then reassure.
    if YES_NO.match(q.strip()) and not SAYS_YES_NO.search(r):
        return ("Answers it vaguely and asks nothing back. Say yes or no, "
                "then ask a question.")
    out = "Doesn't answer {}.".format(topic)
    if "?" not in r:
        out += " Nothing asked back, either."
    return out


def needle_of(detail):
    """The words to mark, out of text_errors' description of the fault.

    It writes "your looking (your -> you're)" and "intrested -> interested";
    only the part before the arrow or the bracket is actually in the
    message."""
    d = (detail or "").strip()
    for sep in (" (", " \u2192 ", " -> "):
        if sep in d:
            d = d.split(sep)[0].strip()
    return d


def mark(body, hit):
    """The message in full, with the part that broke the rule in red.

    Megan 2026-10-06: "we want to see EXACTLY what the person is sending
    and highlight in red what isn't approved". The hit is usually a literal
    slice of the message; when it is the APPLICANT's question instead (the
    hiring-manager rule records the question, not our words), the reply's
    own deflection is marked, and the question is shown above it."""
    body = body or ""
    hit = (hit or "").strip()
    asked = ""
    if ASKED.match(hit):
        asked = ASKED.sub("", hit)
        hit = ""
    span = None
    if hit:
        i = body.lower().find(hit.lower())
        if i >= 0:
            span = (i, i + len(hit))
    if span is None:
        from automations.sms_audit import rebuttals as _R
        m = _R.REFUSES.search(body) or _R.DEFERS.search(body)
        if m:
            span = m.span()
    if span is None:
        out = esc(body)
    else:
        a, b = span
        out = "{}<span class='bad'>{}</span>{}".format(
            esc(body[:a]), esc(body[a:b]), esc(body[b:]))
    if asked:
        # No truncation: Megan 2026-10-06 "we need to see exact".
        out = ("<span class='asked'>They asked: {}</span><br>{}".format(
            esc(asked), out))
    return out


# Light red through to light green. Used per ROW, so each measure is
# shaded against its own best and worst week rather than the whole table.
_SHADES = ("#f7c5c0", "#fbdbd3", "#fdeee4", "#f3f6e6", "#dfeedb", "#c6e3c3")


def shade(values, i, higher_is_better=True):
    """Background for cell `i` of `values`, or '' when there is nothing to
    compare it with."""
    nums = [v for v in values if isinstance(v, (int, float))]
    if len(set(nums)) < 2 or not isinstance(values[i], (int, float)):
        return ""
    lo, hi = min(nums), max(nums)
    pos = (values[i] - lo) / float(hi - lo)
    if not higher_is_better:
        pos = 1.0 - pos
    return _SHADES[min(len(_SHADES) - 1, int(pos * len(_SHADES)))]


def render(person, office, weeks, path):
    d = person["weeks"]
    got = [w for w in weeks if w in d]
    L = ["<!doctype html><html><head><meta charset='utf-8'>",
         "<title>Scorecard — {}</title>".format(esc(person["display"])),
         "<style>{}</style></head><body>".format(CSS),
         "<h1>{}</h1>".format(esc(person["display"])),
         "<p class='date'>Account {} · week ending {}</p>".format(
             esc(office), esc(R.week_label(got[-1]) if got else "—"))]
    add = L.append

    fixes = work_on(person, weeks)
    add("<div class='fix'><h2>Work on this</h2>")
    if not fixes:
        add("<p>Nothing above the line this week.</p>")
    else:
        add("<div class='scroll'><table><tr><th>What</th><th>This week</th>"
            "<th>Last week</th><th>Do this</th></tr>")
        for f in fixes:
            add("<tr class='{}'><td>{}</td><td>{}</td><td>{}</td>"
                "<td>{}</td></tr>".format(
                    f["grade"], esc(f["area"]), esc(f["now"]),
                    esc(f["before"] or "—"), esc(f["do"])))
        add("</table></div>")
    add("</div>")

    add("<h2>Week over week</h2>")
    # (label, the number to shade on, how to show it, is more better)
    rows = [
        ("Interviews booked", lambda w: w.get("booked") or 0,
         lambda v: "{:,}".format(v), True),
        ("Showed up", lambda w: _rate(w, "shown", "booked"),
         lambda v: "{:.0f}%".format(v) if v is not None else "\u2014", True),
        ("Texts sent", lambda w: w.get("texts") or 0,
         lambda v: "{:,}".format(v), True),
        ("Usual reply", lambda w: (w.get("replies") or {}).get("median"),
         A_mins, False),
        ("Typing and grammar mistakes", lambda w: w.get("typing") or 0,
         lambda v: "{}".format(v), False),
        ("House rules broken", lambda w: w.get("house") or 0,
         lambda v: "{}".format(v), False),
        ("Questions not answered", lambda w: w.get("dodged") or 0,
         lambda v: "{}".format(v), False),
        ("Booked over a day out",
         lambda w: (_rate(w, "far_out", "matched")
                    if (w.get("matched") or 0) >= MIN_MATCHED else None),
         lambda v: "{:.0f}%".format(v) if v is not None else "\u2014", False),
    ]
    add("<div class='scroll'><table><tr><th></th>" + "".join(
        "<th>{}</th>".format(esc(R.week_label(t))) for t in got) + "</tr>")
    for label, value_of, show, up_good in rows:
        vals = [value_of(d[t]) for t in got]
        cells = []
        for i, v in enumerate(vals):
            bg = shade(vals, i, up_good)
            cells.append("<td class='n'{}>{}</td>".format(
                " style=\"background:{}\"".format(bg) if bg else "",
                esc(show(v))))
        add("<tr><td>{}</td>{}</tr>".format(esc(label), "".join(cells)))
    add("</table></div>")

    last = d[got[-1]] if got else {}
    # Megan 2026-10-06: "Did not answer should be it's own dropdown
    # section". Three kinds of fault, three fixes, three sections — mixed
    # together they read as one undifferentiated pile.
    sections = (
        ("House rules broken", last.get("examples") or [], ""),
        ("Questions not answered", last.get("asked") or [],
         "Did not answer: "),
        ("Typing and grammar", last.get("typos") or [], ""),
    )
    if any(items for _h, items, _p in sections):
        add("<p class='none'>Open any one to read the texts in full, exactly "
            "as they went out. The part that broke the rule is in red.</p>")
    for heading, items, strip in sections:
        if not items:
            continue
        groups = collections.OrderedDict()
        for issue, hit, body, name, why in items:
            label = issue[len(strip):] if strip and issue.startswith(strip) \
                else issue
            groups.setdefault(label, []).append((hit, body, name, why))
        add("<h2>{} \u2014 {}</h2>".format(esc(heading), len(items)))
        for label, rows_ in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            add("<details><summary>{} \u2014 {}</summary>".format(
                esc(label), len(rows_)))
            for hit, body, name, why in rows_:
                add("<blockquote>{}{}{}</blockquote>".format(
                    "<span class='who'>{}</span><br>".format(esc(name))
                    if name else "", mark(body, hit),
                    "<div class='why'>{}</div>".format(esc(why))
                    if why else ""))
            add("</details>")
    add("</body></html>")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def office_summary_html(people, weeks, include_ai=True):
    """The ICD's own breakdown: one row per recruiter, worst first.

    Megan 2026-10-06: "the ICD gets an email breakdown weekly and then each
    recruiter on their market has an attachment to it that is their
    scorecard". So this is the body, and the scorecards ride along as
    files — the ICD reads one table and forwards one attachment."""
    rows = []
    for _k, p in people.items():
        got = [w for w in weeks if w in p["weeks"]]
        if not got:
            continue
        if is_ai(p["display"]) and not include_ai:
            continue
        now = p["weeks"][got[-1]]
        if (now.get("texts") or 0) < MIN_TEXTS:
            continue
        fixes = work_on(p, weeks)
        rows.append((p["display"], now, fixes))
    rows.sort(key=lambda r: (-len(r[2]),
                             -(r[2][0]["grade"] == "F" if r[2] else 0)))

    out = ["<table role='presentation' cellpadding='6' cellspacing='0' "
           "style=\"border-collapse:collapse;font-family:Georgia,serif;"
           "font-size:14px\">",
           "<tr>" + "".join(
               "<th align='left' style=\"border-bottom:2px solid #111\">"
               "{}</th>".format(h)
               for h in ("Recruiter", "Booked", "Showed", "Texts",
                         "Usual reply", "To work on")) + "</tr>"]
    for name, now, fixes in rows:
        show = _rate(now, "shown", "booked")
        top = fixes[0]["area"] if fixes else "nothing"
        out.append(
            "<tr>"
            "<td style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{:,}</td>"
            "<td align='right' style=\"border-bottom:1px solid #ddd\">{}</td>"
            "<td style=\"border-bottom:1px solid #ddd\">{}</td></tr>".format(
                esc(name), now.get("booked") or 0,
                "{:.0f}%".format(show) if show is not None else "—",
                now.get("texts") or 0,
                A_mins((now.get("replies") or {}).get("median")),
                esc(top)))
    out.append("</table>")
    return "\n".join(out), rows


def email_icd(office, people, weeks, paths, to, dry_run=True, logfn=print):
    """One email to the ICD: the table in the body, scorecards attached."""
    from automations.shared import report_email
    got = [w for w in weeks if any(w in p["weeks"] for p in people.values())]
    week = R.week_label(got[-1]) if got else "—"
    body, rows = office_summary_html(people, weeks)
    intro = ("<p>Here is the recruiting week for account {}, ending {}. "
             "Each person's own scorecard is attached — it shows the same "
             "numbers week over week and what to work on.</p>{}".format(
                 esc(office), esc(week), body))
    files = [(name, paths[name]) for name, _n, _f in rows if name in paths]
    return report_email.send_boards(
        subject="Recruiting scorecards — account {} — week ending {}".format(
            office, week),
        to=to, title="RECRUITING SCORECARDS — ACCOUNT {}".format(office),
        blocks=[], intro_html=intro, files=files,
        dry_run=dry_run, logfn=logfn)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="11280")
    ap.add_argument("--email", action="store_true",
                    help="build the ICD email; writes a preview and sends "
                         "NOTHING unless --send is given too")
    ap.add_argument("--send", action="store_true",
                    help="actually send it. Never set this without asking.")
    ap.add_argument("--to", default="", help="comma list, else the office's "
                                             "email from the config tab")
    ap.add_argument("--weeks", default="", help="comma list, default last 6")
    ap.add_argument("--no-ai", action="store_true",
                    help="leave the AI out; by default it gets a card like "
                         "anyone else, because it books more than anyone")
    a = ap.parse_args(argv)

    weeks = [w.strip() for w in a.weeks.split(",") if w.strip()] or R.WEEKS
    people = collect(a.office, weeks)
    if not people:
        print("[scorecard] nothing pulled for {} in {}".format(
            a.office, ", ".join(weeks)))
        return 1
    OUTPUT.mkdir(exist_ok=True)
    made = 0
    paths = {}
    for key, person in sorted(people.items(),
                              key=lambda kv: -sum(
                                  w.get("texts", 0)
                                  for w in kv[1]["weeks"].values())):
        if is_ai(person["display"]) and a.no_ai:
            continue
        total = sum(w.get("texts", 0) for w in person["weeks"].values())
        if total < MIN_TEXTS:
            continue
        path = OUTPUT / "scorecard-{}-{}.html".format(
            a.office, re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-"))
        render(person, a.office, weeks, path)
        paths[person["display"]] = path
        fixes = work_on(person, weeks)
        print("   {:<24} {:>6,} texts · {} to work on -> {}".format(
            person["display"][:24], total, len(fixes), path.name), flush=True)
        made += 1
    print("[scorecard] {} scorecard(s) for {}".format(made, a.office))

    if not a.email:
        return 0
    to = [x.strip() for x in a.to.split(",") if x.strip()]
    if not to:
        cfg = [o for o in (O.load()[0] or []) if o.get("office") == a.office]
        to = [x.strip() for x in ((cfg[0].get("email") if cfg else "") or "")
              .replace(";", ",").split(",") if x.strip()]
    if not to:
        print("[scorecard] no ICD email on file for {} — add one to the "
              "office tab or pass --to. Nothing sent.".format(a.office))
        return 1
    # Standing rule: ask before ANY send. --send is the only way through,
    # and without it this writes the preview and sends nothing.
    res = email_icd(a.office, people, weeks, paths, to, dry_run=not a.send)
    print("[scorecard] {} -> {}".format(
        "SENT" if a.send and res.get("ok") else "preview only", ", ".join(to)))
    if res.get("preview"):
        print("[scorecard] preview: {}".format(res["preview"]))
    return 0 if res.get("ok") or not a.send else 1


if __name__ == "__main__":
    sys.exit(main())
