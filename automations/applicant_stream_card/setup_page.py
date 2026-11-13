# -*- coding: utf-8 -*-
"""Page 2 of the grade card: what ApplicantStream is actually set to.

Megan 2026-11-13, after Aptel changed 25065's buffers from 180/300 to 45/30
without the card showing it: "we need to add a 2nd page to this audit about
the settings in actual app stream - what their SMS / emails say and then the
AI settings overall including the buffer times".

Page 1 grades. This page only SHOWS, as last pulled: AI Settings, the three
AI Preferences numbers next to our standard, every AI reply with its
escalation type, and every SMS template (on/off and its full words). So
anyone can see a change the moment a pull picks it up.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import html
import re

from automations.applicant_stream_card import fixes as F

# AI Settings fields in the order the page shows them, with plain labels.
INFO = [
    ("ai_company_name", "Company name the AI uses"),
    ("office_name", "Office name"),
    ("ai_assistant_name", "AI's name"),
    ("office_address1", "Address"),
    ("office_city", "City"),
    ("office_state", "State"),
    ("office_zip", "Zip"),
    ("office_phone", "Phone"),
    ("interview_type", "Interview type"),
    ("interview_length", "Interview length"),
    ("escalation_contact_name", "Escalation contact"),
    ("escalation_contact_title", "Escalation contact title"),
]

# What each AI Preferences number does, in plain words
# (resources/appstream-ai-preferences-standard.md).
PREFS = [
    ("offered_buffer", "Earliest time the AI can offer",
     "The AI won't offer an interview sooner than this many minutes from "
     "now."),
    ("accepted_buffer", "Earliest time an applicant can pick",
     "An applicant can't pick an interview sooner than this many minutes "
     "from now."),
    ("ghosting_threshold", "Ghosting flag",
     "Minutes of silence before a conversation is flagged as ghosting. "
     "Display only."),
]

# Raf's ARS doc, Auditing Process -> Templates: the texts and emails that
# should be live at every office (resources/recruiting-context/
# ars-processes-2026.md). Names as ApplicantStream spells the steps.
RECOMMENDED_SMS = [
    "Await Call AI", "2nd Left Message - Call List", "No Answer - Call List",
    "On Hold", "Directions", "Directions AI", "2nd Interview Invite",
    "No Show - Interview", "No Show - 2nd Interview",
    "1st Interview - Reschedule", "2nd Interview - Reschedule",
    "Follow Up from Calendar - Left Message",
    "Follow Up from Calendar - No Answer",
    "Follow Up from Calendar - Late Join", "Showed Up - Interview",
    "FDOT/BOB", "First Interview Confirmation",
]
RECOMMENDED_EMAIL = [
    "1st Left Message - Call List", "2nd Left Message - Call List",
    "3rd Left Message - Call List", "Directions", "2nd Interview Invite",
    "2nd Interview - Reschedule", "Second Interview Confirmation", "FDOT/BOB",
]
WHY_ON = ("It's on Raf's list of {} every office should have on. While it's "
          "off, applicants at this step get nothing from us.")
# AI Settings fields the AI drops into its texts — a blank leaves a hole.
MUST_FILL = {"ai_company_name", "office_name", "ai_assistant_name",
             "office_address1", "office_city", "office_state", "office_zip",
             "office_phone", "interview_type"}
WHY_DONT = ("Only Don't Escalate sends our approved words. On any other "
            "type the AI writes its own answer.")


# Who fixes each flag (Megan 2026-11-13: "it can say you or communicate to
# the Aptel team"). Offices can edit their own templates; the AI side is
# set up by Aptel.
YOU = APTEL_FIX = F.WHO_FIXES


# AppStream adds this note to a row whose type does not send its message.
NOT_SENT = re.compile(r"\s*Message not sent as written:.*$", re.S)


def _flag(title, found="", why="", owner="", options=None, link=None):
    return {"title": title, "found": found, "why": why, "owner": owner,
            "options": options or [], "link": link}


def options_html(versions, link=None):
    """'We'd recommend one of these replies' plus ONE link, so a page of 30
    recommendations stays short. With a replies-page link, that page holds
    the 5 versions and their Copy buttons; otherwise the signed-off reply
    opens here with its own Copy button."""
    if link:
        return ("<p class='rec'>We'd recommend one of our approved replies: "
                "<a class='opts-link' href='{}' target='_blank' "
                "rel='noopener'>See the 5 replies \u2197</a></p>"
                "<p class='s'>Copy any one. Anything in red braces there "
                "isn't in AppStream yet, so don't paste one of those."
                "</p>").format(_e(link))
    if not versions:
        return ""
    return ("<p class='rec'>We'd recommend this reply:</p>"
            "<details class='opts'><summary>See the reply</summary>"
            "<div class='body'>{}<p class='s'>Words like officeName fill in "
            "by themselves. Paste as written.</p></div></details>").format(
                "".join("<div class='opt'><span>{}</span><button type='button' "
                        "onclick='cp(this)'>Copy</button></div>".format(_e(v))
                        for v in versions))


# Copy button. The fallback selects the text so a viewer that blocks the
# clipboard still lets you press Cmd/Ctrl+C.
COPY_JS = ("<script>function cp(b){var t=b.previousElementSibling;"
           "function sel(){var r=document.createRange();"
           "r.selectNodeContents(t);var s=getSelection();"
           "s.removeAllRanges();s.addRange(r);"
           "try{document.execCommand('copy')}catch(e){}}"
           "var done=function(){b.textContent='Copied';"
           "setTimeout(function(){b.textContent='Copy'},1500)};"
           "if(navigator.clipboard){navigator.clipboard.writeText("
           "t.innerText).then(done,function(){sel();done()})}"
           "else{sel();done()}}</script>")


def _k(name):
    return F._key(name)


def _section_of(where, sections):
    """The longest section name `where` starts with ("Directions AI / x"
    belongs to Directions AI, not Directions)."""
    hits = [sec for sec in sections if (where or "").startswith(sec)]
    return max(hits, key=len) if hits else None


# What to mark red in "What it says now", per finding kind.
CURLY = re.compile("[\u2018\u2019\u201c\u201d\u2013\u2014\u2026]")
QUOTED = re.compile("\u201c([^\u201d]{2,120}?)\u2026?\u201d")
URL = re.compile(r"https?://\S+")
PHONE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
OPENING = re.compile("\\(the one starting \u201c(.+?)\u2026\u201d\\)")


def _spans(kind, body, detail):
    """[(start, end)] of the part of `body` the finding is about."""
    body = body or ""
    if kind == "PLACEHOLDER":
        return [(0, len(body))]
    if kind == "NOT PLAIN TEXT":
        return [m.span() for m in CURLY.finditer(body)]
    if kind == "BASE PAY":
        return [m.span() for m in re.finditer(r"\bbase\b", body, re.I)]
    out = []
    for frag in (QUOTED.findall(detail or "") + URL.findall(detail or "")
                 + PHONE.findall(detail or "")):
        frag = frag.strip().rstrip(".,)")
        i = body.find(frag) if frag else -1
        if i >= 0:
            out.append((i, i + len(frag)))
    return out


def marked(body, spans):
    """Escaped body with the spans wrapped in <mark>."""
    body = body or ""
    out, at = [], 0
    for a, b in sorted(set(spans)):
        if a < at:
            continue
        out += [_e(body[at:a]), "<mark>", _e(body[a:b]), "</mark>"]
        at = b
    out.append(_e(body[at:]))
    return "".join(out)


def _rec(item):
    """The one-line change, from the walkthrough's own step."""
    steps = [st for st in item.get("steps") or []
             if not st.startswith(("In ApplicantStream", "Find ", "Click Save"))]
    return steps[0] if steps else item.get("title", "")


def _template_of(where, section, tpls):
    """Index of the template a finding's `where` points at, or None."""
    m = OPENING.search(where or "")
    opening = m.group(1) if m else None
    base = OPENING.sub("", where or "").strip()
    for n, (name, body) in enumerate(tpls):
        label = name if name.startswith(section) else "{} / {}".format(
            section, name)
        if base == label and (opening is None or
                              (body or "").startswith(opening)):
            return n
    return None


STATE_ORDER = {"Activated": 0, "Not Activated": 1, "None Created": 2}


def _e(t):
    return html.escape(str(t if t is not None else ""))


def _mins(v):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return str(v or "")
    if n >= 60 and n % 60 == 0:
        return "{} min ({} hr)".format(n, n // 60)
    if n >= 60:
        return "{} min ({:.1f} hr)".format(n, n / 60)
    return "{} min".format(n)


def _templates(bodies, states):
    """[(section, state, [(name, body)])] — on first, then off, then empty.
    The probe sometimes dumps a template twice (the field, then a stray
    input); the same name+body is kept once."""
    by = {}
    for section, name, body in bodies or []:
        body = "\n".join(ln for ln in (body or "").splitlines()
                         if not ln.startswith("[")).strip()
        lst = by.setdefault(section, [])
        if body and (name, body) not in lst:
            lst.append((name, body))
    names = list(states or {}) + [s for s in by if s not in (states or {})]
    out = [(s, (states or {}).get(s, "Unknown"), by.get(s, [])) for s in names]
    out.sort(key=lambda r: STATE_ORDER.get(r[1], 3))
    return out


_EMAIL_ROW = re.compile(r"^(?P<name>.+?)\s*\((?P<state>Activated|Not Activated)\)")


def parse_email_list(text):
    """[(section, state, [(name, "")])] off the Email Templates page (p=325)
    in the template pull. Names and on/off only: the pull opens SMS
    templates to read their words, not emails. A section is ON when any of
    its emails is Activated."""
    if not text or "PAGE p=325" not in text:
        return None
    page = text.split("PAGE p=325", 1)[1].split("\n#####", 1)[0]
    out, recent = [], []
    cur = None
    for raw in page.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "Create New":
            # section name sits 4 lines up: name, description, Found, Multiples
            cur = [recent[-4] if len(recent) >= 4 else "?", "Not Activated", []]
            out.append(cur)
        elif cur is not None:
            m = _EMAIL_ROW.match(raw.strip())
            if m:
                on = m.group("state") == "Activated"
                cur[2].append((m.group("name").strip() + (" (ON)" if on else
                                                          ""), ""))
                if on:
                    cur[1] = "Activated"
        recent.append(line)
    out = [(a, b, c) for a, b, c in out]
    out.sort(key=lambda r: STATE_ORDER.get(r[1], 3))
    return out


def gather(sinfo=None, prefs=None, esc_rows=None, bodies=None, states=None,
           pulled=None, emails=None, items=()):
    """Everything page 2 shows, as data. Any part may be None = not pulled.
    `pulled` is {"ai": date|None, "templates": date|None}."""
    """`items` are page 1's findings (fixes.py items); each is shown again
    here, flagged next to the thing it is about."""
    items = list(items or ())
    out = {"pulled": pulled or {}}
    if sinfo is not None:
        out["info"] = [(label, sinfo.get(key) or "", _flag(
            "Blank. Fill this in.", "",
            "The AI puts this into its texts. Blank leaves a hole in the "
            "message.", APTEL_FIX) if key in MUST_FILL and not
            (sinfo.get(key) or "").strip() else None)
            for key, label in INFO]
        out["info_flags"] = [_flag(i["title"], i["found"], i["why"],
                                   APTEL_FIX)
                             for i in items if i["source"] == "AI Settings"
                             and not i["kind"].startswith("PREF ")]
        out["prefs"] = []
        for key, label, meaning in PREFS:
            now = (prefs or {}).get(key)
            flag = None
            # Flag only what the card grades (fixes.check_preferences), so
            # page 2 never contradicts page 1 over a 45 vs 60.
            hit = [i for i in F.check_preferences({key: now})]
            if hit:
                flag = _flag("We recommend {}".format(_mins(
                    F.STANDARD[key])), "", hit[0]["why"], APTEL_FIX)
            out["prefs"].append((label, now, F.STANDARD[key], meaning, flag))
    if esc_rows is not None:
        approved = {_k(n): (num, msg) for num, n, msg in F.approved_replies()}
        lint = {}
        for i in items:
            if i["source"] == "AI replies" and i["kind"] != "ROUTING":
                lint.setdefault(_k(i["where"]), []).append(_flag(
                    i["title"], i["found"], i["why"], APTEL_FIX))
        rows = sorted(esc_rows, key=lambda r: (r.get("routing") or "",
                                               r.get("name") or ""))
        out["replies"], seen = [], set()
        dupes = set()
        for r in rows:
            k = _k(r.get("name"))
            sig = (k, r.get("routing"), r.get("message"))
            if sig in dupes:          # the pull can list a row twice
                continue
            dupes.add(sig)
            seen.add(k)
            locked = "only" in (r.get("routing") or "").lower()
            flags = list(lint.get(k, []))
            dont = (r.get("routing") or "").lower().replace("\u2019", "'") \
                in ("don't escalate", "dont escalate", "do not escalate")
            # "Silent Only" rows are locked by AppStream: no type to pick.
            words = NOT_SENT.sub("", r.get("message") or "").strip()
            if k in approved and not dont and not locked:
                num, msg = approved[k]
                if words and not lint.get(k):
                    # The words are fine (often ours already); only the type
                    # stops them going out. Don't offer new wording.
                    flags.insert(0, _flag(
                        "We'd recommend: switch this to Don't Escalate so "
                        "your reply actually sends", "",
                        "It's set to {} right now, so AppStream never sends "
                        "this reply. The AI writes its own answer "
                        "instead.".format(r.get("routing") or "another type"),
                        APTEL_FIX))
                else:
                    flags.insert(0, _flag(
                        "We'd recommend: set this to Don't Escalate with one "
                        "of our replies", "", WHY_DONT, APTEL_FIX,
                        F.reply_versions(r.get("name"), msg),
                        F.reply_link(r.get("name"))))
            out["replies"].append((r.get("name"), r.get("routing"),
                                   words, flags))
        out["replies_missing"] = [
            (num, n, msg) for num, n, msg in F.approved_replies()
            if _k(n) not in seen]
    if bodies is not None:
        tpl = _templates(bodies, states)
        names = [sec for sec, _st, _t in tpl]
        by, per = {}, {}
        for i in items:
            if i["source"] != "Templates":
                continue
            sec = _section_of(i["where"], names)
            if not sec:
                continue
            tpls = next(t for sc, _s, t in tpl if sc == sec)
            n = _template_of(i["where"], sec, tpls)
            f = _flag(i["title"], "", i["why"], YOU)
            f["rec"] = _rec(i)
            if n is None:
                f["found"] = i["found"]
                by.setdefault(sec, []).append(f)
            else:
                f["spans"] = _spans(i["kind"], tpls[n][1], i["found"])
                per.setdefault((sec, n), []).append(f)
        rec = {_k(n) for n in RECOMMENDED_SMS}
        out["sms"] = []
        for sec, state, tpls in tpl:
            flags = list(by.get(sec, []))
            if _k(sec) in rec and state != "Activated":
                flags.insert(0, _flag(
                    "Recommend turning this text on" if tpls else
                    "Recommend writing this text and turning it on", "",
                    WHY_ON.format("texts"), YOU))
            full = [(name, body, per.get((sec, n), []))
                    for n, (name, body) in enumerate(tpls)]
            out["sms"].append((sec, state, full, flags))
        have = {_k(sec) for sec in names}
        for sec in RECOMMENDED_SMS:
            if _k(sec) not in have:
                out["sms"].append((sec, "None Created", [], [_flag(
                    "Recommend writing this text and turning it on", "",
                    WHY_ON.format("texts"), YOU)]))
    if emails is not None:
        rec = {_k(n) for n in RECOMMENDED_EMAIL}
        out["email"] = [(sec, state, tpls, [_flag(
            "Recommend turning an email on here", "",
            WHY_ON.format("emails"), YOU)] if _k(sec) in rec and
            state != "Activated" else [])
            for sec, state, tpls in emails]
    out["flags"] = count(out)
    return out


def count(setup):
    """Flags per section of page 2."""
    s = setup or {}
    return {
        "ai": sum(1 for r in s.get("info", []) if r[2])
        + len(s.get("info_flags", [])),
        "prefs": sum(1 for r in s.get("prefs", []) if r[4]),
        "replies": sum(len(r[3]) for r in s.get("replies", []))
        + len(s.get("replies_missing", [])),
        "sms": sum(len(r[3]) + sum(len(t[2]) for t in r[2])
                   for r in s.get("sms", [])),
        "email": sum(len(r[3]) for r in s.get("email", [])),
    }


def _when(d):
    return " · pulled {}/{}/{}".format(d.month, d.day, d.year) if d else ""


def _ampm(start):
    """'08:15 AM' -> 'am'; '12:30 PM' -> 'pm'. Noon counts as afternoon."""
    t = (start or "").strip().upper()
    return "pm" if t.endswith("PM") else "am" if t.endswith("AM") else ""


def _slot_list(lst):
    if not lst:
        return "<span class='s'>none</span>"
    return ", ".join("{}{}".format(
        _e(x.get("start", "").lstrip("0")),
        " ({})".format(x["seats"]) if x.get("seats") else "") for x in lst)


def _flags_html(flags):
    out = []
    for f in flags or []:
        out.append("<div class='flag'><b>\u2691 {}</b>{}{}{}{}</div>".format(
            _e(f["title"]),
            "<div class='found'>{}</div>".format(_e(f["found"]))
            if f.get("found") else "",
            options_html(f.get("options"), f.get("link")),
            "<p class='why'><b>Why:</b> {}</p>".format(_e(f["why"]))
            if f.get("why") else "",
            "<p class='who'><b>Who fixes it:</b> {}</p>".format(
                _e(f["owner"]))
            if f.get("owner") else ""))
    return "".join(out)


def _badge(n):
    return ("<span class='fl'>\u2691 {}</span>".format(n) if n else "")


def _head(title, n, when=None):
    return "<h2 class='k'>{}{} {}</h2>".format(
        _e(title), _e(_when(when)), _badge(n))


def _onoff(state):
    on = state == "Activated"
    return "<span class='onoff {}'>{}</span>".format(
        "on" if on else "off",
        "ON" if on else "OFF" if state == "Not Activated" else "NONE")


def render(setup):
    """HTML for page 2."""
    s = setup or {}
    n = s.get("flags") or count(s)
    total = sum(n.values())
    L = []
    add = L.append
    when = s.get("pulled") or {}
    add("<p class='s'>What ApplicantStream is set to, as of the last pull. "
        "<span class='fl'>\u2691</span> marks what we recommend changing "
        "or setting up, and why.</p>")
    if total:
        add("<p class='flagsum'>\u2691 {} thing{} we recommend changing"
            "</p>".format(total, "" if total == 1 else "s"))

    add(_head("AI Settings", n.get("ai"), when.get("ai")))
    if "info" not in s:
        add("<p class='s'>Not pulled yet.</p>")
    else:
        add("<div class='truth'><table>")
        for label, value, flag in s["info"]:
            add("<tr{}><td>{}</td><td>{}{}</td></tr>".format(
                " class='diff'" if flag else "", _e(label),
                _e(value) if value else "<i>blank</i>",
                _flags_html([flag]) if flag else ""))
        add("</table>{}</div>".format(_flags_html(s.get("info_flags"))))

        add(_head("Buffer times + ghosting", n.get("prefs")))
        add("<div class='truth'><table class='prefs'><tr><th></th>"
            "<th>Set now</th><th>Our standard</th></tr>")
        for label, now, want, meaning, flag in s["prefs"]:
            add("<tr{}><td><b>{}</b><br><span class='s'>{}</span></td>"
                "<td>{}</td><td>{}</td></tr>".format(
                    " class='diff'" if flag else "", _e(label), _e(meaning),
                    _e(_mins(now)) if now not in (None, "") else
                    "<i>blank</i>", _e(_mins(want))))
            if flag:
                add("<tr><td colspan='3'>{}</td></tr>".format(
                    _flags_html([flag])))
        add("</table></div>")

    add(_head("Interview slots (1st rounds)", 0, when.get("ai")))
    if not s.get("hours"):
        add("<p class='s'>Not pulled yet. They're on AI \u2192 AI Settings "
            "\u2192 Hours.</p>")
    else:
        add("<div class='truth'><table class='list'><tr><th>Day</th>"
            "<th>Morning</th><th>Afternoon</th></tr>")
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                    "Saturday", "Sunday"):
            lst = s["hours"].get(day) or []
            am = [x for x in lst if _ampm(x.get("start")) == "am"]
            pm = [x for x in lst if _ampm(x.get("start")) == "pm"]
            add("<tr><td><b>{}</b></td><td>{}</td><td>{}</td></tr>".format(
                day, _slot_list(am), _slot_list(pm)))
        add("</table><p class='s'>The number in brackets is how many "
            "people that time holds. 2nd-round times aren't pulled yet."
            "</p></div>")

    add(_head("AI replies (escalations)", n.get("replies"), when.get("ai")))
    if "replies" not in s:
        add("<p class='s'>Not pulled yet.</p>")
    else:
        if s.get("replies_missing"):
            add("<details open><summary><span class='t'>Not set up at all"
                "</span><span class='s'>{} of our replies</span> {}"
                "</summary><div class='body'>".format(
                    len(s["replies_missing"]),
                    _badge(len(s["replies_missing"]))))
            for num, name, msg in s["replies_missing"]:
                add("<p class='tn'>#{} {}</p>{}".format(num, _e(name),
                    _flags_html([_flag(
                        "Recommend: add it as Don't Escalate", "", WHY_DONT,
                        APTEL_FIX, F.reply_versions(name, msg),
                        F.reply_link(name))])))
            add("</div></details>")
        groups = {}
        for name, routing, msg, flags in s["replies"]:
            groups.setdefault(routing or "(no type)", []).append(
                (name, msg, flags))
        for routing, rows in groups.items():
            nf = sum(len(f) for _n, _m, f in rows)
            add("<details><summary><span class='t'>{}</span>"
                "<span class='s'>{} replies</span> {}</summary>"
                "<div class='body'><table class='list'>".format(
                    _e(routing), len(rows), _badge(nf)))
            for name, msg, flags in rows:
                add("<tr><td><b>{}</b><p class='lbl'>What your current "
                    "reply says:</p><div class='says'>{}</div>{}</td></tr>"
                    .format(_e(name), _e(msg) if msg else
                            "<i class='s'>nothing (blank)</i>",
                            _flags_html(flags)))
            add("</table></div></details>")

    add(_head("SMS templates", n.get("sms"), when.get("templates")))
    if "sms" not in s:
        add("<p class='s'>Not pulled yet.</p>")
    else:
        for section, state, tpls, flags in sorted(
                s["sms"], key=lambda r: (not r[3], STATE_ORDER.get(r[1], 3))):
            add("<details><summary>{}<span class='t'>{}</span>"
                "<span class='s'>{}</span> {}</summary><div class='body'>"
                .format(_onoff(state), _e(section),
                        "{} template{}".format(len(tpls),
                                               "" if len(tpls) == 1 else "s")
                        if tpls else "none saved", _badge(
                            len(flags) + sum(len(t[2]) for t in tpls))))
            add(_flags_html(flags))
            for name, body, tflags in tpls:
                spans = [sp for f in tflags for sp in f.get("spans", [])]
                add("<div class='tpl'><p class='tn'>Template name: {}</p>"
                    "<p class='lbl'>What it says now:</p>"
                    "<div class='says'>{}</div>".format(
                        _e(name), marked(body, spans)))
                for f in tflags:
                    add("<div class='flag'><b>\u2691 We'd recommend:</b> {}"
                        "<p class='why'><b>Why:</b> {}</p>"
                        "<p class='who'><b>Who fixes it:</b> {}</p></div>"
                        .format(_e(f["rec"]), _e(f["why"]), _e(f["owner"])))
                add("</div>")
            if not tpls:
                add("<p class='s'>No template saved here.</p>")
            add("</div></details>")

    add(_head("Email templates", n.get("email"), when.get("templates")))
    if not s.get("email"):
        add("<p class='s'>Not pulled yet.</p>")
    else:
        add("<p class='s'>Which email is switched on in each step. The "
            "wording itself isn't pulled yet.</p>")
        for section, state, tpls, flags in sorted(
                s["email"], key=lambda r: (not r[3], STATE_ORDER.get(r[1], 3))):
            live = [nm[:-5] for nm, _b in tpls if nm.endswith(" (ON)")]
            add("<details><summary>{}<span class='t'>{}</span>"
                "<span class='s'>{}</span> {}</summary><div class='body'>"
                "{}<ul>{}</ul></div></details>".format(
                    _onoff(state), _e(section),
                    _e(", ".join(live)) if live else
                    "{} saved, none on".format(len(tpls)),
                    _badge(len(flags)), _flags_html(flags),
                    "".join("<li>{}</li>".format(_e(nm)) for nm, _b in tpls)
                    or "<li class='s'>none saved</li>"))
    return "\n".join(L)


CSS = """
.tabs{display:flex;gap:.4em;margin:0 0 1em}
.tabs label{flex:1;text-align:center;padding:.55em .4em;border-radius:8px;
     border:2px solid var(--ink);cursor:pointer;font-weight:bold;
     background:#fff}
#pg0,#pg1,#pg2{display:none}
#pg0:checked~.tabs label[for=pg0],#pg1:checked~.tabs label[for=pg1],
#pg2:checked~.tabs label[for=pg2]{
     background:var(--ink);color:#fff}
.page0,.page1,.page2{display:none}
#pg0:checked~.page0,#pg1:checked~.page1,#pg2:checked~.page2{display:block}
table.prefs th{font-size:.8em;color:var(--muted);text-align:left;
     font-weight:normal;padding:.2em .3em}
table.prefs td{text-align:left;white-space:normal}
table.prefs td:first-child{width:auto;color:var(--ink)}
table.prefs tr.diff td:nth-child(2){color:#A8322A;font-weight:bold}
table.list td{text-align:left;white-space:normal}
.onoff{flex:none;font-size:.72em;font-weight:bold;padding:.15em .45em;
     border-radius:5px;min-width:2.8em;text-align:center}
.onoff.on{background:#e3f1e8;color:#156E46}
.onoff.off{background:#eee;color:#777}
.tn{font-weight:bold;margin:.6em 0 .1em}
.flag{background:#fdecea;border-left:3px solid #A8322A;border-radius:6px;
     padding:.4em .6em;margin:.4em 0;font-size:.95em;text-align:left;
     white-space:normal}
.flag .found{background:#fff}
.flag .why{margin:.2em 0}
.rec{margin:.3em 0 .1em}
.tpl{border-top:1px solid var(--line);padding:.5em 0 .2em;margin-top:.4em}
.tpl .tn{margin:0}
.lbl{margin:.3em 0 .1em;color:var(--muted);font-size:.9em}
.says{background:var(--soft);padding:.45em .6em;border-radius:6px;
     white-space:pre-wrap;word-break:break-word}
.says mark{background:#f6c9c4;color:#8f1d14;font-weight:bold;
     border-radius:3px;padding:0 .1em}
details.opts{background:#fff;border:1px solid var(--line);margin:.2em 0}
a.opts-link{color:#1a56c4;font-weight:bold}
details.opts>summary{padding:.35em .6em;color:#1a56c4;font-weight:bold}
details.opts .body{padding:0 .6em .5em}
.opt{display:flex;gap:.6em;align-items:flex-start;border-top:1px solid
     var(--line);padding:.45em 0}
.opt span{flex:1}
.opt button{flex:none;font:inherit;font-size:.85em;padding:.2em .7em;
     border:1px solid #1a56c4;color:#1a56c4;background:#fff;
     border-radius:6px;cursor:pointer}
.flag .who{margin:.2em 0;color:#1a56c4}
.fl{color:#A8322A;font-weight:bold;font-size:.9em;letter-spacing:0;
     text-transform:none}
.flagsum{background:#fdecea;color:#A8322A;font-weight:bold;
     border-radius:8px;padding:.5em .8em}
.truth tr.diff>td:first-child{color:#A8322A;font-weight:bold}
"""
