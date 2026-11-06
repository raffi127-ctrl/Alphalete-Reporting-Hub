"""Verizon office boards, off Credico's emails in the Hub inbox.

    python -m automations.verizon_office.run --office nico               # preview only
    python -m automations.verizon_office.run --office nico --board sales --send
    python -m automations.verizon_office.run --sv FILE.xlsx --cf FILE.xlsx   # local files, preview

Boards:
  sales       daily: Sales Verification xlsx (sales through yesterday) -> per-rep
              board, parent title + thread (Raf's clean-parent rule)
  compliance  weekly: Compliance Flags xlsx -> flagged reps. Posted only where
              offices.py gives it a channel.

NEVER POSTS BLANK OR STALE. A sales file not dated today (= not through
yesterday), or a week with no reps, is reported and nothing is sent.
Preview text always lands in output/verizon_office_preview_<office>_<date>.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from automations.verizon_office import board, parse
from automations.verizon_office import offices as OF

ROOT = Path(__file__).resolve().parents[2]
SENDER = "vzreports@credicousa.com"


def fetch(office: OF.VerizonOffice, which: str, *, since_days: int = 10) -> Optional[Path]:
    """Newest Sales Verification / Compliance Flags xlsx for this office from the
    Hub inbox (redirected from the office's Credico Outlook)."""
    from automations.shared import email_ingest
    subject = {"sales": "Sales Verification", "compliance": "Compliance Flags"}[which]
    glob = f"{subject} - Verizon Wireless - {office.office}*.xlsx"
    dest = Path(tempfile.gettempdir()) / f"verizon_office_{office.key}"
    # Matched by file name + subject, never by sender alone: a redirect keeps
    # Credico as the sender, a forward would not.
    found = email_ingest.fetch_by_globs("", [glob], dest, subject=subject,
                                        since_days=since_days, verbose=False)
    return next(iter(found.values()), None)


def build(which: str, path: Path, today: dt.date) -> Tuple[str, List[str], str]:
    """(parent, thread, problem). problem != "" means DO NOT POST."""
    if which == "sales":
        sv = parse.read_sales_verification(path)
        fd = parse.file_date(path)
        if fd != today:
            return "", [], f"newest Sales Verification is dated {fd}, not today ({today}) — stale"
        if not sv.weeks or not sv.weeks[0].reps:
            return "", [], "Sales Verification has no reps this week — not posting a blank board"
        p, th = board.sales_board(sv)
        return p, th, ""
    cf = parse.read_compliance(path)
    if not cf.reps:
        return "", [], "Compliance Flags has no reps — not posting a blank board"
    p, th = board.compliance_board(cf)
    return p, th, ""


def post(channel: str, parent: str, thread: List[str]) -> str:
    from automations.shared import slack_metrics_post as S
    client = S._client()
    ts = client.chat_postMessage(channel=channel, text=parent)["ts"]
    for t in thread:
        client.chat_postMessage(channel=channel, thread_ts=ts, text=t)
    return ts


def check_forwarding(*, since_days: int = 7, log=print) -> int:
    """Has each Verizon office's Credico mail reached the Hub inbox yet?

    The one proof the office's Outlook rule works -- set up on the sign-up
    form, so nobody here has to log into their mailbox. Read-only."""
    from automations.shared import email_ingest
    missing = 0
    for o in OF.all_offices():
        globs = [f"Sales Verification - Verizon Wireless - {o.office}*.xlsx",
                 f"Compliance Flags - Verizon Wireless - {o.office}*.xlsx"]
        hits = email_ingest.list_matches("", globs, since_days=since_days)
        if hits:
            newest = max(d for _fn, d in hits.values())
            log("✓ %-12s %-34s arriving (newest %s)" % (o.key, o.office, newest))
        else:
            missing += 1
            log("✗ %-12s %-34s nothing yet — their Outlook rule is not delivering" % (o.key, o.office))
    return 1 if missing else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-forwarding", action="store_true",
                    help="which Verizon offices' Credico emails are arriving (read-only)")
    ap.add_argument("--office", help="office key from offices.py (fetches from the Hub inbox)")
    ap.add_argument("--board", choices=["sales", "compliance", "both"], default="both")
    ap.add_argument("--sv", type=Path, help="local Sales Verification xlsx (preview)")
    ap.add_argument("--cf", type=Path, help="local Compliance Flags xlsx (preview)")
    ap.add_argument("--send", action="store_true", help="really post (default: preview only)")
    a = ap.parse_args(argv)
    if a.check_forwarding:
        return check_forwarding()
    today = dt.date.today()

    office = OF.get(a.office) if a.office else None
    wanted = ["sales", "compliance"] if a.board == "both" else [a.board]
    files = {}
    if a.sv:
        files["sales"] = a.sv
    if a.cf:
        files["compliance"] = a.cf
    if office:
        for w in wanted:
            files.setdefault(w, fetch(office, w))
    if not office and a.send:
        ap.error("--send needs --office")

    md = [f"# Verizon office boards — {'SENT' if a.send else 'PREVIEW (not posted)'} · {today}\n"]
    failed = 0
    for w in wanted:
        path = files.get(w)
        if not path:
            print(f"✗ {w}: no file found in the Hub inbox"); failed = 1
            continue
        parent, thread, problem = build(w, path, today if (office and w == "sales") else parse.file_date(path) or today)
        if problem:
            print(f"✗ {w}: {problem}"); failed = 1
            continue
        channel = (office.sales_channel if w == "sales" else office.compliance_channel) if office else None
        md.append(f"\n## {w}  →  {channel or '(not posted: no channel)'}\n\n**Parent:**\n\n{parent}\n\n**Thread:**\n")
        md += [f"\n{t}\n" for t in thread]
        if a.send:
            if not channel:
                print(f"– {w}: built, not posted (no channel set in offices.py)")
                continue
            ts = post(channel, parent, thread)
            print(f"✓ {w}: posted to {channel} (ts {ts})")
    out = ROOT / "output" / f"verizon_office_preview_{a.office or 'local'}_{today:%Y-%m-%d}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"(preview saved {out})")
    return failed


if __name__ == "__main__":
    sys.exit(main())
