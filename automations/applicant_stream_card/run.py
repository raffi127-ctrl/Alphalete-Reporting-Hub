# -*- coding: utf-8 -*-
"""Build one office's Applicant Stream Grade Card from what is on disk.

    python -m automations.applicant_stream_card.run --office 11280
    python -m automations.applicant_stream_card.run --office 11280 --no-sheets

Reads (nothing is pulled here — every source has its own puller):
    output/sms_thread_dump_<id>.json   sms_thread_dump --actions
    output/sms_log_<id>*.json          sms_log  (p=336)
    output/ai_settings_<id>.json       pull_ai_settings
    output/escalations_<id>.json       pull_escalations
    "AS Templates <id>" tab            as_templates_probe
    "Recruiting Audit Offices" tab     the address / Zoom / phone on file

Writes output/applicant-stream-card-<id>.html. Posts and sends nothing.
"""
from __future__ import annotations  # Lucy runs Python 3.9 — keep lazy

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.applicant_stream_card import card as C
from automations.applicant_stream_card import fixes as F
from automations.applicant_stream_card import stream_stats as S

OUTPUT = Path(__file__).resolve().parents[2] / "output"

# ai_settings checks this card replaces with the written-down standard.
REPLACED = {"WINDOW TOO SHORT", "GHOST TOO SOON"}
# Template checks the card does not grade. Megan 2026-11-12, on "Add Reply
# STOP to opt out to 30 templates": "we're not doing this anywhere".
NOT_GRADED = {"NO OPT-OUT"}
TYPO_LIMIT = 10


def _office(oid, use_sheets=True):
    from automations.sms_audit import offices as O
    row = None
    if use_sheets:
        try:
            row = O.find(oid)
        except Exception as e:  # noqa: BLE001
            print("[card] office sheet unreadable: {}".format(e))
    return row or {"office": oid}


def _template_bodies(oid, use_sheets):
    """(bodies, states) of the saved templates, or (None, why). The raw
    pull text is left on _template_bodies.text for page 2."""
    _template_bodies.text = None
    if not use_sheets:
        return None, "templates not read (--no-sheets)"
    from automations.sms_audit import templates as T
    try:
        text, _src = T.load_text(office=oid)
    except Exception as e:  # noqa: BLE001 — not pulled yet is not a failure
        return None, "no templates pulled yet ({})".format(type(e).__name__)
    _template_bodies.text = text      # page 2 reads the email list off it
    return (T.parse_bodies(text), T.parse_activation(text)), None


ZOOM = re.compile(r"https?://[\w.-]*zoom\.us/j/\d+")


def zoom_in_use(bodies, states):
    """{1: [links], 2: [links]} — Zoom links the LIVE templates send, by
    round, most used first. A template is 2nd round when its section says
    Second Interview / 2nd Interview / 2nd Round; "2nd Left Message - Call
    List" is still a 1st-round call-list text."""
    import collections
    seen = {1: collections.Counter(), 2: collections.Counter()}
    for section, _name, body in bodies or []:
        if states.get(section) != "Activated":
            continue
        rnd = 2 if SECOND.search(section or "") else 1
        for url in ZOOM.findall(body or ""):
            seen[rnd][url.rstrip("/")] += 1
    return {r: [u for u, _n in c.most_common()] for r, c in seen.items()}


SECOND = re.compile(r"(second|2nd)\s*(interview|round|rd)", re.I)


def _mode(raw):
    m = (raw or "").strip().lower()
    if m.startswith("zoom") or "virtual" in m or "online" in m:
        return "Zoom"
    if "person" in m or "office" in m:
        return "In person"
    return ""


def grading_facts(office, sinfo, zooms):
    """What every check grades against, shown at the top of the card.

    Megan 2026-11-12: "read the set information in the AI settings of what
    the office name is, the address that's set, the phone number that's set
    ... make sure these are correct. This is what we're grading against."
    Then: "an office could have a separate Zoom link for first rounds than
    second rounds ... first rounds conducted in person or over Zoom, second
    rounds in person or over Zoom." And no "where it came from" line: "just
    needs to know that's what's being sent out".

    Name, address and phone come from AI Settings. AI Settings holds no Zoom
    link and one interview type, so each round's way of interviewing comes
    from what the office told us, and its link from what they told us or,
    failing that, the link their live templates send for that round."""
    si = sinfo or {}
    zooms = zooms if isinstance(zooms, dict) else {1: list(zooms or []),
                                                   2: []}
    addr = ", ".join(x for x in (
        (si.get("office_address1") or "").strip(),
        (si.get("office_city") or "").strip(),
        " ".join(x for x in ((si.get("office_state") or "").strip(),
                             (si.get("office_zip") or "").strip()) if x),
    ) if x)
    if addr:
        office["address"] = addr
    if (si.get("office_phone") or "").strip():
        office["phone"] = si["office_phone"].strip()
    for rnd, key, mode_key in ((1, "zoom", "r1_mode"),
                               (2, "zoom2", "r2_mode")):
        # An in-person round has no room: a Zoom link in its templates is
        # a mistake to flag, never the link to grade against.
        if _mode(office.get(mode_key)) == "In person":
            office[key] = ""
            continue
        if not (office.get(key) or "").strip() and zooms.get(rnd):
            office[key] = zooms[rnd][0]
    # A single-room office runs both rounds in one Zoom.
    if not office.get("zoom2") and _mode(office.get("r2_mode")) == "Zoom":
        office["zoom2"] = office.get("zoom") or ""

    def how(rnd, mode_key, link_key):
        mode = _mode(office.get(mode_key))
        if not mode and rnd == 1:
            mode = _mode(si.get("interview_type"))
        link = (office.get(link_key) or "").strip()
        if not mode and link:
            mode = "Zoom"
        if mode == "Zoom":
            return "Zoom \u00b7 {}".format(link) if link else \
                "Zoom \u00b7 link not on file"
        if mode == "In person":
            return "In person \u00b7 {}".format(addr) if addr else "In person"
        return None
    return [
        ("Office name", (si.get("office_name") or "").strip() or None),
        ("Address", addr or None),
        ("Phone", office.get("phone") if si.get("office_phone") else None),
        ("1st rounds", how(1, "r1_mode", "zoom")),
        ("2nd rounds", how(2, "r2_mode", "zoom2")),
    ]


def _recruiters(oid):
    """One row per graded recruiter, from the per-recruiter scorecards."""
    from automations.sms_audit import scorecard as SC
    try:
        people = SC.collect(oid)
    except Exception as e:  # noqa: BLE001
        print("[card] recruiter scorecards unavailable: {}".format(e))
        return None
    if not people:
        return None
    rows = []
    for key, p in people.items():
        if SC.is_ai(p["display"]):
            continue
        weeks = sorted(p["weeks"])
        if sum(w.get("texts", 0) for w in p["weeks"].values()) < SC.MIN_TEXTS:
            continue
        g = SC.grade_of(p, weeks)
        if not g:
            continue
        last = p["weeks"][weeks[-1]]
        ret = SC._rate(last, "shown", "booked")
        fix = SC.failing(SC.work_on(p, weeks))
        rows.append({
            "name": p["display"], "grade": g,
            "booked": sum(w.get("booked") or 0 for w in p["weeks"].values()),
            "retention": "{:.0f}%".format(ret) if ret is not None else "-",
            "focus": fix[0]["area"] if fix else "keep it up",
            # The full scorecard, inline: Megan 2026-11-12, "just click the
            # recruiter name and have their full scorecard show".
            "body": _scorecard_html(SC, p, oid, weeks),
            "file": "scorecard-{}-{}.html".format(
                oid, re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-"))})
    rows.sort(key=lambda r: "FDCBA".index(r["grade"]))
    return rows


def _file_date(path):
    p = OUTPUT / path
    return dt.date.fromtimestamp(p.stat().st_mtime) if p.exists() else None


def _tab_date(oid):
    """'pulled 2026-10-01T09:12:00 from AppStream p=1504' off the AI
    Settings tab's first cell, or the local file's date."""
    local = _file_date("ai_settings_{}.json".format(oid))
    if local:
        return local, "output/ai_settings_{}.json".format(oid)
    try:
        from automations.sms_audit import ai_settings_tab as TAB
        ws = TAB._client().open_by_key(TAB.CONTROL_SHEET_ID).worksheet(
            TAB.tab_for(oid))
        m = re.search(r"(\d{4}-\d{2}-\d{2})", ws.acell("A1").value or "")
        when = dt.date.fromisoformat(m.group(1)) if m else None
        return when, "control sheet tab '{}'".format(TAB.tab_for(oid))
    except Exception:  # noqa: BLE001
        return None, "control sheet tab (unreadable)"


def _log_date(log):
    from automations.applicant_stream_card.stream_stats import _when
    ts = [_when(r.get("sent_at") or r.get("queued_at")) for r in log or []]
    ts = [t for t in ts if t]
    return max(ts).date() if ts else None


def _scorecard_html(SC, person, oid, weeks):
    try:
        body = "\n".join(SC.card_body(person, oid, weeks))
    except Exception as e:  # noqa: BLE001 — a card that will not draw
        return "<p>Scorecard could not be drawn ({}).</p>".format(
            type(e).__name__)
    # Its own "back to the list" link points at a page that is not here.
    return re.sub(r"<p class='date'><a href='#top'>.*?</a></p>", "", body)


def scorecard_css():
    from automations.sms_audit import scorecard as SC
    return SC.CSS


def gather(oid, use_sheets=True):
    from automations.sms_audit import analyze as A
    from automations.sms_audit import ai_settings as AIS
    from automations.sms_audit import escalations as ESC
    from automations.sms_audit import icd_audit as IA
    from automations.sms_audit import offices as O

    from automations.sms_audit import templates as T

    office = _office(oid, use_sheets)
    sinfo, prefs = AIS.load(oid)
    got, tmpl_why = _template_bodies(oid, use_sheets)
    bodies, states = got if got else (None, {})
    grading = grading_facts(office, sinfo, zoom_in_use(bodies, states))
    try:
        IA.apply_address_history(office)
    except Exception as e:  # noqa: BLE001
        print("[card] address history not applied: {}".format(e))

    info, info_skip, words, words_skip, ai, ai_skip = [], [], [], [], [], []
    for gap in O.missing_fields(office):
        (words_skip if "pay" in gap else info_skip).append(gap)

    # --- templates: wrong info vs wording -----------------------------
    if got is None:
        info_skip.append(tmpl_why)
        words_skip.append(tmpl_why)
    else:
        found, _personas = T.lint(bodies, states, office)
        z2 = (office.get("zoom2") or "").strip()
        for kind, text in found:
            if kind in NOT_GRADED:
                continue
            if kind == "WRONG ROOM" and z2 and z2 in text:
                continue          # the office's second room, not a wrong one
            item = F.template(kind, text, office)
            (info if kind in C.WRONG_INFO else words).append(item)

    # --- the booking records + texts ----------------------------------
    recs, _src = A.load_office(oid)
    log, _src2 = A.load_log(oid)
    stats = S.summary(recs) if recs else None
    ttb, median_reply, humans = None, None, None
    if recs and log:
        convos = A.log_conversations(log, A.booked_index(recs))
        ttb = A.texts_to_book(convos)
        msgs = IA.message_findings(office) or {}
        median_reply = msgs.get("median_reply")
        humans = msgs.get("human_senders")
        errs = sorted(msgs.get("errors") or [],
                      key=lambda e: -(e.get("sent") or 1))
        for e in errs[:TYPO_LIMIT]:
            words.append(F.recruiter_text(e))
        if len(errs) > TYPO_LIMIT:
            words_skip.append("{} more typing slips on the recruiter "
                              "scorecards".format(len(errs) - TYPO_LIMIT))
        for e in msgs.get("coaching") or []:
            words.append(F.house_rule(e))
    else:
        words_skip.append("recruiter texts not checked — no SMS log")

    # --- AI Settings + escalations ------------------------------------
    if sinfo is None:
        ai_skip.append("AI Settings page not pulled")
    else:
        for kind, text in AIS.lint(sinfo, prefs, office, median_reply,
                                   None, humans):
            if kind in REPLACED or kind == "NOT PULLED":
                continue
            # ai_settings raises this whenever the two rounds differ. The
            # page holds ONE type, so it is only wrong when that type is
            # not the 1st round's.
            if kind == "ONE INTERVIEW TYPE" and _mode(
                    sinfo.get("interview_type")) == _mode(
                    office.get("r1_mode")):
                continue
            item = F.setting(kind, text, office)
            (info if kind in C.WRONG_INFO else ai).append(item)
        ai.extend(F.check_preferences(prefs))
    rows, src = ESC.load(oid)
    # AppStream appends "Message not sent as written: ..." to a row whose
    # type does not send it. That note is not the office's words: left in,
    # it was measured as part of the reply (a 229-character reply read as
    # 341, "longer than two segments").
    from automations.applicant_stream_card.setup_page import NOT_SENT
    for r in rows:
        r["message"] = NOT_SENT.sub("", r.get("message") or "").strip()
    if not src:
        ai_skip.append("Escalation rows not pulled")
    else:
        summ = F.routing_summary(rows)
        if summ:
            ai.append(summ)
        for kind, text in ESC.lint(rows, office):
            if kind == "NO MESSAGE":     # see fixes.routing_summary
                continue
            item = F.escalation(kind, text, office)
            (info if kind in C.WRONG_INFO else ai).append(item)

    sources = []
    if stats and stats.get("span"):
        sources.append(("Bookings + Action History", stats["span"][1],
                        "AppStream Calendar walk (sms_thread_dump), "
                        "interviews {} to {}".format(*stats["span"])))
    else:
        sources.append(("Bookings + Action History", None, "not pulled"))
    sources.append(("Texts (SMS List Report p=336)", _log_date(log),
                    _src2 if log else "not pulled"))
    when, where = _tab_date(oid) if (sinfo is not None or src) else \
        (None, "not pulled")
    sources.append(("AI Settings + Escalations (p=1504)", when, where))

    from automations.applicant_stream_card import setup_page as SP
    setup = SP.gather(
        sinfo, prefs, rows if src else None, bodies, states,
        pulled={"ai": when},
        emails=SP.parse_email_list(getattr(_template_bodies, "text", None))
        if bodies is not None else None,
        items=info + words + ai)

    hours, _hw = AIS.load_hours(oid)
    slots = S.slots(hours, recs) if hours else None
    setup["hours"] = hours

    from automations.applicant_stream_card import vitals as V
    vitals = V.read(oid) if use_sheets else ([], None)

    return C.build(oid, stats=stats, ttb=ttb, setup=setup, slots=slots,
                   vitals=vitals,
                   recruiter_rows=_recruiters(oid),
                   info_items=info, info_skipped=info_skip,
                   word_items=words, word_skipped=words_skip,
                   ai_items=ai, ai_skipped=ai_skip, sources=sources,
                   grading=grading, delivery=S.delivery(log))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--office", help="AppStream account id")
    who.add_argument("--all", action="store_true",
                     help="every active office on the Recruiting Audit "
                          "Offices tab")
    ap.add_argument("--no-sheets", action="store_true",
                    help="skip the Google Sheet reads (office facts, "
                         "templates)")
    a = ap.parse_args(argv)
    if a.all:
        from automations.sms_audit import offices as O
        rows, src = O.load()
        ids = [o["office"] for o in rows]
        print("[card] {} offices from {}".format(len(ids), src))
    else:
        ids = [a.office.strip()]
    OUTPUT.mkdir(exist_ok=True)
    failed = 0
    for oid in ids:
        try:
            card = gather(oid, use_sheets=not a.no_sheets)
        except Exception as e:  # noqa: BLE001 — one office never stops the rest
            failed += 1
            print("[card] {} FAILED: {}: {}".format(oid, type(e).__name__, e))
            continue
        path = OUTPUT / "applicant-stream-card-{}.html".format(oid)
        path.write_text(C.render(card, scorecard_css()), encoding="utf-8")
        print("[card] {}".format(oid))
        for ln in card["lines"]:
            print("  [{:<6}] {:<28} {}".format(ln["dot"], ln["title"],
                                               ln["short"][:90]))
        for f in card["stale"]:
            print("  STALE: {} ({})".format(f["what"], f["where"]))
        print("[card] wrote {}".format(path))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
