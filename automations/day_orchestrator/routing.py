"""Send a hand-queued rerun to the emptiest Lucy that can actually run it.

WHY (Megan 2026-10-21): "if Eve and I are running reports (outside of the 4am
run) then you automatically direct them to the least loaded down machine at
that time so we're not always waiting on a que to clear out." Measured that
evening: 17 rows backed up on Lucy 2 (sixteen AppStream SMS reruns in a burst,
the 8:30pm NDS text stuck behind them) while Lucy 3 and Lucy 4 sat at zero.

WHAT MOVES — build/fix work only
--------------------------------
Megan, same evening: "nothing that we have scheduled to run is what i'm talking
about. I'm talking about if we're building or fixing." So only a `rerun` that
is ALL of:
  * queued by a person or a Claude session (not `auto:`), with no --machine;
  * of an entry that is NOT on the 4am scheduler and has NO timer of its own
    — no `standalone_weekdays` / `standalone_watch` / `runs_at`, AND no
    deploy/*.sh or *.plist that starts its module or reruns it. The config
    flags alone missed leaders_call (Mon LaunchAgent), birthday_reminders and
    five more in the first dry run. What's left is probes, backfills, one-off
    pulls and hand_run_only builds;
  * not an install_/remove_ job and not `stay_home`.
Scheduled reports keep their machine, full stop, even on a hand rerun.

WHERE IT MAY GO — every rule must hold
--------------------------------------
The Lucys are NOT interchangeable (fleet.py), and the mismatches fail SILENTLY,
so a machine is a candidate only when:

  1. Same OwnerVille login as home — unless the report is AppStream-only
     (`source_type: appstream`), which never touches OwnerVille. A Carlos
     report on a Raf login reads Raf's offices: wrong numbers, no error.
  2. AppStream reports: the box runs AppStream (`runs_appstream`).
  3. Home can text → the box can text (`can_text`).
  4. If the entry names NO machine, rules 1-3 are enough: it landed on Lucy 1
     only because nobody picked one (80 entries, 2026-10-21). If it IS
     pinned, also one of: same Google account as home; `can_run_on` lists
     the box; or PROVEN — a hand rerun of it finished `done` there within
     PROVEN_DAYS. A missing sheet share fails loudly, so for build/fix work a
     wrong guess costs one visible retry, not a silent wrong number.
  An entry that depends on files saved on its own box (sms_ai_settings,
  sms_crosscheck) carries `stay_home: true`.

AND NEVER ONTO A BUSY 4AM BATCH
-------------------------------
Queue rows don't show the 4am batch. So each Lucy's read lane stamps its
heartbeat (Job Heartbeats tab) with `batch=running|idle@<utc>` every ~10 min,
from the orchestrator's own day lock. A box is a target only when that stamp
is fresh (HEARTBEAT_MAX_AGE_MIN) and says idle. Missing, stale or unreadable →
not a target. And nothing moves at all between QUIET_HOURS, when the batch is
starting. Megan 2026-10-21: "we CANNOT mess up the 4am run."

HOW IT PICKS
------------
Load = queued + running rows on the control tab (+ BATCH_LOAD if home's own
batch is running, since a rerun there competes with it). Home keeps the job
unless a candidate is at least MOVE_MARGIN rows lighter. Any error → home.
"""
from __future__ import annotations

import datetime as _dt
import re
import shlex
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from automations.shared import fleet

#: How many rows lighter another machine must be before a job leaves home.
MOVE_MARGIN = 2
#: Extra load counted on HOME while its own batch is running.
BATCH_LOAD = 5
#: A heartbeat older than this says nothing about the batch.
HEARTBEAT_MAX_AGE_MIN = 25
#: Local hours [start, end) when nothing moves: the 4am batch is starting.
QUIET_HOURS = (3, 5)
#: How far back a clean finish counts as proof a report runs on a box.
PROVEN_DAYS = 30
#: Report ids that act ON a machine (install/remove a LaunchAgent, etc.).
NEVER_MOVE_PREFIXES = ("install_", "uninstall_", "remove_")

_BUSY = ("queued", "running")


# ---------------------------------------------------------------- heartbeat
def batch_note(running: Optional[bool], now_utc: Optional[_dt.datetime] = None) -> str:
    """The heartbeat note a Lucy publishes: 'batch=running@<utc iso>'."""
    state = {True: "running", False: "idle"}.get(running, "unknown")
    now_utc = now_utc or _dt.datetime.now(_dt.timezone.utc)
    return "batch={}@{}".format(state, now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"))


def batch_state(note: str, now_utc: Optional[_dt.datetime] = None) -> Optional[str]:
    """'running' / 'idle' from a FRESH note, else None (missing, stale, junk).
    The stamp is UTC so a laptop in another timezone ages it correctly."""
    try:
        head, stamp = (note or "").split("@", 1)
        state = head.split("=", 1)[1]
        seen = _dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_dt.timezone.utc)
    except (ValueError, IndexError):
        return None
    now_utc = now_utc or _dt.datetime.now(_dt.timezone.utc)
    if (now_utc - seen).total_seconds() > HEARTBEAT_MAX_AGE_MIN * 60:
        return None
    return state if state in ("running", "idle") else None


# ---------------------------------------------------------------- queue rows
def report_id_of(args: str) -> str:
    try:
        parts = shlex.split(args or "")
    except ValueError:
        parts = (args or "").split()
    return parts[0] if parts else ""


def count_busy(rows: Iterable[list]) -> int:
    """Queued + running rows on one control tab (rows exclude the header)."""
    n = 0
    for r in rows:
        status = (r[4] if len(r) > 4 else "").strip().lower()
        if status in _BUSY:
            n += 1
    return n


def proven_on(rows: Iterable[list], report_id: str, parse_ts: Callable,
              now: _dt.datetime) -> bool:
    """A hand-queued rerun of `report_id` finished `done` on this tab lately."""
    for r in rows:
        if len(r) < 5 or r[1] != "rerun":
            continue
        if str(r[3]).startswith("auto:"):
            continue
        if not str(r[4]).strip().lower().startswith("done"):
            continue
        if report_id_of(r[2]) != report_id:
            continue
        q = parse_ts(r[0])
        if q is None:
            continue
        try:
            age = now - q
        except TypeError:   # naive vs aware — compare wall clocks
            age = now.replace(tzinfo=None) - q.replace(tzinfo=None)
        if age.days < PROVEN_DAYS:
            return True
    return False


# ---------------------------------------------------------------- eligibility
def identity_ok(raw_report: dict, home: fleet.Machine, box: fleet.Machine) -> bool:
    """Rules 1-3: the logins this report depends on are the same on `box`."""
    src = raw_report.get("source_type", "tableau")
    if src != "appstream" and box.ownerville_account != home.ownerville_account:
        return False
    if src == "appstream" and not box.runs_appstream:
        return False
    if home.can_text and not box.can_text:
        return False
    return True


#: An entry with any of these runs on its own clock — it is scheduled work.
TIMER_KEYS = ("standalone_weekdays", "standalone_watch", "runs_at")


DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy"
_deploy_text_cache: Optional[str] = None


def _deploy_text() -> str:
    global _deploy_text_cache
    if _deploy_text_cache is None:
        parts = []
        for pat in ("*.sh", "*.plist"):
            for f in sorted(DEPLOY_DIR.glob(pat)):
                try:
                    parts.append(f.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    pass
        _deploy_text_cache = "\n".join(parts)
    return _deploy_text_cache


def has_launch_agent(raw_report: dict, report_id: str,
                     deploy_text: Optional[str] = None) -> bool:
    """A deploy script starts this entry's module, or queues a rerun of it.
    Unreadable deploy dir → True (treat as scheduled; it stays home)."""
    text = _deploy_text() if deploy_text is None else deploy_text
    if not text:
        return True
    module = (raw_report.get("command") or [""])[0]
    if module and re.search(r"(?<![\w.])" + re.escape(module) + r"(?![\w.])", text):
        return True
    return bool(re.search(r"rerun[\"' ]+" + re.escape(report_id) + r"(?!\w)", text))


def is_build_or_fix(raw_report: dict, report_id: str,
                    deploy_text: Optional[str] = None) -> bool:
    """True for hand-run work (probes, backfills, pulls) that may move."""
    if raw_report.get("on_scheduler") or raw_report.get("stay_home"):
        return False
    if any(raw_report.get(k) for k in TIMER_KEYS):
        return False
    if report_id.startswith(NEVER_MOVE_PREFIXES):
        return False
    return not has_launch_agent(raw_report, report_id, deploy_text)


def candidates(raw_report: dict, report_id: str,
               history: Dict[str, List[list]], parse_ts: Callable,
               now: _dt.datetime, deploy_text: Optional[str] = None) -> List[str]:
    """Home first, then every machine that passes the rules, roster order."""
    pinned = bool((raw_report.get("machine") or "").strip())
    home_name = (raw_report.get("machine") or fleet.RUNNERS[0]).strip()
    home = fleet.get(home_name)
    out = [home_name]
    if home is None or not is_build_or_fix(raw_report, report_id, deploy_text):
        return out
    explicit = set(raw_report.get("can_run_on") or [])
    for box in fleet.MACHINES:
        if box.name == home_name or not identity_ok(raw_report, home, box):
            continue
        same_google = bool(box.google_account) and \
            box.google_account == home.google_account
        if (not pinned or same_google or box.name in explicit
                or proven_on(history.get(box.name, []), report_id, parse_ts, now)):
            out.append(box.name)
    return out


# ---------------------------------------------------------------- decision
def choose(cands: List[str], loads: Dict[str, int],
           margin: int = MOVE_MARGIN) -> str:
    """Pure: cands[0] is home; a machine with no known load is never chosen."""
    home = cands[0]
    home_load = loads.get(home)
    if home_load is None:
        return home
    best, best_load = home, home_load
    for m in cands[1:]:
        load = loads.get(m)
        if load is not None and load < best_load:
            best, best_load = m, load
    return best if home_load - best_load >= margin else home


def pick(raw_report: dict, report_id: str, by: str,
         history: Dict[str, List[list]], beats: Dict[str, dict],
         parse_ts: Callable, now: Optional[_dt.datetime] = None,
         beat_id: Callable[[str], str] = None,
         deploy_text: Optional[str] = None) -> Optional[str]:
    """The machine to queue this rerun on, or None to leave it at home.

    `history` = {machine: control-tab rows without header}; `beats` = the Job
    Heartbeats tab as silent_job_watch.read_beats() returns it."""
    if str(by or "").startswith("auto:"):
        return None
    now = now or _dt.datetime.now().astimezone()
    if QUIET_HOURS[0] <= now.hour < QUIET_HOURS[1]:
        return None
    cands = candidates(raw_report, report_id, history, parse_ts, now, deploy_text)
    if len(cands) < 2:
        return None
    beat_id = beat_id or (lambda m: "mini_control_" + m.lower().replace(" ", "_"))
    now_utc = now.astimezone(_dt.timezone.utc) if now.tzinfo else \
        _dt.datetime.now(_dt.timezone.utc)
    loads: Dict[str, int] = {}
    for i, m in enumerate(cands):
        if m not in history:
            continue
        state = batch_state((beats.get(beat_id(m)) or {}).get("note", ""), now_utc)
        load = count_busy(history[m])
        if i == 0:                       # home: always allowed, batch adds load
            loads[m] = load + (BATCH_LOAD if state == "running" else 0)
        elif state == "idle":            # others: only with a fresh 'idle'
            loads[m] = load
    picked = choose(cands, loads)
    return None if picked == cands[0] else picked
