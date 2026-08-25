"""Morning safety-net: flag enrollments that are sitting in the 'Office
Onboarding' sheet but haven't been applied to the report wiring yet.

Section EDITS (Thread Builder) go live automatically each morning, but a brand-new
OFFICE enrollment still needs a reviewed `office_onboarding.apply --write` +
commit (it rewrites the committed registry + schedule — deliberately gated, not
auto-pushed at 4am). This step makes sure a pending enrollment is never forgotten:
it posts to the corrections channel with the list + how to apply.

    python -m automations.office_onboarding.pending_alert            # post if pending
    python -m automations.office_onboarding.pending_alert --dry-run  # print only

Best-effort: no Sheets creds / a read error → no-op, exit 0 (never blocks the flow).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Tuple


def _client():
    try:
        from automations.recruiting_report.fill import _client as c
        return c()
    except Exception as e:  # noqa: BLE001
        print("[pending_alert] no Sheets client ({}: {})".format(
            type(e).__name__, e), file=sys.stderr)
        return None


def _applied_keys() -> set:
    from automations.office_onboarding import apply
    keys = set()
    for path in apply.ONBOARDED_JSON.values():
        if path.exists():
            try:
                keys |= {r["key"] for r in json.loads(path.read_text())}
            except Exception:  # noqa: BLE001
                pass
    return keys


def pending() -> Tuple[List[dict], List[dict]]:
    """(ready, blocked) enrollments not yet in the applied registry. `ready` pass
    validation and can be applied now; `blocked` have problems to fix first.
    Empty when the sheet can't be read (best-effort)."""
    from automations.office_onboarding import store, apply
    gc = _client()
    if gc is None:
        return [], []
    store.set_client(gc)
    try:
        plans = apply.plan()
    except Exception as e:  # noqa: BLE001
        print("[pending_alert] plan() failed ({}: {})".format(
            type(e).__name__, e), file=sys.stderr)
        return [], []
    applied = _applied_keys()
    ready, blocked = [], []
    for p in plans:
        if p["rec"].key in applied:
            continue
        (blocked if p["problems"] else ready).append(p)
    return ready, blocked


def _log_run(started_at) -> None:
    """One Hub Activity row per run — even (especially) the quiet ones.

    Standing rule: LaunchAgent reports publish to the Hub. Until 2026-08-21 this
    module never logged, so after the check moved off the 4am pass to the hourly
    agent (2026-08-19) the Activity log went silent, machine_digest kept judging
    it by the old mini-4am baseline, and the morning of 2026-08-21 opened a
    "didn't run today" incident for an agent that was installed and healthy.
    A quiet run logging `success` is exactly what tells the watcher it's alive.
    Skipped under the orchestrator (HUB_REPORT_ID set): the pill row is its job.

    Logs to the merged "Office Onboarding" CARD id, not this module's scheduler
    handle (Megan 2026-08-25: onboarding is one card). hub_activity keys on the
    CARD id and self-registers a library card for an id it doesn't know, so
    logging `enrollment_pending_check` now would rebuild the very duplicate the
    merge removed."""
    import os
    if os.environ.get("HUB_REPORT_ID"):
        return
    try:
        from automations.shared import hub_activity
        from automations.shared import onboarding_surfaces as _os
        hub_activity.log_completed(_os.CARD_ID, "Office Onboarding",
                                   status="success", started_at=started_at)
    except Exception as e:  # noqa: BLE001 — reporting never sinks the check
        print("[pending_alert] activity log skipped ({}: {})".format(
            type(e).__name__, e), file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="office_onboarding.pending_alert")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be posted, don't post")
    args = ap.parse_args(argv)

    import datetime as dt
    started_at = dt.datetime.now()
    ready, blocked = pending()
    if not args.dry_run:
        _log_run(started_at)
    if not ready and not blocked:
        print("[pending_alert] no pending enrollments.")
        return 0

    def _line(p):
        r = p["rec"]
        return "• *{}* → {} [{} / {}]".format(
            r.key, r.channel_name, r.family.upper(), r.machine())

    n = len(ready) + len(blocked)
    title = ":envelope_with_arrow: *{} enrollment{} waiting to go live*".format(
        n, "" if n == 1 else "s")
    body = []
    if ready:
        body.append("*Ready to apply:*")
        body += [_line(p) for p in ready]
        body.append("")
        body.append("*To apply:* `lucy rerun apply_enrollments` (or run it from "
                    "the Hub), then review `git diff` and commit + push.")
    if blocked:
        body.append("")
        body.append("*Need a fix first (validation problems):*")
        for p in blocked:
            body.append(_line(p))
            body += ["    - {}".format(pr) for pr in p["problems"]]

    if args.dry_run:
        print(title)
        print("\n".join(body))
        return 0

    try:
        from automations.day_orchestrator import registry, notify
        cfg = registry.load_config()
        notify._post_corrections(cfg, title, body, False, tag="pending-enrollments")
        print("[pending_alert] posted {} pending enrollment(s).".format(n))
    except Exception as e:  # noqa: BLE001 — alerting must never crash the flow
        print("[pending_alert] post failed ({}: {}) — listing here instead:\n{}\n{}"
              .format(type(e).__name__, e, title, "\n".join(body)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
