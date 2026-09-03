"""Which offices on the access list run MORE THAN ONE campaign — the ones that
cannot be enrolled for dispositions yet.

WHY IT MATTERS BEFORE THE LINK GOES OUT. An ICD running several campaigns cannot
be pinned: OwnerVille's top-right picker defaults for it and invD2DClientId does
not move it (Megan, 2026-09-02). So its board comes back holding another
campaign's reps, and `assert_campaign_grid` refuses to publish it. Such an owner
can fill the sign-up form and get all the way to Megan's confirm before being
told no. Knowing who they are first turns that into "not you yet, here's why".

HOW IT COUNTS. Impersonate the office, load an UNPINNED p=89, and read the
distinct invD2DClientId values off the page's own links — the picker's entries
are links, so the distinct ids ARE this office's campaigns. It must be unpinned:
an id in the URL floods the links and the scan starts answering "what did I just
ask for". Verified 2026-09-02: Isaiah {1}, Roshan {16}, Carlos {2,16,39}.

IT MUST NOT COST RAF HIS BOARDS. ownerville allows ONE session per account, and
the gap_alerts tick shares it. So this takes that job's pid lock ONE OFFICE AT A
TIME and lets go in between, rather than holding it for the whole run — a tick
that wants the session waits seconds, not half an hour. `--after-hours` refuses
to start at all while any office is inside its selling window, which is the
setting to use for the full 90.

    python -m automations.disposition_signup.campaign_scan --after-hours
    python -m automations.disposition_signup.campaign_scan --only "Jay Turnage"
    python -m automations.disposition_signup.campaign_scan --limit 5

Read-only: it impersonates, reads, and exits impersonation. Nothing is written
to OwnerVille, no Sheet, no Slack.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

OUT_DIR = Path(__file__).resolve().parents[2] / "output"


def _log(msg: str) -> None:
    print("[campaign-scan] %s" % msg, flush=True)


def _lock_for_one_office(seconds: int = 90):
    """gap_alerts' pid lock, held for ONE office. None if it never came free.

    Per office, not per run: the whole point is that a tick wanting the session
    waits for one office's read, not for ninety.
    """
    from automations.gap_alerts.run import Lock
    deadline = time.time() + seconds
    while True:
        lock = Lock()
        lock.__enter__()
        if lock.held:
            return lock
        lock.__exit__()
        if time.time() >= deadline:
            return None
        time.sleep(5)


def scan_office(page, name: str) -> Dict:
    """{name, campaigns:[{id,label}], note} for one office."""
    from automations.disposition_signup import resolve_office as RO
    from automations.focus_office_att.aliases import load_aliases
    from automations.focus_office_att.run_all_owners import (
        _find_owner_and_impersonate, _exit_impersonation)
    from automations.focus_office_att.step5_fill_one_owner import page_rqst
    from automations.knocks_access_watch.audit import read_office_access

    read_office_access(page)          # leaves the page on the access table
    rqst, why = _find_owner_and_impersonate(page, name, load_aliases())
    if not rqst:
        return {"name": name, "campaigns": [], "note": "not impersonated: %s" % why}
    try:
        rqst = page_rqst(page) or rqst
        # NO invD2DClientId — see the module docstring.
        page.goto("https://v2.ownerville.com/index.cfm?p=89&rqst=%s" % rqst,
                  wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2000)
        return {"name": name, "campaigns": RO.read_campaigns(page), "note": ""}
    finally:
        _exit_impersonation(page)


def targets(only: str = "", limit: int = 0) -> "List[str]":
    """Owner names to scan, off the access list. Only GRANTED rows: a pending
    request cannot be impersonated, so it has nothing to tell us yet."""
    from automations.shared.tableau_patchright import ownerville_session
    from automations.gap_alerts import config as C
    from automations.knocks_access_watch.audit import read_office_access
    from automations.disposition_signup import resolve_office as RO

    lock = _lock_for_one_office()
    try:
        with ownerville_session(headless=True, verbose=False,
                                profile_dir=str(C.PROFILE_DIR)) as page:
            rows = read_office_access(page)
    finally:
        if lock is not None:
            lock.__exit__()
    out = []
    for r in rows:
        if RO.access_state(r) != RO.GRANTED:
            continue
        owner = RO.owner_of(r)
        if not owner:
            continue
        if only and only.strip().lower() not in owner.lower():
            continue
        out.append(owner)
    return out[:limit] if limit else out


def run(*, only: str = "", limit: int = 0, after_hours: bool = False) -> int:
    from automations.gap_alerts import config as C
    from automations.shared.tableau_patchright import ownerville_session

    if after_hours and C.any_office_in_window():
        _log("an office is still inside its selling window — refusing to start. "
             "This is the flag that keeps a 90-office scan off Raf's session; "
             "drop it to run anyway.")
        return 2

    names = targets(only, limit)
    _log("%d granted office(s) to scan" % len(names))
    results: List[Dict] = []
    for i, name in enumerate(names, 1):
        lock = _lock_for_one_office()
        if lock is None:
            _log("%3d/%d %-28s SKIPPED — the tick held the session"
                 % (i, len(names), name[:28]))
            results.append({"name": name, "campaigns": [],
                            "note": "session busy"})
            continue
        try:
            with ownerville_session(headless=True, verbose=False,
                                    profile_dir=str(C.PROFILE_DIR)) as page:
                res = scan_office(page, name)
        except Exception as e:                       # noqa: BLE001 — one office
            res = {"name": name, "campaigns": [],
                   "note": "%s: %s" % (type(e).__name__, str(e)[:120])}
        finally:
            lock.__exit__()
        n = len(res["campaigns"])
        _log("%3d/%d %-28s %s" % (i, len(names), name[:28],
                                  ("%d campaign(s): %s" % (n, ", ".join(
                                      "%s (%s)" % (c["label"] or "?", c["id"])
                                      for c in res["campaigns"])))
                                  if n else (res["note"] or "no campaigns read")))
        results.append(res)
    return report(results)


def report(results: "List[Dict]") -> int:
    multi = [r for r in results if len(r["campaigns"]) > 1]
    single = [r for r in results if len(r["campaigns"]) == 1]
    unknown = [r for r in results if not r["campaigns"]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    path = OUT_DIR / ("disposition-campaign-scan-%s.md" % stamp)
    lines = ["# Offices by campaign count — %s" % stamp, "",
             "An office running MORE THAN ONE campaign cannot be enrolled for "
             "dispositions yet: the picker defaults and the pin cannot move it.",
             "", "## CANNOT ENROLL YET — %d" % len(multi), ""]
    for r in sorted(multi, key=lambda x: x["name"]):
        lines.append("- **%s** — %s" % (r["name"], ", ".join(
            "%s (%s)" % (c["label"] or "?", c["id"]) for c in r["campaigns"])))
    lines += ["", "## Servable — %d" % len(single), ""]
    for r in sorted(single, key=lambda x: x["name"]):
        c = r["campaigns"][0]
        lines.append("- %s — %s (%s)" % (r["name"], c["label"] or "?", c["id"]))
    if unknown:
        lines += ["", "## Could not read — %d" % len(unknown), ""]
        for r in sorted(unknown, key=lambda x: x["name"]):
            lines.append("- %s — %s" % (r["name"], r["note"] or "?"))
    path.write_text("\n".join(lines) + "\n")
    (OUT_DIR / ("disposition-campaign-scan-%s.json" % stamp)).write_text(
        json.dumps(results, indent=2))
    _log("")
    _log("CANNOT ENROLL YET: %d · servable: %d · unread: %d"
         % (len(multi), len(single), len(unknown)))
    for r in sorted(multi, key=lambda x: x["name"]):
        _log("  x %s — %s" % (r["name"], ", ".join(
            "%s (%s)" % (c["label"] or "?", c["id"]) for c in r["campaigns"])))
    _log("wrote %s" % path)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="disposition_signup.campaign_scan")
    ap.add_argument("--only", default="", help="substring of one owner's name")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--after-hours", action="store_true",
                    help="refuse to start while any office is still selling")
    args = ap.parse_args(argv)
    return run(only=args.only, limit=args.limit, after_hours=args.after_hours)


if __name__ == "__main__":
    sys.exit(main())
