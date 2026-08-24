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
# Cards were split out of dashboard.py 2026-08-20; scan both so ids in either
# file (and any card that ever moves back) keep counting as hardcoded.
HUB_CARDS_PY = REPO_ROOT / "automations" / "hub_cards.py"
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
    r"|recruiting_backfill_juan|applicant_clear_session"
    r"|harvest_prime"                       # churn-cache warm — internal, not a report
    r"|dd_headshots_sync|dd_special_accumulate"  # DD sub-steps under dd-bulletin
    r"|session_proof_"                      # ownerville session-holder heartbeats
    r"|tableau_ledger"                      # access-budget ledger summaries
    r").*|.*(_slack|_post|_send|_finalize)$")

# Reports whose card already exists under an id slug() can't derive — map by hand
# so we reuse the real card instead of auto-creating a duplicate. The --audit
# surfaces any new report that needs an entry here.
CURATED_ALIAS = {
    "texas_de_brazil": "june_texas_de_brazil_monthly_competition",
    # Standalone agents whose scheduler report_id differs from the real card id —
    # alias so the pill wires to the EXISTING card instead of auto-creating a
    # duplicate. Surfaced by audit_agents() (2026-07-27).
    "applicant_sync": "applicant-tracker-sync",       # applicant-morning/-evening
    "b2b_metrics_preview": "b2b-metrics",             # b2b-metrics standalone
}


def slug(report_id: str) -> str:
    """Orchestrator report_id -> Hub card-id convention (underscores -> hyphens)."""
    return report_id.replace("_", "-").strip("-")


# Background plumbing + auto-registered sub-step/dupe stubs that must NEVER carry a
# Hub card of their own (they never publish a real run — they self-registered when
# hub_coverage scanned an agent/plist, cluttering the Hub with permanently-white
# cards). Listed explicitly so a plain row-delete STICKS — without this, the next
# sync() recreates them. jiraiya_bot is deliberately NOT here (Megan wants the /dd
# + promo listener visible as a card). Swept 2026-08-02. [[reference_hub_card_rendering_rules]]
_NOT_A_REPORT = frozenset({
    # background machinery (not a report anyone runs)
    "day_orchestrator", "card_scheduler", "session_holder", "keep_awake",
    "mini_control", "board_probe", "orchestrator_schedule_guard", "lucy2_digest",
    "bg_check_watchdog", "due_diligence_watch", "harvest_proof_1pm", "proof_order_log",
    # auto-registered sub-step / dupe stubs of a real card (never published)
    "applicant_morning", "applicant_evening", "appstream_morning", "leaders_call_mon",
    "weather_6am", "texas_de_brazil_745", "new_start_followup_sat",
    "override_bulletin_send_fri", "brand_audit_noon", "car_rides_cleanup",
    "harvest_prime",
    # Tableau access-budget tooling (Megan 2026-08-17). All three are hand-run
    # DIAGNOSTICS with on_scheduler:false — they answer "is a shared login safe
    # for this report" and "how many times did we sign in". They self-registered
    # the first time they ran and showed up as scheduled-looking Hub cards, which
    # they are not. Nothing to run from the Hub; they run via `lucy rerun <id>`.
    "session_proof_fiber", "session_proof_captainship", "session_proof_probes",
    "tableau_ledger_summary",
})


def is_internal(report_id: str) -> bool:
    return report_id in _NOT_A_REPORT or bool(_SKIP_RE.match(report_id))


# ---------------------------------------------------------------- card inventory
def _hardcoded_card_ids() -> Set[str]:
    """Card ids baked into AUTOMATED_REPORTS (hub_cards.py, plus dashboard.py
    for anything not yet moved) — read by regex so we never import Streamlit.
    Stable format: `"id": "kebab-case"`."""
    ids: Set[str] = set()
    for path in (HUB_CARDS_PY, DASHBOARD_PY):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        ids |= set(re.findall(r'"id":\s*"([a-z0-9_-]+)"', text))
    return ids


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
    curated = _curated_map()
    mapped = curated.get(report_id) or CURATED_ALIAS.get(report_id)
    # An EXPLICIT curated mapping (_HUB_CARD / CURATED_ALIAS) means the report is
    # MEANT to carry a card, so it OVERRIDES the internal/skip patterns. Without
    # this, a report_id ending in _slack/_post/_send/_finalize (e.g.
    # org_board_slack — the daily Org Sales Board Slack post) matched _SKIP_RE and
    # resolved to None, so its pill silently stopped publishing even though
    # _HUB_CARD maps it to a real card (regression: org-sales-board-slack went
    # white after 2026-07-27). Only skip when there is NO explicit mapping.
    # (Megan 2026-07-29)
    if not mapped and is_internal(report_id):
        return None
    # Fast path: a curated target that is a real hardcoded card (local read, no
    # network) is trusted as-is.
    if mapped and mapped in _hardcoded_card_ids():
        return mapped
    existing = _existing if _existing is not None else existing_card_ids()
    # A curated target that exists as a library card is valid too.
    if mapped and mapped in existing:
        return mapped
    # PHANTOM GUARD: a curated mapping whose target card does NOT exist anywhere
    # (e.g. b2b_quality -> "b2b-quality", a card that was never created) must NOT
    # short-circuit — returning it would publish the report's pill into the void
    # forever. Fall through to slug-match / auto-create so the running report
    # always lands on a real, publishable card. (2026-07-27)
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


def _is_offboarded(report_id: str) -> bool:
    """Does `report_id` belong to an office that was deliberately turned off?

    Matches the office KEY against office_onboarding.apply.OFFBOARDED_KEYS —
    `drew_metrics` -> `drew`, and the bare key too, so both the report id and a
    raw key answer the same. Best-effort by design: if that module can't be
    imported for any reason, we must NOT block card creation, because a missing
    card is the failure this whole module exists to prevent."""
    try:
        from automations.office_onboarding.apply import OFFBOARDED_KEYS
    except Exception:  # noqa: BLE001 — never block carding on an import
        return False
    rid = (report_id or "").strip().lower()
    if not rid:
        return False
    return any(rid == k or rid.startswith(k + "_") for k in OFFBOARDED_KEYS)


def ensure_library_card(report_id: str, report_name: str, *,
                        module: Optional[str] = None,
                        dry_run: bool = False,
                        category: Optional[str] = None,
                        emoji: Optional[str] = None,
                        description: Optional[str] = None,
                        schedule_ov: Optional[dict] = None,
                        machine_ov: Optional[str] = None) -> Tuple[bool, str]:
    """Create a Report Library card for a report that has none. Idempotent —
    keyed by the underscore report_id, so a second call updates in place, never
    dupes. Auto-created cards carry a delegating launcher script (so they render
    and run) and are tagged so Megan can rename / curate them later. Looks up the
    real module + base_args from schedule_config when not passed.

    OFFBOARDED REPORTS ARE REFUSED (Megan 2026-08-24). Self-registration is why
    "remove Drew" did not stick: he came out of both registries, the schedule and
    the onboarding apply path, and his card kept coming back — because the card
    is a ROW IN THE SHARED LIBRARY SHEET, and nothing code-side deletes a sheet
    row. Megan asked four separate times. So the offboard denylist that already
    guards onboarding now guards THIS door too: a report belonging to an
    offboarded office never gets a card, however it is reached."""
    if _is_offboarded(report_id):
        return False, ("{} belongs to an offboarded office — no Hub card "
                       "(see office_onboarding.apply.OFFBOARDED_KEYS)"
                       .format(report_id))
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
    if machine_ov:
        machine = machine_ov
    script = _launcher_script(cid, real_module, base_args)
    schedule = schedule_ov or _schedule_meta(weekdays, est)
    # Section placement on the schedule page: a card with its OWN fixed clock time
    # is a Time-Set report (self_scheduled -> ⏰ TIME SET divider + a "· HH:MM" chip
    # on the tile); a "4 AM flow" / on-demand card rides the ☀️ MORNING BATCH.
    _t = str(schedule.get("time", "")).strip().lower()
    is_timed = bool(_t) and "flow" not in _t and "demand" not in _t
    meta = {
        "id": cid,
        "name": name,
        "module": real_module or "",
        "args": base_args,
        "creator": "Auto (self-registered)",
        "auto_registered": True,
        "auto_registered_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source_report_id": report_id,
        "emoji": emoji or "🗂",
        "description": description or ("Auto-registered from a scheduled run so "
                        "it's visible on the Hub. Rename / add detail any time."),
        "category": category or "🗂 Auto-registered",
        "assignees": [machine],       # profile grouping
        "schedule": schedule,         # calendar days + time chip
        "self_scheduled": is_timed,   # ⏰ Time Set (fixed clock) vs ☀️ Morning Batch
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


# --------------------------------------------------- launchd agent coverage
# The 4am-batch audit above only sees on_scheduler reports. STANDALONE launchd
# agents (deploy/com.alphalete.*.plist) are where automations silently go
# uncarded — a report whose module never publishes AND isn't in the batch is
# invisible (this is exactly how dd_gross_revenue was lost). These helpers
# reconcile the agent inventory itself, so every SCHEDULED job gets a card.
DEPLOY_DIR = REPO_ROOT / "deploy"

# Pure-infrastructure agents (never a report) + the cutover-retire duplicates
# that shadow a batch report which already owns a card
# (schedule_config _meta.cutover_retire_jobs). These never get a card.
_INFRA_AGENTS = {
    "day-orchestrator", "orchestrator-schedule-guard", "card-scheduler",
    "session-holder", "keep-awake", "mini-control", "hub-watch",
    "lucy2-digest", "bg-check-watchdog", "harvest-proof-1pm", "board-probe",
    "social-scanner",
    "appstream-morning", "weather-6am", "brand-audit-noon", "recruiting-report",
    # frontier-sunday-6pm is just the Sunday timer that runs opt_frontier --email;
    # opt_frontier already owns the curated 'Frontier OPT Data Pull' card, so this
    # wrapper is deliberately card-less. Without this it registered a duplicate
    # ('Frontier Sunday 6Pm') that confused the two — deleted 2026-08-02.
    "frontier-sunday-6pm",
    # deploy/com.alphalete.harvest-3am.plist is COMMITTED but deliberately NOT
    # installed on any machine yet (Megan 2026-08-17: build it, prove it, then
    # flip). sync_launchd_system scans deploy/*.plist, not what launchd actually
    # loaded, so it carded a 3 AM job that does not exist anywhere and the card
    # sat grey "didn't run" — correctly, but misleadingly. Card it when it is
    # actually installed, not when the file lands in the repo.
    "harvest-3am",
}
# Wrapper module segments that are PREP steps (run before the real report), so a
# naive first-`-m` grab would resolve the wrong module (e.g. stf's chrome_guard).
_PREP_MODULES = ("chrome_guard", "chrome_collision", "collision_guard")
_PUBLISH_ID_RE = re.compile(
    r"publish_(?:done|running)\(\s*['\"]([a-zA-Z0-9_]+)['\"]")
_WRAPPER_MODULE_RE = re.compile(r"-m\s+(automations\.[a-zA-Z0-9_.]+)")


def _wrapper_for_plist(plist_path: Path) -> Optional[Path]:
    """The deploy/*.sh a plist runs (mapped into our repo, ignoring the committed
    laptop path placeholder)."""
    try:
        import plistlib
        args = plistlib.loads(plist_path.read_bytes()).get("ProgramArguments", [])
    except Exception:
        return None
    for a in args:
        if isinstance(a, str) and a.endswith(".sh"):
            cand = DEPLOY_DIR / Path(a).name
            return cand if cand.exists() else None
    return None


def _module_to_report_id(module: str) -> Optional[str]:
    """Canonical report_id whose schedule_config command runs `module`, or None."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return None
    for rid, r in cfg.get("reports", {}).items():
        if (r.get("command") or [None])[0] == module:
            return rid
    return None


def _agent_report_id(agent_name: str) -> Tuple[Optional[str], str]:
    """Best-effort CONFIDENT report_id for a launchd agent → (report_id, reason).

    Prefers the wrapper's own publish_*() id — the id the pill actually writes to,
    the only fully-reliable signal — then a schedule_config module match. Returns
    (None, reason) when it can't resolve confidently: we NEVER guess a card into
    existence (a junk card is worse than a flagged gap). reason 'infra'/'internal'
    = deliberately card-less; 'unresolved' = surface for human review.
    """
    if agent_name in _INFRA_AGENTS:
        return None, "infra"
    plist = DEPLOY_DIR / ("com.alphalete.%s.plist" % agent_name)
    if not plist.exists():
        return None, "no-plist"
    wrapper = _wrapper_for_plist(plist)
    if wrapper is None:
        return None, "no-wrapper"
    try:
        text = wrapper.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None, "unreadable-wrapper"
    m = _PUBLISH_ID_RE.search(text)
    if m:
        rid = m.group(1)
        return (None, "internal") if is_internal(rid) else (rid, "publish-id")
    for mod in _WRAPPER_MODULE_RE.findall(text):
        if any(p in mod for p in _PREP_MODULES):
            continue
        rid = _module_to_report_id(mod)
        if rid:
            return (None, "internal") if is_internal(rid) else (rid, "module-match")
    return None, "unresolved"


def audit_agents() -> Dict[str, list]:
    """Classify every standalone launchd agent by whether it has a Hub card.
    Pure read. Buckets: covered / needs_card / unresolved / infra."""
    existing = existing_card_ids()
    out = {"covered": [], "needs_card": [], "unresolved": [], "infra": []}
    for plist in sorted(DEPLOY_DIR.glob("com.alphalete.*.plist")):
        name = plist.name[len("com.alphalete."):-len(".plist")]
        rid, why = _agent_report_id(name)
        if rid is None:
            bucket = "infra" if why in ("infra", "internal") else "unresolved"
            out[bucket].append((name, why))
            continue
        card = resolve_card(rid, create=False, _existing=existing)
        (out["covered"].append((name, rid, card)) if card
         else out["needs_card"].append((name, rid)))
    return out


def sync_agents(dry_run: bool = True) -> List[str]:
    """Create a library card for every launchd agent with a CONFIDENT report_id
    but no card. Confident-only — unresolved agents are surfaced by audit_agents(),
    never auto-carded. Idempotent (ensure_library_card updates in place)."""
    msgs = []
    for name, rid in audit_agents()["needs_card"]:
        ok, msg = ensure_library_card(rid, rid.replace("_", " ").title(),
                                      dry_run=dry_run)
        msgs.append(("  ✓ " if ok else "  ✗ ") + name + " -> " + rid + ": " + msg)
    return msgs


_XML_COMMENT = re.compile(rb"<!--.*?-->", re.S)


def _plist_schedule(plist_path: Path) -> Optional[dict]:
    """Parse a plist's StartCalendarInterval into a card schedule (fixed clock →
    a card that lands in ⏰ Time Set). None for interval/continuous jobs (no
    calendar) → on-demand. launchd Weekday: 0/7=Sun, 1=Mon…6=Sat → Python Mon=0.
    launchd Day = day-of-month → a monthly schedule (days_of_month list)."""
    try:
        import plistlib
        raw = plist_path.read_bytes()
        try:
            d = plistlib.loads(raw)
        except Exception:
            d = plistlib.loads(_XML_COMMENT.sub(b"", raw))
    except Exception:
        return None
    cal = d.get("StartCalendarInterval")
    if not cal:
        return None
    if isinstance(cal, dict):
        cal = [cal]
    def _pywd(wd):
        return 6 if wd in (0, 7) else wd - 1
    wds = sorted({_pywd(e["Weekday"]) for e in cal if "Weekday" in e})
    doms = sorted({int(e["Day"]) for e in cal if "Day" in e})
    e0 = min(cal, key=lambda e: (e.get("Hour", 0), e.get("Minute", 0)))
    t = "%02d:%02d" % (e0.get("Hour", 0), e0.get("Minute", 0))
    if doms:
        # Day-of-month job (e.g. dd-gross-revenue, 1st + 15th at noon). Before
        # this branch existed the card was saved as DAILY, so 🚨 Needs attention
        # flagged it "no run logged" on every day it correctly didn't run.
        return {"frequency": "monthly", "days_of_month": doms, "time": t}
    sc = {"frequency": "daily" if not wds or len(wds) >= 7 else "weekly", "time": t}
    if wds and len(wds) < 7:
        sc["weekdays"] = wds
    return sc


def sync_launchd_system(dry_run: bool = True) -> List[str]:
    """Card every launchd agent (deploy/com.alphalete.*.plist) that fires on a
    schedule but has NO card of ANY kind — including ⚙️ System plumbing that
    _agent_report_id can't resolve to a report. Keeps the "every scheduled job is
    visible" guarantee true for FUTURE jobs, not just today's. Hardened dedup:
    skips anything already covered by a report card (hardcoded / curated / slug /
    library) OR a same-name card — so it can never recreate the duplicate cards a
    naive pass produced (2026-07-28). Idempotent."""
    existing = existing_card_ids()
    curated = _curated_map()
    msgs: List[str] = []
    for plist in sorted(DEPLOY_DIR.glob("com.alphalete.*.plist")):
        name = plist.name[len("com.alphalete."):-len(".plist")]
        rid, _why = _agent_report_id(name)
        # covered by a real report card (hardcoded / curated / slug / library)?
        if rid and resolve_card(rid, create=False, _existing=existing):
            continue
        cid = name.replace("-", "_")
        # would this dupe an existing card, a hardcoded slug, or a curated target?
        if (cid in existing or slug(cid) in existing or cid in curated
                or cid in CURATED_ALIAS):
            continue
        # Pure-infra plumbing + cutover-retire duplicates (in _INFRA_AGENTS) are
        # NOT reports — Megan doesn't want them on the Hub, and the _INFRA_AGENTS
        # contract already says they "never get a card". Skip them entirely
        # (audit_agents still tracks them in the 'infra' bucket); only genuine
        # standalone jobs get an auto-card. (Megan 2026-07-28)
        if name in _INFRA_AGENTS:
            continue
        sched = _plist_schedule(plist)
        cat, emoji = "🗂 Auto-registered", "🗂"
        ok, msg = ensure_library_card(
            cid, name.replace("-", " ").title(), category=cat, emoji=emoji,
            schedule_ov=sched,
            description="Scheduled launchd job (%s). Auto-carded so no automation "
                        "runs invisibly." % name,
            dry_run=dry_run)
        msgs.append(("  ✓ " if ok else "  ✗ ") + name + ": " + msg)
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
