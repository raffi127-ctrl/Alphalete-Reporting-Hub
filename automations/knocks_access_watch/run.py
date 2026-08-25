"""Watch the ownerville Office Access list and say when a captainship ICD
becomes reachable.

WHY THIS EXISTS (Eve, 2026-08-25). The knock sections of the five fiber
captainship reports run on offices the reporting account (`rhidalgo`) has
Office Access to. Sixteen of the thirty-five ICDs did not have it; Eve asked for
them and the grants arrive one at a time, over days, from someone else's
console. Her instruction was to ship the reports with the offices we already
have and "andá agregando a medida que nos otorgan acceso".

The ADDING half needs no code and no list: the knock boards are built from the
Org Sales Board roster, so the morning an office is granted, the impersonation
that used to fail simply works and that ICD appears in its captain's email on
its own. What was missing is KNOWING — nobody watches ownerville's permission
table, and a grant that lands on a Tuesday would otherwise be noticed whenever
someone happened to reopen the report.

So this job answers one question on a schedule: what changed since last time?

  * an ICD that went missing/pending -> ok is announced (it is now in the
    reports), and the count for its captainship goes up
  * an ICD that went ok -> missing is announced LOUDLY: access was revoked, or
    the office was closed, and its captain's totals just lost an office
  * nothing changed -> silent. A watcher that posts "still 19 of 35" every few
    hours trains everyone to ignore it.

READ-ONLY. It impersonates nobody, writes no Sheet, sends no mail. What it does
touch is the ownerville SESSION — one per account, and reaching the Office
Access page re-establishes it in master mode, which would corrupt a knocks
capture running at that moment. Hence the wait: the run blocks until the
ownerville modules are done, and skips (exit 0, says so) rather than barging in.

    python -m automations.knocks_access_watch.run
    python -m automations.knocks_access_watch.run --post
    python -m automations.knocks_access_watch.run --no-wait      # laptop check
    python -m automations.knocks_access_watch.run --show         # last snapshot
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.knocks_access_watch import audit as A

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "knocks_access_watch"
STATE_PATH = OUT_DIR / "state.json"

# Its own Chrome profile, like the knocks capture's: the shared one is
# first-come-first-served and this job runs unattended alongside others. Login
# still comes from the shared ownerville storage_state, so a fresh dir needs no
# seeding of its own.
PROFILE_DIR = (REPO_ROOT / "automations" / "uploaded"
               / ".browser_profile_knocks_access")

CHANNEL = "C0BK5PRG259"          # #claudecorrections-and-requests

_LABEL = {A.OK: "granted", A.PENDING: "requested, not granted",
          A.MISSING: "not on the list"}


# --------------------------------------------------------------------------
# snapshot
# --------------------------------------------------------------------------

def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no snapshot = first run, everything new
        return {}


def save_state(report: dict, when: dt.datetime) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"checked_at": when.isoformat(timespec="seconds"),
               "statuses": A.statuses(report),
               "counts": {k: list(v) for k, v in A.counts(report).items()},
               "report": report}
    STATE_PATH.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    # A dated copy too: the snapshots are how we'll answer "when did Wayne's
    # offices actually land?" without anyone having kept notes.
    (OUT_DIR / f"access_{when.date().isoformat()}.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8")


def diff(prev: Dict[str, str], now: Dict[str, str]) -> dict:
    """What moved. `gained` is the news everyone is waiting for; `lost` is the
    alarm; `added`/`dropped` are roster churn, reported separately so an owner
    who simply left a captainship never reads as revoked access."""
    gained, lost, added, dropped = [], [], [], []
    for key, status in sorted(now.items()):
        was = prev.get(key)
        if was is None:
            added.append((key, status))
        elif was != status:
            (gained if status == A.OK else lost).append((key, was, status))
    for key, was in sorted(prev.items()):
        if key not in now:
            dropped.append((key, was))
    return {"gained": gained, "lost": lost, "added": added, "dropped": dropped}


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def summary_lines(report: dict) -> List[str]:
    out = []
    for key in A.CAPTAINS:
        block = report.get(key)
        if not block:
            continue
        ok, total = A.counts(report)[key]
        gaps = [o for o in block["owners"] if o["status"] != A.OK]
        line = f"{key}: {ok}/{total} reachable"
        if gaps:
            line += " — waiting on " + ", ".join(
                f"{o['display']} ({_LABEL[o['status']]})" for o in gaps)
        out.append(line)
    return out


def change_text(d: dict, report: dict) -> Optional[str]:
    """The Slack message, or None when nothing worth saying happened."""
    if not (d["gained"] or d["lost"]):
        return None
    ok = sum(c[0] for c in A.counts(report).values())
    total = sum(c[1] for c in A.counts(report).values())
    parts = []
    if d["gained"]:
        parts.append("*Office Access granted* — these ICDs are now in their "
                     "captainship's knock boards:\n"
                     + "\n".join(f"• {k}" for k, _w, _s in d["gained"]))
    if d["lost"]:
        parts.append("*:rotating_light: Office Access LOST* — these ICDs "
                     "dropped out of the knock boards:\n"
                     + "\n".join(f"• {k} ({_LABEL.get(s, s)})"
                                 for k, _w, s in d["lost"]))
    parts.append(f"Captainship knock coverage is now *{ok} of {total}* ICDs.")
    if ok == total:
        parts.append(":white_check_mark: Every captainship ICD is reachable — "
                     "the summary boards no longer carry the "
                     "\"(N of M ICDs)\" caveat.")
    return "\n\n".join(parts)


def post(text: str, *, dry_run: bool) -> bool:
    """Post to the corrections channel. Refuses from Windows: that machine's
    Slack token is Evelyn's personal account, not Lucy, and everything in this
    channel has to read as Lucy — a post signed by a person looks like a human
    request, not a report. Run it on the mini to post."""
    if dry_run:
        print("\n--- would post to Slack -----------------------------")
        print(text)
        print("-----------------------------------------------------")
        return True
    if platform.system() == "Windows":
        print("\n! not posting from Windows (the token here is Evelyn, not "
              "Lucy). Run this on the mini to post:")
        print("  lucy rerun knocks_access_watch --machine \"Lucy 1\"")
        print(text)
        return False
    from automations.shared import slack_metrics_post as smp
    smp._client().chat_postMessage(channel=CHANNEL, text=text)
    print("  ✓ posted to #claudecorrections-and-requests")
    return True


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def _wait_for_session(logfn=print) -> bool:
    """True when the ownerville session is ours to take. See the module
    docstring: reaching p=901 re-establishes the account's single session in
    master mode, so a capture that is mid-impersonation would start scraping
    the wrong office. Waiting is the whole safety story here."""
    from automations.knocks_request.service import wait_for_ownerville
    return wait_for_ownerville(logfn=logfn)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="Post to #claudecorrections-and-requests when "
                         "something CHANGED (silent otherwise).")
    ap.add_argument("--dry-run", action="store_true",
                    help="With --post: print the message instead of sending.")
    ap.add_argument("--no-wait", action="store_true",
                    help="Don't wait for other ownerville jobs. For a hand "
                         "run on a laptop only — never on the mini.")
    ap.add_argument("--show", action="store_true",
                    help="Print the last snapshot and exit. Opens nothing.")
    args = ap.parse_args(argv)

    if args.show:
        state = load_state()
        if not state:
            print("no snapshot yet — run it once without --show")
            return 0
        print(f"last checked: {state.get('checked_at')}")
        for line in summary_lines(state.get("report") or {}):
            print("  " + line)
        return 0

    if not args.no_wait and not _wait_for_session():
        # Not a failure: the capture is still working and this job is a
        # nicety. Exit 0 so the orchestrator doesn't paint a red card over a
        # deliberate yield (the dead-source rule — ping, don't fail).
        print("ownerville is busy with the knock pulls — skipping this pass; "
              "the next one picks it up")
        return 0

    from automations.shared.tableau_patchright import ownerville_session
    print("reading Office Access on the reporting account (read-only)…")
    with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
        data = A.audit(page)
    report = data["report"]
    now = dt.datetime.now()

    prev = load_state()
    d = diff(prev.get("statuses") or {}, A.statuses(report))
    print(f"\n{len(data['offices'])} office(s) on the access list")
    for line in summary_lines(report):
        print("  " + line)

    if d["gained"]:
        print("\n  NEW ACCESS since the last check:")
        for key, was, _s in d["gained"]:
            print(f"    + {key}  (was: {_LABEL.get(was, was)})")
    if d["lost"]:
        print("\n  ACCESS LOST since the last check:")
        for key, _w, status in d["lost"]:
            print(f"    - {key}  (now: {_LABEL.get(status, status)})")
    if d["added"]:
        print(f"\n  {len(d['added'])} owner(s) new to a roster (not an access "
              "change):")
        for key, status in d["added"]:
            print(f"    · {key} — {_LABEL.get(status, status)}")
    if d["dropped"]:
        print(f"\n  {len(d['dropped'])} owner(s) no longer on a roster")
    if not prev:
        print("\n  (first run — recorded as the baseline, nothing announced)")

    save_state(report, now)

    if args.post and prev:
        text = change_text(d, report)
        if text:
            post(text, dry_run=args.dry_run)
        else:
            print("\nnothing changed — staying quiet")

    print("\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
