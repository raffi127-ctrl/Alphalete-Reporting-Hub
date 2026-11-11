"""📆 Activations Scheduled Today — by EMAIL, for owners with no Metrics thread.

Eve 2026-11-10: the board posts in every office's Metrics thread, but 64 owners
with installs this week have no thread (Chan, Pat, Wayne, Tony, Jess, Aaron
Nimako, Alex Roberts...). "por mail": each of them gets their own board by
email every morning, Eve in copy.

Source path: same as run.py — Tableau -> ATT TRACKER 2.1 - D2D -> ORDER LOG ->
'Sales Board Original' -> worksheet 'A.Order Log', last 42 days of sales,
pulled ONCE, then per owner: spe.Install Date = today (Central), still open.

WHO gets a mail: an owner in the RAF ORG section of the ORG Sales Board
(Eve 11/10: nobody outside the org; the captainship sections are not the org) with >= 1 install today who is NOT already covered by
a Metrics thread (an office_metrics office on the scheduler, or Raf's
daily_metrics). Addresses come from captainship_night_knocks.owners (the pinned
owner -> email table the 9 PM knocks mail uses), Eve always in copy. An owner
with installs but no address on file is listed in the summary sent to Eve.

Modes (outward actions OFF by default):
  (no flag)   pull + print who would get what; sends nothing
  --sample    every mail goes to Eve ONLY, subject tagged [SAMPLE]
              (--limit N caps how many; default 3) + the summary
  --send      the live run: each owner + Eve, then the summary to Eve
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tempfile
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from automations.activations_today import pull

EVE = "eve@alphaletemarketing.com"
SUBJECT = "Activations Scheduled Today — {owner} — {day}"
_ROOT = Path(__file__).resolve().parents[2]


# --- who already sees it in Slack --------------------------------------------
def thread_owners() -> set:
    """casefolded owner names whose Metrics thread already carries the board."""
    from automations.activations_today import run as at_run
    from automations.office_metrics import offices as om
    cfg = json.loads((_ROOT / "automations" / "day_orchestrator"
                      / "schedule_config.json").read_text(encoding="utf-8"))
    live_offices = set()

    def walk(d):
        for k, v in d.items():
            if isinstance(v, dict):
                if "command" in v:
                    a = v.get("base_args") or []
                    if (v.get("on_scheduler") and (v.get("cadence") or {}).get("weekdays")
                            and "--office" in a and a.index("--office") + 1 < len(a)):
                        live_offices.add(a[a.index("--office") + 1])
                    elif v.get("on_scheduler") and k in ("aya_metrics", "rashad_metrics"):
                        live_offices.add(k.split("_")[0])
                else:
                    walk(v)
    walk(cfg)
    out = {at_run.DEFAULT_OWNER.casefold()}
    for k, o in om.OFFICES.items():
        if k in live_offices and not o.nds and k not in om.SECTION_OVERRIDES:
            out.add(o.owner.strip().casefold())
    return out


# --- owner name -> address -----------------------------------------------------
def _norm(name: str) -> str:
    s = re.sub(r"[’'`.]", "", (name or "").lower())
    s = re.sub(r"\b(jr|sr|ii|iii)\b", "", s)
    return " ".join(s.replace("-", " ").split())


def recipients_for(owner: str) -> List[str]:
    """[owner address, Eve], or [] when no address is on file. Only the OWNER:
    the knocks table's EXTRA_RECIPIENTS (Blake on Chan's, Starr on Gabe's...)
    were asked for the knocks mail, not this one. Exact name first; then the
    same first + last name (board spellings like "Andre' Burton Jr." /
    "JC Gerard Pascual" vs the table's short forms)."""
    from automations.captainship_night_knocks import owners as ow
    addr = ow.owner_email(owner)
    if not addr:
        n = _norm(owner).split()
        for k in ow.OWNER_EMAILS:
            m = _norm(k).split()
            if len(n) >= 2 and len(m) >= 2 and m[0] == n[0] and m[-1] == n[-1]:
                addr = ow.OWNER_EMAILS[k]
                break
    return [addr, EVE] if addr else []


# --- the org -------------------------------------------------------------------
def org_matcher():
    """True for a name on the live Alphalete ORG Sales Board (or one of its ICD
    Aliases). Eve 2026-11-10: Raf does not want this reaching owners outside
    the org, so an owner who is not on the board gets NO mail."""
    from automations.focus_office_att.aliases import load_aliases
    from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB
    from automations.recruiting_report.fill import open_by_key, _retry
    vals = _retry(_retry(lambda: open_by_key(SHEET_ID).worksheet(SANDBOX_TAB)).get_all_values)
    # ONLY the "RAF ORG" section (Eve 11/10: the captainship sections below it
    # -- Wayne's, Chan's, Tony's... -- are NOT the org). Found by its label,
    # ended at the next section title, never by row number.
    start = next((i for i, r in enumerate(vals)
                  if len(r) > 1 and r[1].strip().upper().startswith("RAF ORG")), None)
    if start is None:
        raise RuntimeError("no 'RAF ORG' section on the org board — sending nothing")
    org = set()
    for r in vals[start + 1:]:
        c = (r[1] if len(r) > 1 else "").strip()
        if "PERFORMANCE" in c.upper() or "CAPTAIN" in c.upper():
            break
        if c and len(c.split()) >= 2 and len(c) < 40 and not any(ch.isdigit() for ch in c):
            org.add(_norm(c))
    if len(org) < 15:
        raise RuntimeError("org board read looks wrong ({} names) — sending nothing"
                           .format(len(org)))
    groups = [{_norm(k), *(_norm(x) for x in v)} for k, v in load_aliases().items()]
    firstlast = {(o.split()[0], o.split()[-1]) for o in org}

    def in_org(name: str) -> bool:
        k = _norm(name)
        keys = {k}
        for g in groups:
            if k in g:
                keys |= g
        return any(x in org or (len(x.split()) >= 2
                                and (x.split()[0], x.split()[-1]) in firstlast)
                   for x in keys)
    return in_org


# --- the mail ------------------------------------------------------------------
def build_mail(owner: str, rows, day: dt.date, png: Path, to: List[str],
               *, sample: bool) -> EmailMessage:
    from automations.scheduled_6_days_out.email_send import FROM_ADDR
    n = len(rows)
    reps = len({r.get(pull.REP, "") for r in rows})
    subject = SUBJECT.format(owner=owner, day=day.strftime("%m/%d/%Y"))
    if sample:
        subject = "[SAMPLE] " + subject
    msg = EmailMessage()
    msg["From"] = FROM_ADDR
    if sample and any(a.lower() != EVE for a in to):
        raise RuntimeError("sample mail must name only Eve, got {}".format(to))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="alphalete.report")
    intro = ("{n} install{s} scheduled today across {r} rep{rs}. "
             "Please have your reps reach out to these customers today."
             .format(n=n, s="" if n == 1 else "s", r=reps, rs="" if reps == 1 else "s"))
    msg.set_content("Hi {},\n\n{}\n\nThe list is in the attached image.\n\n— Lucy"
                    .format(owner.split()[0], intro))
    cid = make_msgid(domain="alphalete.report")
    msg.add_alternative(
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px">'
        "<p>Hi {first},</p><p>{intro}</p>"
        '<p><img src="cid:{cid}" style="max-width:100%;border:1px solid #ddd"></p>'
        "<p>— Lucy</p></div>".format(first=owner.split()[0], intro=intro,
                                     cid=cid[1:-1]),
        subtype="html")
    msg.get_payload()[1].add_related(png.read_bytes(), "image", "png", cid=cid,
                                     filename=png.name)
    return msg


def _send(msg: EmailMessage, to: List[str]) -> None:
    from automations.captainship_night_knocks import mail as nk
    nk.send(msg, to)


def _summary(day, sent, no_email, mode) -> Tuple[str, str]:
    subject = "{}Activations Scheduled Today — owner mails {}".format(
        "[SAMPLE] " if mode == "sample" else "", day.strftime("%m/%d/%Y"))
    li = "".join("<li>{} — {} install{}</li>".format(o, n, "" if n == 1 else "s")
                 for o, n in sent)
    miss = "".join("<li>{} — {} install{}</li>".format(o, n, "" if n == 1 else "s")
                   for o, n in no_email)
    html = ("<p><b>{} owner mail(s) {}.</b></p><ul>{}</ul>".format(
        len(sent), "built (sample: only some sent, to you)" if mode == "sample"
        else "sent", li or "<li>none</li>"))
    if no_email:
        html += ("<p><b>{} owner(s) had installs today but NO email on file "
                 "— they got nothing:</b></p><ul>{}</ul>"
                 "<p>Add their address in captainship_night_knocks/owners.py."
                 "</p>".format(len(no_email), miss))
    return subject, html


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="activations_today.owner_mail")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default: today CT)")
    ap.add_argument("--csv", default=None)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--sample", action="store_true")
    g.add_argument("--send", action="store_true")
    ap.add_argument("--limit", type=int, default=3,
                    help="--sample: how many owner mails to send to Eve")
    args = ap.parse_args(argv)
    mode = "send" if args.send else ("sample" if args.sample else "dry")

    from automations.activations_today import run as at_run
    day = dt.date.fromisoformat(args.day) if args.day else pull.central_today()
    csv_path = Path(args.csv) if args.csv else pull.fetch(day)
    rows = pull.read_rows(csv_path)
    if not rows:
        print("✗ export is EMPTY — sending nothing.")
        return 1
    covered = thread_owners()
    in_org = org_matcher()
    by_owner: Dict[str, list] = {}
    outside = set()
    for r in pull.scheduled_on(rows, day):
        o = r.get(pull.OWNER, "").strip()
        if not o or o.casefold() in covered:
            continue
        if not in_org(o):
            outside.add(o)
            continue
        by_owner.setdefault(o, []).append(r)
    if outside:
        print("  (skipped, not on the ORG board: {})".format(", ".join(sorted(outside))))
    print("=== owner mails — {} — {} owner(s) with installs today and no thread "
          "({}) ===".format(day, len(by_owner), mode.upper()))

    sent, no_email, failed = [], [], []
    out_dir = Path(tempfile.gettempdir()) / "activations_today_mail"
    out_dir.mkdir(exist_ok=True)
    for owner in sorted(by_owner, key=lambda o: -len(by_owner[o])):
        orows = by_owner[owner]
        to = recipients_for(owner)
        if not to:
            no_email.append((owner, len(orows)))
            print("  ✗ {:<28} {:>3} installs — NO EMAIL on file".format(owner, len(orows)))
            continue
        if mode == "dry":
            print("  · {:<28} {:>3} installs → {}".format(owner, len(orows), ", ".join(to)))
            sent.append((owner, len(orows)))
            continue
        if mode == "sample" and len(sent) >= args.limit:
            sent.append((owner, len(orows)))
            continue
        try:
            png = out_dir / "activations_today_{}.png".format(_norm(owner).replace(" ", "_"))
            at_run.render(at_run.build(orows, owner, day), png)
            # A SAMPLE names ONLY Eve, in the header too (2026-11-10: the To:
            # line showed the owner while delivery went to Eve alone — it read
            # as sent to Chan, and a reply-all WOULD have reached him).
            dest = [EVE] if mode == "sample" else to
            _send(build_mail(owner, orows, day, png, dest, sample=mode == "sample"), dest)
            sent.append((owner, len(orows)))
            print("  ✓ {:<28} {:>3} installs → {}".format(owner, len(orows), ", ".join(dest)))
        except Exception as e:  # noqa: BLE001 — one owner must not stop the rest
            failed.append(owner)
            print("  ✗ {:<28} FAILED: {}: {}".format(owner, type(e).__name__, str(e)[:200]))

    if mode != "dry":
        from automations.captainship_night_knocks import mail as nk
        subj, html = _summary(day, sent, no_email, mode)
        if failed:
            html += "<p><b>FAILED to send:</b> {}</p>".format(", ".join(failed))
        nk.send_plain(subj, html, [EVE])
    print("=== done: {} mail(s), {} without email, {} failed ===".format(
        len(sent), len(no_email), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
