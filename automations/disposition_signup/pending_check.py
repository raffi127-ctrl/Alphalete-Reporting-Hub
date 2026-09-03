"""Retry the preflight for offices that are wired but not switched on yet.

THE GAP THIS CLOSES. A confirmed sign-up is wired `enabled=false` and the
runner's preflight decides whether to switch it on. But the thing preflight is
usually waiting for is not ours: Office Access has to be accepted by the OWNER,
in their own OwnerVille dashboard and inbox, which happens minutes — or days —
after they fill the form. Until this existed, that first preflight was the ONLY
one: it ran at confirm, found "Request Sent", and the office sat off forever
while everybody involved believed it was enrolled. Megan had to remember to
re-run it, which is exactly the remembering the sign-up link exists to delete.

So this re-checks them on a schedule and switches on the ones that have come
good. It is the thing that makes preflight's "this retries on its own" true
rather than a promise ([[feedback_reminders_are_scheduled_tasks]]).

QUIET BY DEFAULT. It posts on a CHANGE of state, never on every pass — an
office waiting three days on an owner's inbox would otherwise be 72 identical
corrections posts, and a channel that cries every hour is one nobody reads
([[feedback_never_post_blank]] is the same instinct).

CHEAP WHEN THERE IS NOTHING TO DO. No sign-ups waiting means no browser, no
OwnerVille session, no lock — it returns before any of that, which is what lets
it run hourly next to the ticks.

    python -m automations.disposition_signup.pending_check
    python -m automations.disposition_signup.pending_check --dry-run
    python -m automations.disposition_signup.pending_check --only cody

Best-effort throughout: no Sheets creds, a read error, a dead session — all
no-op and exit 0. This is a safety net, and a safety net must never be the
thing that breaks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

STATE_PATH = (Path.home() / ".config" / "recruiting-report"
              / "disposition_pending_state.json")


def _client():
    try:
        from automations.recruiting_report.fill import _client as c
        return c()
    except Exception as e:                           # noqa: BLE001
        print("[pending_check] no Sheets client (%s: %s)"
              % (type(e).__name__, e), file=sys.stderr)
        return None


def _state() -> Dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:                                # noqa: BLE001
        return {}


def _save_state(data: Dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(data, indent=2))
    except OSError as e:
        print("[pending_check] couldn't save state: %s" % e, file=sys.stderr)


def waiting(only: str = "") -> "List":
    """Every confirmed office that is still switched off, as records.

    `status == "wired"` and `enabled` false is the exact state preflight leaves
    an office in when a check did not pass. A PENDING row is not ours — Megan
    has not confirmed it — and an enabled one is already live.
    """
    from automations.disposition_signup import store
    from automations.disposition_signup.schema import campaign_live
    out = []
    for d in store.load_all():
        rec = store.record_from_json(d)
        if rec.status != "wired" or rec.enabled:
            continue
        if only and rec.key != only:
            continue
        # A waiting-list campaign has nothing to pull, so a preflight would
        # burn a browser session to fail on something no retry can fix.
        if not campaign_live(rec.campaign_key):
            continue
        out.append(rec)
    return out


def _outcome(res: Dict) -> str:
    """One word for what this pass found, and the thing state is keyed on."""
    if res.get("ok"):
        return "ready"
    if res.get("retry"):
        # Which retryable reason, so "the owner finally accepted, but now the
        # chat is missing" is a change worth saying rather than more silence.
        for c in res.get("checks") or []:
            if c.get("state"):
                return "waiting:%s" % c["state"]
        return "waiting"
    return "failed"


def run(*, dry_run: bool = False, only: str = "") -> int:
    from automations.disposition_signup import preflight as P, store

    gc = _client()
    if gc is None:
        return 0
    store.set_client(gc)
    try:
        recs = waiting(only)
    except Exception as e:                           # noqa: BLE001
        print("[pending_check] couldn't read the sign-up tab (%s: %s)"
              % (type(e).__name__, e), file=sys.stderr)
        return 0
    if not recs:
        print("[pending_check] nothing waiting to be switched on")
        return 0

    state = _state()
    print("[pending_check] %d office(s) waiting: %s"
          % (len(recs), ", ".join(r.key for r in recs)))
    for rec in recs:
        if dry_run:
            print("  %s — would re-run the preflight" % rec.key)
            continue
        try:
            res = P.check(rec.key)
        except Exception as e:                       # noqa: BLE001
            print("  %s — preflight raised (%s: %s)"
                  % (rec.key, type(e).__name__, str(e)[:180]), file=sys.stderr)
            continue
        now = _outcome(res)
        was = state.get(rec.key)
        print("  %s — %s%s" % (rec.key, now,
                               "" if was == now else " (was %s)" % (was or "new")))
        turned_on = False
        if res["ok"] and res.get("rec") is not None:
            # The whole point of the pass. enable() re-materializes the office,
            # so the next tick has it.
            P.enable(res["rec"])
            turned_on = True
        # SAY IT ONLY WHEN IT CHANGED. An office waiting on its owner's inbox
        # for three days is one post, not seventy-two.
        if turned_on or was != now:
            P.notify(rec.key, res, enabled=turned_on)
        state[rec.key] = now
        if turned_on:
            # It is live; stop tracking it so a later re-confirm starts clean.
            state.pop(rec.key, None)
    if not dry_run:
        _save_state(state)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="disposition_signup.pending_check")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be re-checked, open nothing")
    ap.add_argument("--only", default="", help="one office key")
    args = ap.parse_args(argv)
    return run(dry_run=args.dry_run, only=args.only)


if __name__ == "__main__":
    sys.exit(main())
