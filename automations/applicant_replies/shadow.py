"""Shadow run: what Lucy WOULD have texted, next to what actually went out.

Reads a SAVED SMS log (output/sms_log_<office>*.json from sms_audit.pull_log).
Never logs in to AppStream, never sends a text, never posts to Slack. Output
goes to output/applicant_replies/.

    # free — which moments Lucy would take, by reason; no model calls
    python -m automations.applicant_replies.shadow --office 11280 --triage-only

    # draft replies for a sample (spread across the reasons)
    python -m automations.applicant_replies.shadow --office 11280 --limit 30

    # the 122 real questions from the 9/27 review, Lucy vs what was sent
    python -m automations.applicant_replies.shadow --bench

--log picks a specific saved file (e.g. output/sms_log_11280_w0925.json);
the default is the newest output/sms_log_<office>*.json.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

from automations.applicant_replies import config as C
from automations.applicant_replies import draft as D
from automations.applicant_replies import facts as F
from automations.applicant_replies import guard as G
from automations.applicant_replies import triage as T
from automations.sms_audit import analyze as A
from automations.sms_audit import rebuttals as R

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "output" / "applicant_replies"
BENCH = REPO / "output" / "review-scenarios.json"


def _newest_log(office):
    """pull_log's live file (sms_log_<office>.json) — the kept-aside weeks
    (_w0821 ...) are backfills and their file dates say nothing about which
    week they hold."""
    live = REPO / "output" / "sms_log_{}.json".format(office)
    return live if live.exists() else None


def load(office, log=None):
    path = Path(log) if log else _newest_log(office)
    if not path or not path.exists():
        sys.exit("no saved SMS log for {} — pass --log".format(office))
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["records"] if isinstance(data, dict) and "records" in data else data
    convos = A.log_conversations(rows)
    ends = [m["when"] for c in convos.values() for m in c["msgs"]]
    return path, convos, (max(ends) if ends else None)


def sample(picked, limit):
    """Round-robin across reasons so a sample isn't 30 'unanswered'."""
    by = collections.OrderedDict((r, []) for r in T.REASONS)
    for p in picked:
        by[p[2]].append(p)
    out = []
    while len(out) < limit and any(by.values()):
        for r in T.REASONS:
            if by[r] and len(out) < limit:
                out.append(by[r].pop(0))
    return out


def _who(msg):
    if msg is None:
        return ""
    return "AI" if A.is_ai(msg) else (msg.get("sent_by") or "recruiter")


def run(office, log=None, limit=20, triage_only=False, client=None):
    path, convos, log_end = load(office, log)
    picked = T.pick(convos, log_end)
    turns = sum(len(T.turns(c)) for c in convos.values())
    counts = collections.Counter(p[2] for p in picked)
    print("{}: {} conversations, {} applicant turns, Lucy would take {}"
          .format(path.name, len(convos), turns, len(picked)))
    for r in T.REASONS:
        print("  {:<11} {}".format(r, counts.get(r, 0)))
    if triage_only:
        return None

    rows = []
    for convo, turn, reason, detail in sample(picked, limit):
        ftxt, gaps = F.block(office, turn["at"].date())
        if ftxt is None:
            sys.exit(gaps[0])
        err = ""
        try:
            if reason in T.NO_TEXT:
                # No model call: these never get a text from Lucy.
                d = {"reply": "", "hand_to_person": reason == "scheduling",
                     "note_for_team": ("Wants to book or move an interview: "
                                       "“{}”".format(turn["q"][:160])
                                       if reason == "scheduling" else ""),
                     "facts_used": []}
            else:
                d = D.write(ftxt, convo, turn, reason, detail, client=client)
        except Exception as e:  # noqa: BLE001 — one bad draft never stops the run
            d, err = {"reply": "", "hand_to_person": True, "note_for_team": "",
                      "facts_used": []}, "{}: {}".format(type(e).__name__, e)
        text, probs = G.check(office, d["reply"], turn["at"].date(), reason)
        if err:
            probs = ["draft failed — " + err]
        rows.append({
            "phone_last4": convo["phone"][-4:],
            "applicant": convo["name"],
            "at": turn["at"].strftime("%Y-%m-%d %H:%M"),
            "reason": reason, "why": detail,
            "applicant_said": turn["q"],
            "we_sent": turn["reply"],
            "sent_by": _who(turn["reply_msg"]),
            "wait_min": "" if turn["wait_min"] is None else int(turn["wait_min"]),
            "lucy_would_send": text,
            "verdict": "HELD" if probs else ("quiet" if not text else "ok"),
            "problems": "; ".join(probs),
            "hand_to_person": "yes" if d["hand_to_person"] else "",
            "note_for_team": d["note_for_team"],
            "gaps": ", ".join(gaps),
        })
    return _write(office, rows, path.name, counts, len(picked))


def _write(office, rows, src, counts, total):
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    csv_path = OUT / "shadow-{}-{}.csv".format(office, stamp)
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    v = collections.Counter(r["verdict"] for r in rows)
    md = ["# Lucy shadow run, {} ({})".format(office, stamp), "",
          "Source: `output/{}`. Shadow only: nothing was sent.".format(src), "",
          "Lucy would take **{}** moments: ".format(total) + ", ".join(
              "{} {}".format(r, counts.get(r, 0)) for r in T.REASONS) + ".", "",
          "Drafted {}: **{} ok**, {} held by the house checks, {} stay quiet."
          .format(len(rows), v.get("ok", 0), v.get("HELD", 0), v.get("quiet", 0)),
          ""]
    for r in rows:
        md += ["### {} · {} · {}".format(r["reason"], r["at"], r["verdict"]),
               "- **Applicant:** " + r["applicant_said"],
               ("- **We sent** ({}, {} min later): {}".format(
                   r["sent_by"], r["wait_min"], r["we_sent"])
                if r["we_sent"] else "- **We sent:** nothing"),
               "- **Lucy:** " + (r["lucy_would_send"] or "(nothing)")]
        if r["problems"]:
            md.append("- **Held:** " + r["problems"])
        if r["hand_to_person"]:
            md.append("- **For the team:** " + r["note_for_team"])
        md.append("")
    md_path = OUT / "shadow-{}-{}.md".format(office, stamp)
    md_path.write_text("\n".join(md), encoding="utf-8")
    print("wrote", md_path)
    if rows:
        print("wrote", csv_path)
    return md_path


def bench(limit=None, client=None):
    """Lucy against the 122 real exchanges from the 9/27 review.

    Each question is scored with the CURRENT rebuttals rules for both the
    reply that went out and Lucy's — not the verdict stored in the file,
    which predates rulings 1 and 4. Questions are answered without the rest
    of their thread, so this tests the answer, not the reading of context.
    """
    items = json.loads(BENCH.read_text(encoding="utf-8"))
    if limit:
        items = items[:limit]
    rows = []
    when = dt.datetime(2026, 9, 25, 12, 0)
    for it in items:
        m = re.search(r"\((\d{5})\)", it.get("office", ""))
        office = m.group(1) if m else "11280"
        convo = {"phone": "0000000000", "name": it.get("name", ""),
                 "msgs": [{"when": when, "dir": "In", "body": it["q"],
                           "sent_by": "", "source": "", "template": "",
                           "status": ""}]}
        turn = {"q": it["q"], "at": when, "upto": 0}
        ftxt, gaps = F.block(office, when.date())
        reason, detail = T.classify(dict(turn, reply_msg=None, wait_min=None))
        reason = reason or "dodged"
        try:
            d = D.write(ftxt, convo, turn, reason, detail, client=client)
            err = ""
        except Exception as e:  # noqa: BLE001
            d, err = {"reply": "", "hand_to_person": True}, str(e)
        text, probs = G.check(office, d["reply"], when.date(), reason)
        _, sent_probs = G.check(office, it["a"], when.date(), reason)
        was = R.score(it["q"], it["a"])
        now = R.score(it["q"], text)
        rows.append({
            "office": office, "topic": it.get("topic", ""), "q": it["q"],
            "sent_by": it.get("who", ""), "sent": it["a"],
            "sent_verdict": was[1] if was else "",
            "sent_breaks_rules": "; ".join(sent_probs),
            "lucy": text, "lucy_verdict": now[1] if now else "",
            "lucy_breaks_rules": "; ".join(probs) or err,
            "lucy_hands_off": "yes" if d.get("hand_to_person") else "",
        })
        print("  {:<10} -> {:<10} {}".format(rows[-1]["sent_verdict"],
                                             rows[-1]["lucy_verdict"],
                                             it["q"][:60]))
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    path = OUT / "bench-{}.csv".format(stamp)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    sv = collections.Counter(r["sent_verdict"] for r in rows)
    lv = collections.Counter(r["lucy_verdict"] for r in rows)
    print("\n{} questions".format(len(rows)))
    for k in ("gave_it", "deflected", "ignored", ""):
        print("  {:<10} sent {:>3}   lucy {:>3}".format(k or "(no topic)",
                                                       sv.get(k, 0), lv.get(k, 0)))
    print("  breaks a house rule: sent {}   lucy {}".format(
        sum(1 for r in rows if r["sent_breaks_rules"]),
        sum(1 for r in rows if r["lucy_breaks_rules"])))
    print("wrote", path)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--office")
    ap.add_argument("--log")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--triage-only", action="store_true")
    ap.add_argument("--bench", action="store_true")
    a = ap.parse_args(argv)
    if a.bench:
        bench(a.limit if a.limit != 20 else None)
    elif a.office:
        run(a.office, a.log, a.limit, a.triage_only)
    else:
        ap.error("--office or --bench")


if __name__ == "__main__":
    main()
