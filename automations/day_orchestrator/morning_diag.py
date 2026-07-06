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
    return " ".join(out)


def main():
    print(f"MORNING-DIAG {dt.date.today()} :: {_orchestrator_start()} :: {_pmset()}")


if __name__ == "__main__":
    main()
