"""Self-registering Hub visibility — every automation that RUNS gets a card + a
green pill, with no hand-maintenance.

The problem (Megan 2026-07-27): two silent gaps meant reports ran invisibly.
  1. The pill only greened if a report_id was in hub_publish._HUB_CARD, a
     hand-typed map. 61 scheduler entries weren't in it — incl. P1 boards — so
     they ran fine but their card stayed grey forever.
  2. A NEW automation (Eve pushes one to Lucy 1/2) created NO Hub card at all.
     It ran with zero visibility on Megan's Hub.

Both share one root cause: a new report had to be wired by hand in three places
(schedule_config -> _HUB_CARD -> a Hub card). This module removes the hand-work:

  resolve_card(report_id, name) does, in order:
    1. hub_publish._HUB_CARD          — curated mapping (kept for the id
                                        mismatches slug can't derive)
    2. CURATED_ALIAS                  — dup-guards (a report whose card exists
                                        under an unrelated id, e.g. texas_de_brazil
                                        -> the monthly-competition library card)
    3. slug(report_id) IF that id is already a card  — the common case: the card
                                        exists, it just wasn't wired
    4. auto-create a Report Library card for slug(report_id), then use it

Internal machinery (installers, pollers, sub-steps) is SKIPPED — it never needs a
user-facing card. Everything else becomes visible the first time it runs.

Report Library is the shared uploads path (already open to everyone, Megan
2026-05-29) — writing a row here never touches dashboard.AUTOMATED_REPORTS, which
Megan owns. Card SCHEMA/layout is hers; a library row is the sanctioned way in.

Read-only until asked to write:
  python -m automations.day_orchestrator.hub_coverage --audit          # show gaps
  python -m automations.day_orchestrator.hub_coverage --sync --dry-run # what WOULD be created
  python -m automations.day_orchestrator.hub_coverage --sync           # create the missing cards
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PY = REPO_ROOT / "automations" / "dashboard.py"
CONFIG_PATH = Path(__file__).resolve().parent / "schedule_config.json"

# Mirror of dashboard.SHARED_LIBRARY_* (not imported — importing dashboard pulls
# Streamlit, which the mini can't load; hub_activity.py makes the same choice).
SHARED_LIBRARY_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
SHARED_LIBRARY_TAB = "Report Library"
SHARED_LIBRARY_HEADERS = ["ID", "Name", "Module", "Created By", "Created At",
                          "Metadata", "Script"]

# Reports that must NEVER get a user-facing card: installers, one-shot utilities,
# pollers, and the *_slack / *_post / *_send sub-steps that publish under their
# parent report's card. Matched against the schedule_config report_id.
_SKIP_RE = re.compile(
    r"^(install_|uninstall_"
    r"|kick_poller|morning_diag|set_wake|probe_readiness|opt_phase"
    r"|send_email_preview|schedule_audit|tableau_preview|sunday_coverage"
    r"|rebuild_lastweek|drb_backfill_lastweek|drb_tableau_pull|drb_fill_owner"
    r"|recruiting_backfill_juan|vantura_board_audit|applicant_clear_session"
    r"|harvest_prime"                       # churn-cache warm — internal, not a report
    r"|dd_headshots_sync|dd_special_accumulate"  # DD sub-steps under dd-bulletin
    r").*|.*(_slack|_post|_send|_finalize)$")

# Reports whose card already exists under an id slug() can't derive — map by hand
# so we reuse the real card instead of auto-creating a duplicate. The --audit
# surfaces any new report that needs an entry here.
CURATED_ALIAS = {
    "texas_de_brazil": "june_texas_de_brazil_monthly_competition",
}


def slug(report_id: str) -> str:
    """Orchestrator report_id -> Hub card-id convention (underscores -> hyphens)."""
    return report_id.replace("_", "-").strip("-")


def is_internal(report_id: str) -> bool:
    return bool(_SKIP_RE.match(report_id))


# ---------------------------------------------------------------- card inventory
def _hardcoded_card_ids() -> Set[str]:
    """Card ids baked into dashboard.AUTOMATED_REPORTS — read by regex so we never
    import Streamlit. Stable format: `"id": "kebab-case"`."""
    try:
        text = DASHBOARD_PY.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return set()
    return set(re.findall(r'"id":\s*"([a-z0-9_-]+)"', text))


def _library_ws():
    from automations.recruiting_report.fill import open_by_key
    import gspread as _gs
    sh = open_by_key(SHARED_LIBRARY_SHEET_ID)
    try:
        return sh.worksheet(SHARED_LIBRARY_TAB)
    except _gs.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHARED_LIBRARY_TAB, rows=200,
                              cols=len(SHARED_LIBRARY_HEADERS))
        ws.update([SHARED_LIBRARY_HEADERS], "A1:G1")
        return ws


def _library_card_ids() -> Set[str]:
    try:
        recs = _library_ws().get_all_records()
    except Exception:
        return set()
    return {str(r.get("ID", "")).strip() for r in recs if str(r.get("ID", "")).strip()}


def existing_card_ids() -> Set[str]:
    """Every id the Hub renders a card for: hardcoded + shared library."""
    return _hardcoded_card_ids() | _library_card_ids()


# ------------------------------------------------------------------- resolution
def _curated_map() -> Dict[str, str]:
    """hub_publish._HUB_CARD, read without importing the module's gspread deps."""
    try:
        src = (Path(__file__).resolve().parent / "hub_publish.py").read_text(
            encoding="utf-8", errors="replace")
        m = re.search(r"_HUB_CARD\s*=\s*\{(.*?)\n\}", src, re.S)
        if not m:
            return {}
        return dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', m.group(1)))
    except Exception:
        return {}


def resolve_card(report_id: str, report_name: str = "", *,
                 module: Optional[str] = None, create: bool = True,
                 dry_run: bool = False,
                 _existing: Optional[Set[str]] = None) -> Optional[str]:
    """Return the Hub card id for a report, creating a library card if needed.

    None means "no card and none should exist" (internal machinery, or create
    was suppressed and nothing matched). Best-effort: any write failure returns
    the resolved id anyway so the caller can still log the run — a missing card
    is better than a crashed report.
    """
    if is_internal(report_id):
        return None
    curated = _curated_map()
    if report_id in curated:
        return curated[report_id]
    if report_id in CURATED_ALIAS:
        return CURATED_ALIAS[report_id]
    existing = _existing if _existing is not None else existing_card_ids()
    # Match an existing card in EITHER convention: hardcoded cards are hyphenated
    # (country-sales-board), library cards keep the underscore report_id (car_rides).
    if slug(report_id) in existing:
        return slug(report_id)
    if report_id in existing:
        return report_id
    if not create:
        return None
    ok, _msg = ensure_library_card(report_id, report_name or report_id,
                                   module=module, dry_run=dry_run)
    # The created library card's id is the underscore report_id (so its
    # materialized script module `automations.uploaded._shared.<id>` is import-
    # valid — a hyphen there would be an illegal module name).
    return report_id


def _launcher_script(cid: str, real_module: Optional[str],
                     base_args: List[str]) -> str:
    """A runnable script for an auto-created library card. The Hub runs a library
    card via `python -m automations.uploaded._shared.<id>`, so this delegates to
    the report's real (git-tracked) module — the card is both visible AND runs the
    same thing the scheduler does. A row with an EMPTY script is silently dropped
    by dashboard._read_shared_library_rows, so this must never be empty."""
    if not real_module:
        return ('"""Auto-registered Hub card for %s.\n'
                'This report runs on schedule (Lucy mini); no manual module was '
                'found to wire a Run button to. Edit this card to add one."""\n'
                'print("Scheduled report %s — runs automatically on the mini.")\n'
                % (cid, cid))
    argv = [real_module] + [str(a) for a in (base_args or [])]
    return ('"""Auto-registered Hub launcher for %s -> %s.\n'
            'Created by hub_coverage so a scheduled report is visible + runnable\n'
            'on the Hub. Replace with a richer card any time."""\n'
            'import runpy, sys\n'
            'sys.argv = %r\n'
            'runpy.run_module(%r, run_name="__main__")\n'
            % (cid, real_module, argv, real_module))


def _schedule_meta(weekdays: List[int], est_minutes: Optional[int]) -> dict:
    """Build the `schedule` block the Hub reads for calendar days + the time chip.
    Orchestrator reports don't run at a fixed clock time — they run in the 4 AM
    flow once their data is ready — so the time label says exactly that rather
    than inventing a precise minute. Empty weekdays => on-demand (no calendar)."""
    if not weekdays:
        sched = {"frequency": "on-demand", "time": "On-demand"}
    elif len(weekdays) >= 7:
        sched = {"frequency": "daily", "time": "4 AM flow (when data's ready)"}
    else:
        sched = {"frequency": "weekly", "weekdays": weekdays,
                 "time": "4 AM flow (when data's ready)"}
    if est_minutes:
        sched["estimated_minutes"] = est_minutes
    return sched


def ensure_library_card(report_id: str, report_name: str, *,
                        module: Optional[str] = None,
                        dry_run: bool = False) -> Tuple[bool, str]:
    """Create a Report Library card for a report that has none. Idempotent —
    keyed by the underscore report_id, so a second call updates in place, never
    dupes. Auto-created cards carry a delegating launcher script (so they render
    and run) and are tagged so Megan can rename / curate them later. Looks up the
    real module + base_args from schedule_config when not passed."""
    cid = report_id  # underscore id -> valid materialized-module filename
    real_module, base_args = module, []  # type: Optional[str], List[str]
    name = report_name
    machine, weekdays, est = "Lucy 1", [], None
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        r = cfg.get("reports", {}).get(report_id, {})
        real_module = real_module or (r.get("command") or [None])[0]
        base_args = list(r.get("base_args", []) or [])
        name = name or r.get("display_name") or report_id.replace("_", " ").title()
        # Profile + schedule so the card lands under the right runner, on the
        # right days, with a time chip — same fields the hardcoded cards use.
        machine = r.get("machine") or "Lucy 1"
        weekdays = list(r.get("cadence", {}).get("weekdays", []) or [])
        est = r.get("timeout_minutes")
    except Exception:
        name = name or report_id.replace("_", " ").title()
    script = _launcher_script(cid, real_module, base_args)
    schedule = _schedule_meta(weekdays, est)
    meta = {
        "id": cid,
        "name": name,
        "module": real_module or "",
        "args": base_args,
        "creator": "Auto (self-registered)",
        "auto_registered": True,
        "auto_registered_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source_report_id": report_id,
        "emoji": "🗂",
        "description": ("Auto-registered from a scheduled run so it's visible on "
                        "the Hub. Rename / add detail any time."),
        "category": "🗂 Auto-registered",
        "assignees": [machine],       # profile grouping
        "schedule": schedule,         # calendar days + time chip
    }
    if dry_run:
        return True, "DRY-RUN: would create library card %r (%s)" % (cid, name)
    try:
        from automations.recruiting_report.fill import _retry
        ws = _library_ws()
        row = [cid, name, real_module or "", "Auto (self-registered)",
               dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
               json.dumps(meta), script]
        try:
            found = ws.find(cid, in_column=1)
        except Exception:
            found = None
        if found:
            _retry(lambda: ws.update([row], "A%d:G%d" % (found.row, found.row),
                                     value_input_option="RAW"))
            return True, "updated existing library card %r" % cid
        _retry(lambda: ws.append_row(row, value_input_option="RAW"))
        return True, "created library card %r (%s)" % (cid, name)
    except Exception as e:  # noqa: BLE001 — never sink a report over card creation
        return False, "%s: %s" % (type(e).__name__, e)


# ------------------------------------------------------------------------ audit
def _scheduler_reports() -> Dict[str, dict]:
    cfg = json.loads(CONFIG_PATH.read_text())
    return {rid: r for rid, r in cfg.get("reports", {}).items()
            if r.get("on_scheduler")}


def audit() -> Dict[str, list]:
    """Classify every on-scheduler report by how its pill/card resolves. Pure
    read — no writes. Returns {bucket: [(report_id, card_id, daily)]}."""
    curated = _curated_map()
    existing = existing_card_ids()
    out = {"curated": [], "slug_match": [], "needs_card": [], "skipped": []}
    for rid, r in _scheduler_reports().items():
        daily = bool(r.get("cadence", {}).get("weekdays"))
        if is_internal(rid):
            out["skipped"].append((rid, "", daily)); continue
        if rid in curated:
            out["curated"].append((rid, curated[rid], daily)); continue
        if rid in CURATED_ALIAS:
            out["curated"].append((rid, CURATED_ALIAS[rid], daily)); continue
        if slug(rid) in existing:
            out["slug_match"].append((rid, slug(rid), daily))
        elif rid in existing:                       # already a library card
            out["slug_match"].append((rid, rid, daily))
        else:
            out["needs_card"].append((rid, rid, daily))  # created with underscore id
    return out


def _report_display_name(rid: str, r: dict) -> str:
    return r.get("display_name") or rid.replace("_", " ").title()


def sync(dry_run: bool = True) -> List[str]:
    """Create a library card for every needs_card report. dry_run reports only."""
    cfg = json.loads(CONFIG_PATH.read_text())
    reps = cfg.get("reports", {})
    msgs = []
    for rid, cid, _daily in audit()["needs_card"]:
        r = reps.get(rid, {})
        module = (r.get("command") or [None])[0]
        ok, msg = ensure_library_card(rid, _report_display_name(rid, r),
                                      module=module, dry_run=dry_run)
        msgs.append(("  ✓ " if ok else "  ✗ ") + rid + ": " + msg)
    return msgs


def reenrich(dry_run: bool = True) -> List[str]:
    """Rewrite every AUTO-REGISTERED library card from current schedule_config +
    code (profile, schedule, launcher). Use after changing the card template or a
    report's cadence/machine. Only touches cards this module created — never a
    human-curated one. Idempotent: updates in place, never dupes."""
    msgs = []
    try:
        recs = _library_ws().get_all_records()
    except Exception as e:
        return ["  ✗ could not read library: %s" % e]
    for r in recs:
        if not str(r.get("Created By", "")).startswith("Auto"):
            continue
        try:
            meta = json.loads(str(r.get("Metadata") or "{}"))
        except Exception:
            meta = {}
        rid = meta.get("source_report_id") or str(r.get("ID", "")).strip()
        if not rid:
            continue
        ok, msg = ensure_library_card(rid, meta.get("name", ""), dry_run=dry_run)
        msgs.append(("  ✓ " if ok else "  ✗ ") + rid + ": " + msg)
    return msgs


def _print_audit() -> None:
    a = audit()
    print("Hub coverage audit — %s" % dt.date.today().isoformat())
    print("  curated map:        %3d (already wired)" % len(a["curated"]))
    print("  slug-match card:    %3d (card exists, pill wires itself now)"
          % len(a["slug_match"]))
    print("  needs a new card:   %3d" % len(a["needs_card"]))
    print("  skipped (internal): %3d" % len(a["skipped"]))
    for bucket, title in (("slug_match", "PILL WIRES ITSELF (card already exists)"),
                          ("needs_card", "NEEDS A CARD CREATED")):
        if a[bucket]:
            print("\n%s:" % title)
            for rid, cid, daily in sorted(a[bucket]):
                print("   %-28s -> %-38s %s" % (
                    rid, cid, "[daily]" if daily else "[on-demand]"))


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="hub_coverage")
    ap.add_argument("--audit", action="store_true", help="show coverage gaps (read-only)")
    ap.add_argument("--sync", action="store_true", help="create missing library cards")
    ap.add_argument("--reenrich", action="store_true",
                    help="rewrite existing auto-registered cards from current config")
    ap.add_argument("--dry-run", action="store_true", help="don't write")
    args = ap.parse_args(argv)
    if args.sync or args.reenrich:
        msgs = sync(dry_run=args.dry_run) if args.sync else []
        if args.reenrich:
            msgs += reenrich(dry_run=args.dry_run)
        for m in msgs:
            print(m)
        if args.dry_run:
            print("\n(dry-run — nothing written.)")
        return 0
    _print_audit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
