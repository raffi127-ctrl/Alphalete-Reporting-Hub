"""Lucy stall watch — say so in #claudecorrections-and-requests when a Lucy is
ALIVE but stuck.

The heartbeat watch (silent_job_watch, `standalone-mini_control_<lucy>`) only
catches a Lucy that stopped altogether. 2026-10-30 was the other kind: Lucy 3
kept beating, but something held its one ownerville session from 13:02 CT on,
so the 15-minute knocks fill (alphalete_production.tk_fill) skipped pass after
pass and Raf's Sales Board read 0 reps in the field. Nobody heard about it until
Raf did. Eve: "lo que queremos es que no vuelva a pasar".

Two questions, asked every 10 minutes from the read lane of each Lucy
(mini_control._maybe_pulse):

  1. OWNERVILLE HELD TOO LONG. The same process has held the session lock for
     OV_HELD_MIN+ minutes during selling hours. Everything that needs ownerville
     on that box (knocks fill, /knocks, gap boards) is skipping meanwhile. The
     alert names the job, read from the holder's own command line.

  2. QUEUE NOT MOVING. A main-lane row in this Lucy's own workbook has sat
     'queued' for QUEUE_WAIT_MIN+ minutes. Names what is running ahead of it.

Each opens ONE incident per Lucy per problem (a still-open key is left alone,
so the 10-minute cadence never spams) and closes it the moment it clears.

EVERY POST SAYS WHETHER SOMEONE HAS TO ACT (Eve, 2026-10-30). A job still
inside its own time limit gets cut by that limit anyway, so the post says
"clears on its own by HH:MM". A job past its limit, or with no known limit, is
probably hung, and the post says "needs someone" and how to free the box.
Nothing here stops a job itself: cutting a report mid-write can leave a Sheet
half-filled, and that call stays with a person.

COST. Two local process lookups (lsof, ps) per check — no browser, no
ownerville. The queue check reuses the rows the read lane's own poll just read
(mini_control._LAST_ROWS); it never reads the Sheet itself.

How long a holder has held the lock is tracked here by first-seen time in a
small local state file — the lock keeps no timestamp — so the clock starts at
the first check that sees it: an alert can come up to 10 minutes late, never
early.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "output" / "state" / "stall_watch.json"

# Two missed knock ticks (they run every 15 min).
OV_HELD_MIN = 30
# Local (Central) hours when a held session costs a live board. The morning
# batch holds it for long stretches by design before this.
OV_HOURS = (9, 21)
# A row can legitimately wait behind one long rerun; past this it is news.
QUEUE_WAIT_MIN = 45
# The orchestrator's default when an entry names no timeout_minutes.
DEFAULT_LIMIT_MIN = 45

_MODULE_RE = re.compile(r"-m\s+(automations\.[\w.]+)")


def _slug(machine: str) -> str:
    return str(machine).strip().lower().replace(" ", "_")


def ov_key(machine: str) -> str:
    return "standalone-lucy_stall_ov_%s" % _slug(machine)


def queue_key(machine: str) -> str:
    return "standalone-lucy_stall_queue_%s" % _slug(machine)


def _clock(t: dt.datetime) -> str:
    """'1:45 PM' — no %-I, which is glibc-only."""
    return t.strftime("%I:%M %p").lstrip("0")


# ------------------------------------------------------------- ownerville lock
def ov_holders() -> List[int]:
    """PIDs holding the ownerville session lock right now ([] if free, or where
    lsof isn't available — Windows)."""
    from automations.shared.tableau_patchright import OWNERVILLE_SESSION_LOCK
    if not Path(OWNERVILLE_SESSION_LOCK).exists():
        return []
    try:
        out = subprocess.run(["lsof", "-t", str(OWNERVILLE_SESSION_LOCK)],
                             capture_output=True, text=True,
                             timeout=10).stdout.split()
    except Exception:  # noqa: BLE001 — diagnostics never raise
        return []
    me = os.getpid()
    return sorted({int(p) for p in out if p.isdigit() and int(p) != me})


def _ps(pid: int, field: str) -> str:
    try:
        return subprocess.run(["ps", "-p", str(pid), "-o", field + "="],
                              capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def job_name(pid: int) -> str:
    """'automations.x.run' from the holder's command line, else its program
    name, else 'pid N'."""
    cmd = _ps(pid, "command")
    m = _MODULE_RE.search(cmd)
    if m:
        return m.group(1)
    if cmd:
        return Path(cmd.split()[0]).name
    return "pid %d" % pid


def parse_etime(s: str) -> Optional[int]:
    """`ps -o etime=` ([[dd-]hh:]mm:ss) as whole minutes; None if unreadable."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        days = 0
        if "-" in s:
            d, s = s.split("-", 1)
            days = int(d)
        parts = [int(x) for x in s.split(":")]
    except ValueError:
        return None
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, _ = parts[-3:]
    return days * 1440 + h * 60 + m


def ov_stall(now: dt.datetime, holders: List[int], seen: Dict[str, str],
             namer: Callable[[int], str] = job_name) -> Optional[dict]:
    """Update `seen` (pid -> first-seen ISO) in place for the current holders and
    return the stall to report, or None. Pure apart from `namer`."""
    for pid in list(seen):
        if int(pid) not in holders:
            del seen[pid]
    for pid in holders:
        seen.setdefault(str(pid), now.isoformat(timespec="seconds"))
    if not (OV_HOURS[0] <= now.hour < OV_HOURS[1]):
        return None
    worst = None
    for pid in holders:
        since = dt.datetime.fromisoformat(seen[str(pid)])
        mins = int((now - since).total_seconds() // 60)
        if mins >= OV_HELD_MIN and (worst is None or mins > worst["mins"]):
            worst = {"pid": pid, "since": since, "mins": mins}
    if worst:
        worst["job"] = namer(worst["pid"])
    return worst


# ------------------------------------------------------------------ verdicts
def limits(raw_reports: dict) -> Dict[str, int]:
    """Time limit (minutes) by module AND by report id, from the schedule
    config. A module that several entries share gets the longest."""
    out: Dict[str, int] = {}
    for rid, r in (raw_reports or {}).items():
        t = int(r.get("timeout_minutes") or DEFAULT_LIMIT_MIN)
        out[rid] = max(out.get(rid, 0), t)
        cmd = r.get("command") or []
        if cmd:
            out[cmd[0]] = max(out.get(cmd[0], 0), t)
    return out


def ov_verdict(job: str, age_min: Optional[int], now: dt.datetime,
               lim: Dict[str, int]) -> dict:
    """act=False when the holder is still inside its own limit (it gets cut by
    then anyway); act=True when it's past it or has no known limit."""
    limit = lim.get(job)
    if limit and age_min is not None and age_min < limit:
        return {"act": False, "limit": limit,
                "by": now + dt.timedelta(minutes=limit - age_min)}
    return {"act": True, "limit": limit}


def queue_verdict(q: dict, lim: Dict[str, int]) -> dict:
    """The waiting row starts when the one ahead finishes. A rerun ahead that
    is still inside its limit is just a long job; anything else is wedged."""
    ahead = q.get("running")
    if ahead and str(ahead.get("Action", "")).strip().lower() == "rerun":
        rid = (str(ahead.get("Args", "")).split() or [""])[0]
        limit = lim.get(rid)
        if limit and q["mins"] < limit + 15:
            return {"act": False, "limit": limit, "job": rid}
    return {"act": True}


# -------------------------------------------------------------------- queue
def queue_stall(rows: List[dict], now: dt.datetime,
                parse: Callable[[str], Optional[dt.datetime]],
                owns_main: Callable[[str], bool]) -> Optional[dict]:
    """The oldest main-lane row queued QUEUE_WAIT_MIN+ minutes, plus whatever is
    'running' ahead of it. None when the queue is moving."""
    oldest, running = None, None
    for r in rows:
        status = str(r.get("Status", "")).strip().lower()
        action = str(r.get("Action", "")).strip()
        if not owns_main(action):
            continue
        if status == "running":
            running = r
        if status != "queued":
            continue
        at = parse(str(r.get("Queued At", "")).strip())
        if at is None:
            continue
        mins = int((now - at).total_seconds() // 60)
        if mins >= QUEUE_WAIT_MIN and (oldest is None or mins > oldest["mins"]):
            oldest = {"row": r, "mins": mins}
    if oldest:
        oldest["running"] = running
    return oldest


def _row_text(r: Optional[dict]) -> str:
    if not r:
        return "nothing marked running"
    return "`%s` (by %s)" % (" ".join((str(r.get("Action", "")).strip() + " "
                                       + str(r.get("Args", "")).strip()).split()),
                             str(r.get("By", "")).strip())


# ------------------------------------------------------------------ messages
def ov_message(machine: str, stall: dict, v: dict) -> tuple:
    title = (":rotating_light: *%s* — ownerville tied up for %d min by `%s`"
             % (machine, stall["mins"], stall["job"]))
    if v["act"]:
        verdict = (":warning: *Needs someone.* `%s` is past its own time limit"
                   "%s, so it is probably hung and won't let go by itself. "
                   "Stop it (cancel its queue row, or kill pid %d on %s) and "
                   "the knocks and boards catch up on their next pass."
                   % (stall["job"],
                      " (%d min)" % v["limit"] if v["limit"] else
                      " (it has none on file)",
                      stall["pid"], machine))
    else:
        verdict = (":hourglass_flowing_sand: *Clears on its own* by %s at the "
                   "latest — `%s` gets cut at its %d-min limit. Nothing to do "
                   "unless it can't wait." % (_clock(v["by"]), stall["job"],
                                              v["limit"]))
    body = [verdict,
            "*Meanwhile:* everything on %s that needs ownerville skips — the "
            "15-min knocks fill (Sales Board TK column), `/knocks`, the knock "
            "boards." % machine]
    details = ["*Holder:* `%s` (pid %d), holding it since %s."
               % (stall["job"], stall["pid"], stall["since"].strftime("%H:%M")),
               "_Checked by %s every 10 min. Closes on its own when the session "
               "is free._" % machine]
    return title, body, details


def queue_message(machine: str, q: dict, v: dict) -> tuple:
    title = (":rotating_light: *%s* — a job has waited %d min in its queue"
             % (machine, q["mins"]))
    if v["act"]:
        verdict = (":warning: *Needs someone.* Nothing ahead of it looks like it "
                   "will finish on its own. Cancel the row ahead if it's hung, "
                   "or re-queue the waiting one with no `--machine` so a free "
                   "Lucy takes it.")
    else:
        verdict = (":hourglass_flowing_sand: *Clears on its own.* It's just "
                   "behind `%s`, which can take up to %d min, and starts when "
                   "that one ends. Re-queue it with no `--machine` only if it "
                   "can't wait." % (v["job"], v["limit"]))
    body = [verdict,
            "*Waiting:* %s" % _row_text(q["row"]),
            "*Running ahead of it:* %s" % _row_text(q["running"])]
    details = ["_Checked by %s every 10 min. Closes on its own when the queue "
               "moves._" % machine]
    return title, body, details


# -------------------------------------------------------------------- state
def _load() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(st: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


# -------------------------------------------------------------------- check
def check(machine: str, *, rows: Optional[List[dict]] = None,
          now: Optional[dt.datetime] = None, dry_run: bool = False) -> int:
    """Run both checks for THIS machine; open/close incidents. `rows` = the
    queue rows the poll already read (None skips the queue check rather than
    reading the Sheet). Returns how many alerts it opened. Never raises: the
    poller calling it must keep polling."""
    try:
        from automations.day_orchestrator import notify, registry as _reg
        from automations.day_orchestrator import mini_control as mc
        from automations.shared import incident_thread as inc
        cfg = _reg.load_config()
        ch = notify._corrections_channel(cfg)
        if not ch:
            return 0
        now = now or dt.datetime.now()
        lim = limits(cfg.raw.get("reports"))
        open_now = set(inc.open_keys())
        st = _load()
        opened = 0

        # 1. ownerville held
        seen = st.setdefault("ov_seen", {})
        stall = ov_stall(now, ov_holders(), seen)
        _save(st)
        key = ov_key(machine)
        if stall and key not in open_now:
            v = ov_verdict(stall["job"], parse_etime(_ps(stall["pid"], "etime")),
                           now, lim)
            title, body, details = ov_message(machine, stall, v)
            notify._incident_post(
                cfg, key=key, title=title, body=body, details=details,
                followup=[title], label="*%s ownerville*" % machine,
                needs_human=v["act"], dry_run=dry_run, tag=key)
            opened += 1
        elif not stall:
            inc.resolve_if_open(key, what="*%s* ownerville is free again"
                                % machine, channel=ch, dry_run=dry_run)

        # 2. queue not moving — only on rows the poll already read
        if rows is not None:
            q = queue_stall(rows, now.astimezone(), mc._parse_ts,
                            lambda a: mc._lane_owns(a, mc.LANE_MAIN))
            key = queue_key(machine)
            if q and key not in open_now:
                v = queue_verdict(q, lim)
                title, body, details = queue_message(machine, q, v)
                notify._incident_post(
                    cfg, key=key, title=title, body=body, details=details,
                    followup=[title], label="*%s queue*" % machine,
                    needs_human=v["act"], dry_run=dry_run, tag=key)
                opened += 1
            elif not q:
                inc.resolve_if_open(key, what="*%s* queue is moving again"
                                    % machine, channel=ch, dry_run=dry_run)
        return opened
    except Exception as e:  # noqa: BLE001
        print("stall_watch(%s) failed: %s: %s" % (machine, type(e).__name__,
                                                  str(e)[:160]))
        return 0
