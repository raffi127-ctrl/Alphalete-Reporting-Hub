"""4am heartbeat — did the day orchestrator actually produce a day_state today?

WHY THIS EXISTS (Megan, 2026-08-27): on 2026-08-27 the Lucy 2 orchestrator fired
exactly on time at 04:00:04 and was dead by 04:00:05 — `registry.load_config()`
raised JSONDecodeError because a failed `git stash pop` at 00:47 had left
`schedule_config.json` unmerged (UU, with conflict markers). It ran ZERO reports.

Nobody was told. Every alert in the system is PER-REPORT: a report that fails
raises an incident, but a report that never runs produces nothing to fail. Megan
found out ~2h45m later, when B2B Metrics didn't appear in the office channels.
The machine passed every "is it up?" check the whole time — poller alive, Chrome
fine, AppStream seeded, awake on AC power — which is why the same outage kept
getting diagnosed as a re-seed or a wedged poller and kept coming back.

The intraday watcher (machine_digest._run_watch) could not have caught it twice
over: it calls `registry.load_config()` UNGUARDED at module use, so the corrupt
config kills the watcher too, and its own docstring excludes this class of
failure anyway ("Orchestrator-managed reports are skipped — they already
self-alert in real time"). The orchestrator is the only thing that reports on
orchestrator-managed reports, so when it dies its whole portfolio goes quiet.

SO: THIS MODULE DELIBERATELY IMPORTS NOTHING FROM automations.day_orchestrator.
Not registry, not notify, not state. A watchdog that shares a fuse with the thing
it watches is not a watchdog. It reads the day_state file as plain JSON off disk
and resolves the Slack channel WITHOUT the schedule config (cache file first,
then a best-effort config read, then a literal fallback), so it still speaks when
the config is exactly what's broken.

  python -m automations.orchestrator_heartbeat.run              # check + alert
  python -m automations.orchestrator_heartbeat.run --dry-run    # print, post nothing
  python -m automations.orchestrator_heartbeat.run --force      # ignore the once-a-day marker

Stdlib only, except the shared Slack poster (which imports nothing from
day_orchestrator — checked). Python 3.9 on the runners: no `X | None` syntax.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "output" / "day_state"
CONFIG_PATH = REPO_ROOT / "automations" / "day_orchestrator" / "schedule_config.json"

# The corrections channel, resolved without the schedule config where possible.
# notify.py writes the resolved numeric id here; it is a plain file, so reading it
# costs no import and survives a broken config.
CHANNEL_ID_CACHE = REPO_ROOT / "output" / ".corrections_channel_id"
# Last-resort literal: #claudecorrections-and-requests. Hardcoded ON PURPOSE —
# every other source for this id lives behind the file that breaks.
CHANNEL_FALLBACK = "C0BK5PRG259"

ORCHESTRATOR_LABEL = "com.alphalete.day-orchestrator"
MARKER_DIR = REPO_ROOT / "output" / ".heartbeat"


def _today() -> str:
    return dt.date.today().isoformat()


def _machine_name() -> str:
    """This runner's friendly name — the gitignored .machine-profile marker when
    present, else the hostname. Read as a FILE, never via hub_identity, so this
    keeps working when the repo's importable code is the thing that is broken."""
    marker = REPO_ROOT / ".machine-profile"
    try:
        name = marker.read_text().strip()
        if name:
            return name
    except Exception:  # noqa: BLE001 — no marker is normal on Megan's laptop
        pass
    return socket.gethostname()


def _orchestrator_installed() -> bool:
    """Is the day-orchestrator LaunchAgent loaded on THIS machine?

    Guards against the heartbeat crying wolf on a box that legitimately never
    runs the 4am batch (Megan's laptop, a machine whose agent was booted out on
    purpose). Absent launchctl (non-macOS) => treat as NOT installed and stay
    quiet, since this only ever runs on the Lucy runners.
    """
    try:
        out = subprocess.run(["/bin/launchctl", "list"], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001 — no launchctl / timeout
        return False
    return ORCHESTRATOR_LABEL in out


def _config_is_valid() -> Tuple[bool, str]:
    """Is schedule_config.json parseable? Diagnostic only — this is the most
    likely CAUSE of a missing day_state, so naming it turns the alert into a
    fix instead of a mystery. Never raises."""
    try:
        raw = CONFIG_PATH.read_text()
    except Exception as e:  # noqa: BLE001
        return False, "unreadable ({})".format(type(e).__name__)
    if "<<<<<<<" in raw or ">>>>>>>" in raw:
        return False, "contains git conflict markers (unmerged)"
    try:
        json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return False, "invalid JSON ({})".format(str(e)[:90])
    return True, "valid"


def check_day_state(date: Optional[str] = None) -> Tuple[bool, str]:
    """(ok, detail) for today's day_state file.

    Three distinct bad states, deliberately reported apart — they need different
    fixes and reading them as one is how "it's the poller again" happens:
      * file missing        -> the orchestrator never got far enough to write it
      * file unparseable    -> it wrote, then something corrupted it
      * zero reports        -> it started and loaded no schedule at all
    """
    date = date or _today()
    path = STATE_DIR / "{}.json".format(date)
    if not path.exists():
        return False, "no day_state file for {} — the orchestrator never wrote one".format(date)
    try:
        blob = json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        return False, "day_state for {} is unreadable: {}".format(date, str(e)[:90])
    reports = blob.get("reports") or {}
    if not reports:
        return False, "day_state for {} exists but lists ZERO reports".format(date)
    return True, "{} report(s) recorded".format(len(reports))


def _resolve_channel() -> str:
    try:
        cached = CHANNEL_ID_CACHE.read_text().strip()
        if cached:
            return cached
    except Exception:  # noqa: BLE001 — no cache yet is normal
        pass
    # Best-effort config read. If the config is the broken thing, this is exactly
    # the branch that fails, which is why the literal fallback exists below.
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        cid = (cfg.get("settings", {}).get("corrections_slack_channel") or "").strip()
        if cid:
            return cid
    except Exception:  # noqa: BLE001
        pass
    return CHANNEL_FALLBACK


def build_alert(detail: str, cfg_ok: bool, cfg_detail: str) -> str:
    machine = _machine_name()
    lines = [
        ":rotating_light: *day orchestrator did not run on {}* — {}".format(machine, _today()),
        detail,
    ]
    if not cfg_ok:
        lines.append(
            "Likely cause: `automations/day_orchestrator/schedule_config.json` is "
            "{} — every report loads it first, so nothing can run and "
            "`lucy rerun` is dead too.".format(cfg_detail))
        lines.append("Fix: `lucy git_recover --machine \"{}\"`, then "
                     "`lucy restart_orchestrator --machine \"{}\" --force`.".format(machine, machine))
    else:
        lines.append("`schedule_config.json` parses, so this is NOT the 2026-08-27 "
                     "corrupt-config failure. Check "
                     "`lucy logtail day-orchestrator-{}` for the traceback.".format(_today()))
    return "\n".join(lines)


def _already_alerted(date: str) -> bool:
    return (MARKER_DIR / date).exists()


def _mark_alerted(date: str) -> None:
    try:
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
        (MARKER_DIR / date).write_text(dt.datetime.now().isoformat())
    except Exception:  # noqa: BLE001 — a marker failure must never block the alert
        pass


def post(text: str) -> bool:
    """Post to the corrections channel AS Lucy. Returns False on any failure —
    the caller still exits non-zero, so launchd records the problem even when
    Slack is the thing that is down."""
    try:
        from automations.shared import slack_metrics_post as smp
        smp._client().chat_postMessage(channel=_resolve_channel(), text=text)
        return True
    except Exception as e:  # noqa: BLE001
        print("heartbeat: Slack post FAILED ({}: {})".format(type(e).__name__, str(e)[:140]))
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orchestrator_heartbeat")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the verdict, post nothing, write no marker")
    ap.add_argument("--force", action="store_true",
                    help="alert even if today's once-a-day marker is already set")
    ap.add_argument("--date", default=None, help="check a specific YYYY-MM-DD")
    ap.add_argument("--ignore-agent", action="store_true",
                    help="check even if the day-orchestrator agent isn't loaded here")
    ap.add_argument("--alert-healed", action="store_true",
                    help="post the 'pre-flight repaired schedule_config' notice "
                         "(called by deploy/day_orchestrator.sh, not by hand)")
    a = ap.parse_args(argv)

    date = a.date or _today()

    # A self-heal that says nothing is its own trap: the batch would quietly
    # succeed every morning while the thing that CORRUPTS the config (a `lucy
    # update` autostash pop that conflicts and still exits 0) stayed invisible.
    # Low-key wording on purpose — nothing is broken right now, but somebody
    # should still go find out why the file needed repairing.
    if a.alert_healed:
        text = (":wrench: *orchestrator pre-flight repaired schedule_config.json* "
                "on {} — {}\nThe file was unparseable at 04:00 and was restored "
                "from origin/main, so today's batch ran normally. Nothing is down. "
                "Worth checking WHY it was corrupt — a `lucy update` whose "
                "autostash pop conflicts still exits 0 and leaves it unmerged."
                .format(_machine_name(), date))
        if a.dry_run:
            print("[dry-run] would post to {}:\n{}".format(_resolve_channel(), text))
            return 0
        post(text)
        print(text)
        return 0

    if not a.ignore_agent and not _orchestrator_installed():
        print("heartbeat: {} not loaded on {} — nothing to watch here.".format(
            ORCHESTRATOR_LABEL, _machine_name()))
        return 0

    ok, detail = check_day_state(date)
    cfg_ok, cfg_detail = _config_is_valid()

    if ok:
        print("heartbeat OK — {} · config {}".format(detail, cfg_detail))
        return 0

    text = build_alert(detail, cfg_ok, cfg_detail)
    if a.dry_run:
        print("[dry-run] would post to {}:\n{}".format(_resolve_channel(), text))
        return 1
    if _already_alerted(date) and not a.force:
        print("heartbeat: already alerted for {} — staying quiet.".format(date))
        return 1

    posted = post(text)
    if posted:
        _mark_alerted(date)
    print(text)
    return 1


if __name__ == "__main__":
    sys.exit(main())
