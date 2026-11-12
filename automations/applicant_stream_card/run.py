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


def _templates(office, use_sheets):
    if not use_sheets:
        return None, "templates not read (--no-sheets)"
    from automations.sms_audit import icd_audit as IA
    got, why = IA.template_findings(office)
    if got is None:
        return None, why
    return got[0], None


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


def gather(oid, use_sheets=True):
    from automations.sms_audit import analyze as A
    from automations.sms_audit import ai_settings as AIS
    from automations.sms_audit import escalations as ESC
    from automations.sms_audit import icd_audit as IA
    from automations.sms_audit import offices as O

    office = _office(oid, use_sheets)
    if use_sheets:
        try:
            IA.apply_address_history(office)
        except Exception as e:  # noqa: BLE001
            print("[card] address history not applied: {}".format(e))

    info, info_skip, words, words_skip, ai, ai_skip = [], [], [], [], [], []
    for gap in O.missing_fields(office):
        info_skip.append(gap)

    # --- templates: wrong info vs wording -----------------------------
    tmpl, why = _templates(office, use_sheets)
    if tmpl is None:
        info_skip.append(why)
        words_skip.append(why)
    else:
        for kind, text in tmpl:
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
    sinfo, prefs = AIS.load(oid)
    if sinfo is None:
        ai_skip.append("AI Settings page not pulled")
    else:
        for kind, text in AIS.lint(sinfo, prefs, office, median_reply,
                                   None, humans):
            if kind in REPLACED or kind == "NOT PULLED":
                continue
            item = F.setting(kind, text, office)
            (info if kind in C.WRONG_INFO else ai).append(item)
        ai.extend(F.check_preferences(prefs))
    rows, src = ESC.load(oid)
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

    return C.build(oid, stats=stats, ttb=ttb,
                   recruiter_rows=_recruiters(oid),
                   info_items=info, info_skipped=info_skip,
                   word_items=words, word_skipped=words_skip,
                   ai_items=ai, ai_skipped=ai_skip, sources=sources)


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
        path.write_text(C.render(card), encoding="utf-8")
        print("[card] {}".format(oid))
        for ln in card["lines"]:
            print("  [{:<6}] {:<28} {}".format(ln["dot"], ln["title"],
                                               ln["text"][:90]))
        for f in card["stale"]:
            print("  STALE: {} ({})".format(f["what"], f["where"]))
        print("[card] wrote {}".format(path))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
