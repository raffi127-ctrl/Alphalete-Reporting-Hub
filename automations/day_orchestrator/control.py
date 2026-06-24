"""Stop/resume control — a phone-friendly way to drop a stuck report from the
retry loop so a human can go fix the data/source manually.

Core mechanism: a control file (output/day_state/<date>.control.json) the
orchestrator reads at the top of every pass. Two front-ends write it:

  1. One-line command (terminal / SSH):
       python -m automations.day_orchestrator.control stop  country_metrics
       python -m automations.day_orchestrator.control resume country_metrics
       python -m automations.day_orchestrator.control list

  2. Gmail reply (phone): reply to the checkpoint email with subject
       STOP <report_id>     or     RESUME <report_id>
     The orchestrator polls a narrow Gmail query each pass (poll_email_controls),
     writes the same control file, and marks the message read so it acts once.

Effect: `stop` → the loop drops the report and marks it HALTED_FOR_FIX (terminal
for the day; `resume` puts it back to PENDING). Halting NEVER touches the sheet —
it only stops *retrying*. Unknown ids are ignored and reported.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from typing import List

from automations.day_orchestrator import state as st


# ---------------- applied by the loop each pass ----------------

def apply_control(ds, date: str) -> List[str]:
    """Read the control file and apply stop/resume to the day-state. Returns a
    list of human-readable change strings (for the log). Consumes each directive
    (clears it from the file) so it isn't re-applied every pass."""
    mapping = st.read_control(date)
    if not mapping:
        return []
    changes: List[str] = []
    for rid, action in mapping.items():
        if rid not in ds.reports:
            changes.append(f"ignored unknown report id {rid!r}")
            continue
        rs = ds.reports[rid]
        if action == "stop":
            if rs.status != st.HALTED_FOR_FIX:
                ds.set(rid, st.HALTED_FOR_FIX, reason="manually halted for fix")
                changes.append(f"{rid} → HALTED_FOR_FIX")
        elif action == "resume":
            if rs.status == st.HALTED_FOR_FIX:
                ds.set(rid, st.PENDING, reason="resumed by user")
                changes.append(f"{rid} → resumed (PENDING)")
        else:
            changes.append(f"ignored unknown action {action!r} for {rid}")
    # Directives are one-shot; clear the file after applying them all.
    st.write_control(date, {})
    return changes


def _set(date: str, report_id: str, action: str) -> None:
    mapping = st.read_control(date)
    mapping[report_id] = action
    st.write_control(date, mapping)


# ---------------- Gmail-reply poller (phone path, 4b) ----------------

def poll_email_controls(date: str, *, verbose: bool = False) -> List[str]:
    """Poll the reporting mailbox for unread STOP/RESUME replies and write them
    to the control file. Best-effort: any auth/API hiccup is swallowed (returns
    []), so the loop is never blocked by the mailbox.

    Matches unread messages whose Subject starts 'STOP ' or 'RESUME ' followed by
    a report id. Marks each handled message read so it acts exactly once.
    """
    found: List[str] = []
    try:
        from automations.shared.gmail_auth import load_credentials
        from googleapiclient.discovery import build
        creds = load_credentials()
        svc = build("gmail", "v1", credentials=creds)
        q = 'is:unread (subject:"STOP " OR subject:"RESUME ")'
        resp = svc.users().messages().list(userId="me", q=q, maxResults=25).execute()
        for m in resp.get("messages", []):
            full = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["Subject"]).execute()
            subj = ""
            for h in full.get("payload", {}).get("headers", []):
                if h.get("name", "").lower() == "subject":
                    subj = h.get("value", "")
                    break
            action, rid = _parse_subject(subj)
            if action and rid:
                _set(date, rid, action)
                found.append(f"{action} {rid} (from email)")
                # mark read so we don't act twice
                svc.users().messages().modify(
                    userId="me", id=m["id"],
                    body={"removeLabelIds": ["UNREAD"]}).execute()
    except Exception as e:
        if verbose:
            print(f"[control] email poll skipped: {e}", flush=True)
        return found
    return found


def _parse_subject(subject: str):
    """('stop'|'resume', report_id) or (None, None). Tolerant of 'Re: ' prefixes."""
    s = (subject or "").strip()
    low = s.lower()
    while low.startswith("re:") or low.startswith("fwd:"):
        s = s.split(":", 1)[1].strip()
        low = s.lower()
    parts = s.split()
    if len(parts) >= 2 and parts[0].lower() in ("stop", "resume"):
        return parts[0].lower(), parts[1].strip()
    return None, None


# ---------------- one-line CLI (terminal path, 4a) ----------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Stop/resume a report in today's run.")
    ap.add_argument("action", choices=["stop", "resume", "list"])
    ap.add_argument("report_id", nargs="?")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    args = ap.parse_args(argv)

    if args.action == "list":
        m = st.read_control(args.date)
        if not m:
            print(f"No pending controls for {args.date}.")
        else:
            for rid, act in m.items():
                print(f"  {act:6s} {rid}")
        return 0

    if not args.report_id:
        ap.error("report_id is required for stop/resume")
    _set(args.date, args.report_id, args.action)
    print(f"Queued: {args.action} {args.report_id} (date {args.date}). "
          f"The orchestrator applies it on its next pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
