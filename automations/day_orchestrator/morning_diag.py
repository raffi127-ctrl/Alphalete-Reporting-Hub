"""One-shot morning-timing diagnostic — answers "why do the reports land ~6am
instead of 4am?" Run on the mini via:  lucy rerun morning_diag

Prints a single concise line (fits the Mini Control 280-char result column):
  - START = when the 4am launchd orchestrator ACTUALLY began (from its per-run log
    filename `day-orchestrator-<date>-HHMMSS.log`). ~04:00 => the mini was awake
    (so the delay is the AppStream session, not sleep). ~06:00 => the mini was
    ASLEEP and launchd deferred the job until wake (fix = a pmset wake schedule).
  - WAKE = the mini's scheduled wake events (pmset -g sched) + the sleep timer.
  - daily_focus = how many times it was attempted + how many failed before it
    finally succeeded (many attempts+fails => AppStream session churn).
"""
from __future__ import annotations

import datetime as dt
import glob
import re
import subprocess


def _orchestrator_start() -> str:
    today = dt.date.today().isoformat()
    logs = sorted(glob.glob(f"output/logs/day-orchestrator-{today}-*.log"))
    if not logs:
        return "no-orch-log-today(did-it-run?)"
    log = logs[-1]
    m = re.search(r"-(\d{2})(\d{2})(\d{2})\.log$", log)
    start = f"{m.group(1)}:{m.group(2)}:{m.group(3)}" if m else "??"
    df = []
    try:
        df = [l for l in open(log, errors="replace").read().splitlines()
              if "daily_focus" in l]
    except Exception:
        pass
    attempts = sum(1 for l in df if "running" in l or "data ready" in l)
    fails = sum(1 for l in df if "FAILED" in l)
    done = "yes" if any("DONE" in l for l in df) else "no"
    return f"START={start} daily_focus[attempts={attempts} fails={fails} done={done}]"


def _pmset() -> str:
    out = []
    try:
        sched = subprocess.run(["pmset", "-g", "sched"], capture_output=True,
                               text=True, timeout=10).stdout
        wl = [l.strip() for l in sched.splitlines()
              if re.search(r"wake|poweron", l, re.I)]
        out.append("wake={" + ("; ".join(wl)[:90] if wl else "NONE-SCHEDULED") + "}")
    except Exception as e:
        out.append(f"pmset-sched-err={type(e).__name__}")
    try:
        g = subprocess.run(["pmset", "-g"], capture_output=True, text=True,
                           timeout=10).stdout
        m = re.search(r"^\s*sleep\s+(\d+)", g, re.M)
        out.append(f"sleep={m.group(1) if m else '?'}")
    except Exception:
        pass
    # last system Wake reason (WHY it woke ~6am) — tells sleep apart from power-on
    try:
        log = subprocess.run(["pmset", "-g", "log"], capture_output=True,
                             text=True, timeout=20).stdout
        wakes = [l for l in log.splitlines()
                 if re.search(r"\bWake\b.*due to", l) and "DarkWake" not in l]
        if wakes:
            out.append("lastwake={" + re.sub(r"\s+", " ", wakes[-1].strip())[:95] + "}")
    except Exception:
        pass
    # is a no-sleep (caffeinate) assertion held right now?
    try:
        a = subprocess.run(["pmset", "-g", "assertions"], capture_output=True,
                           text=True, timeout=10).stdout
        out.append(f"caffeinate={'yes' if 'caffeinate' in a.lower() else 'no'}")
    except Exception:
        pass
    return " ".join(out)


def _batch_state() -> str:
    """From the current orchestrator log: which reports are NOT yet DONE, any
    FAILED, and the last log line + how long ago (is the loop still alive?)."""
    import os
    today = dt.date.today().isoformat()
    logs = sorted(glob.glob(f"output/logs/day-orchestrator-{today}-*.log"))
    if not logs:
        return "no-log"
    try:
        lines = open(logs[-1], errors="replace").read().splitlines()
    except Exception:
        return "log-read-err"
    last_state = {}   # report_id -> latest status word
    fail_reason = {}  # report_id -> the "FAILED — <detail>" text
    for l in lines:
        m = re.match(r"(?:\[[^\]]+\])?\s+([a-z0-9_]+):\s+(DONE|FAILED|INCOMPLETE|"
                     r"data ready|still trying|running)(?:\s+[—-]+\s+(.*))?", l)
        if m:
            last_state[m.group(1)] = m.group(2)
            if m.group(2) == "FAILED":
                fail_reason[m.group(1)] = (m.group(3) or "").strip()[:70]
            else:
                fail_reason.pop(m.group(1), None)
    failed = [f"{r}({fail_reason.get(r, '')})" for r, s in last_state.items()
              if s == "FAILED"]
    notdone = [f"{r}:{s}" for r, s in last_state.items()
               if s in ("data ready", "running", "still trying")]
    last = lines[-1][-70:] if lines else ""
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(logs[-1])).strftime("%H:%M")
    return (f"FAILED={failed or 'none'} NOTDONE={notdone or 'none'} "
            f"lastlog@{mtime}={last!r}")


def _installed_schedule() -> str:
    """The day-orchestrator launchd job's ACTUAL loaded schedule on this mini —
    from the INSTALLED plist, not the repo template (a `git pull` updates the
    repo file but never reloads launchd, so a stale plist can keep firing at the
    old time). If this shows Hour 6, THAT'S why the batch starts at 6am even
    though the mini is awake at 4am."""
    import os
    import plistlib
    p = os.path.expanduser(
        "~/Library/LaunchAgents/com.alphalete.day-orchestrator.plist")
    if not os.path.exists(p):
        return "orch-plist=MISSING(not in ~/Library/LaunchAgents)"
    try:
        with open(p, "rb") as f:
            d = plistlib.load(f)
        sci = d.get("StartCalendarInterval")
        return f"orch-schedule={sci}"
    except Exception as e:  # noqa: BLE001
        return f"orch-plist-err={type(e).__name__}:{str(e)[:60]}"


def _boot_and_power() -> str:
    """Last boot time + the last few Sleep/Wake/power events, to tell apart
    'the mini slept and woke at 6am' (caffeinate should prevent — agent gap)
    from 'the mini rebooted/powered on at 6am' (caffeinate CAN'T prevent —
    needs a scheduled power-on). boottime ~6am today => it rebooted."""
    out = []
    try:
        bt = subprocess.run(["sysctl", "-n", "kern.boottime"],
                            capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"sec = (\d+)", bt)
        if m:
            boot = dt.datetime.fromtimestamp(int(m.group(1)))
            up_h = (dt.datetime.now() - boot).total_seconds() / 3600
            out.append(f"booted={boot.strftime('%m-%d %H:%M:%S')} (up {up_h:.1f}h)")
    except Exception as e:
        out.append(f"boottime-err={type(e).__name__}")
    # Last few Sleep/Wake/power lines from the power log — did it sleep at all
    # overnight, and why did it come up?
    try:
        log = subprocess.run(["pmset", "-g", "log"], capture_output=True,
                             text=True, timeout=25).stdout
        events = [l for l in log.splitlines()
                  if re.search(r"\b(Sleep|Wake|DarkWake)\b\s+", l)
                  and "Assertions" not in l]
        for l in events[-3:]:
            out.append("• " + re.sub(r"\s+", " ", l.strip())[:110])
    except Exception as e:
        out.append(f"pmlog-err={type(e).__name__}")
    return " ".join(out)


def main():
    import sys
    # `--pmset`: print ONLY the power diagnostic (wake schedule / sleep timer /
    # last wake reason / caffeinate assertion). The full MORNING-DIAG line gets
    # truncated to ~480 chars in the Mini Control result cell, which cuts off
    # the pmset tail — so when diagnosing "why did it start at 6am not 4am?"
    # (is keep-awake actually holding?), ask for just this. (2026-07-07.)
    if "--pmset" in sys.argv:
        print(f"PMSET {dt.date.today()} :: {_installed_schedule()} :: "
              f"{_boot_and_power()} :: {_pmset()}")
        return
    print(f"MORNING-DIAG {dt.date.today()} :: {_orchestrator_start()} :: "
          f"{_batch_state()} :: {_pmset()}")


if __name__ == "__main__":
    main()
