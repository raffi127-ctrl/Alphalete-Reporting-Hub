#!/usr/bin/env python3
"""Watchdog: checks the 3 watcher processes every run, restarts any that died,
DMs Rafael on first failure (debounced so it doesn't spam).

Invoked by launchd every 5 minutes via the .heartbeat.plist LaunchAgent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

RUNTIME = Path(__file__).parent.resolve()
PROJECT = RUNTIME.parent
PY = RUNTIME / "venv" / "bin" / "python"

INBOX = RUNTIME.parent / "inbox"

# Stuck-but-alive detection: if the log hasn't been touched in this long AND
# there's work pending (or the watcher should be quietly heartbeating), kill it
# so the next tick restarts it. Audit jobs can take 60-90s legitimately, so we
# need a comfortable margin.
STUCK_SECONDS = 8 * 60


def _has_pending_inbox_audio() -> bool:
    """True if there's at least one audio file sitting in inbox/ — meaning the
    audit watcher SHOULD be doing something."""
    if not INBOX.exists():
        return False
    audio_exts = {".m4a", ".mp3", ".wav", ".mp4", ".aac", ".flac", ".ogg", ".webm", ".amr"}
    return any(p.suffix.lower() in audio_exts for p in INBOX.iterdir() if p.is_file())


WATCHERS = [
    {
        "name": "audit",
        "pid_file": RUNTIME / "watcher.pid",
        "log_file": RUNTIME / "watcher.log",
        "args": [str(PY), "audit.py", "--watch"],
        # Stuck if log idle >8 min AND inbox has files waiting
        "is_stuck": lambda log_age: log_age > STUCK_SECONDS and _has_pending_inbox_audio(),
    },
    {
        "name": "feedback",
        "pid_file": RUNTIME / "feedback_watcher.pid",
        "log_file": RUNTIME / "feedback_watcher.log",
        "args": [str(PY), "feedback_watcher.py", "--watch"],
        "is_stuck": lambda log_age: False,  # no good pending signal
    },
    {
        "name": "slack",
        "pid_file": RUNTIME / "slack_watcher.pid",
        "log_file": RUNTIME / "slack_watcher.log",
        "args": [str(PY), "slack_watcher.py"],
        "is_stuck": lambda log_age: False,  # event-driven; idle is normal
    },
]

STATE_FILE = RUNTIME / "heartbeat_state.json"
LAST_CHECK = RUNTIME / "last_heartbeat.txt"
HEARTBEAT_LOG = RUNTIME / "heartbeat.log"
ALERT_COOLDOWN = timedelta(hours=1)  # don't DM Rafael more than once/hour per watcher


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(HEARTBEAT_LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def read_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def restart_watcher(w: dict) -> bool:
    """Spawn the watcher as a fully-detached background process."""
    env = os.environ.copy()
    brew = "/opt/homebrew/lib"
    existing = env.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    env["DYLD_FALLBACK_LIBRARY_PATH"] = f"{brew}:{existing}" if existing else brew

    try:
        log_fh = open(w["log_file"], "a")
        log_fh.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [heartbeat] (re)starting watcher\n")
        log_fh.flush()
        proc = subprocess.Popen(
            w["args"],
            cwd=str(RUNTIME),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        # Give it a moment to fail fast if config is broken
        time.sleep(2)
        if proc.poll() is not None:
            log(f"  ✗ {w['name']}: died within 2s of restart (exit {proc.returncode})")
            return False
        w["pid_file"].write_text(str(proc.pid))
        log(f"  ✓ {w['name']}: restarted (PID {proc.pid})")
        return True
    except Exception as e:
        log(f"  ✗ {w['name']}: restart failed: {e}")
        return False


def dm_rafael(text: str) -> None:
    """Best-effort DM to Rafael's bot channel."""
    try:
        sys.path.insert(0, str(RUNTIME))
        # Reuse the slack_watcher's web client (already configured with bot token)
        from slack_watcher import web  # noqa
        admin_channel = os.getenv("RAFAEL_DM_CHANNEL", "D0B7AQJEFK4")
        web.chat_postMessage(channel=admin_channel, text=text)
        log(f"  → DM'd Rafael: {text[:60]}...")
    except Exception as e:
        log(f"  ✗ failed to DM Rafael: {e}")


def main() -> int:
    LAST_CHECK.write_text(datetime.now().isoformat())
    state = load_state()
    now = datetime.now()

    dead = []
    restarted = []
    failed_restart = []

    for w in WATCHERS:
        pid = read_pid(w["pid_file"])
        alive = pid is not None and is_pid_alive(pid)

        # Detect "alive but stuck" — process running, log frozen, work pending
        if alive:
            log_file = w["log_file"]
            log_age = float("inf")
            if log_file.exists():
                try:
                    log_age = time.time() - log_file.stat().st_mtime
                except OSError:
                    pass
            if w["is_stuck"](log_age):
                log(f"{w['name']}: ALIVE but STUCK (log idle {int(log_age)}s, "
                    f"work pending) — killing pid {pid} so we can restart it")
                try:
                    os.kill(pid, 15)  # SIGTERM
                    time.sleep(2)
                    if is_pid_alive(pid):
                        os.kill(pid, 9)  # SIGKILL if it didn't go quietly
                except (ProcessLookupError, PermissionError):
                    pass
                alive = False  # fall through to restart logic below
            else:
                if state.get(w["name"], {}).get("dead_since"):
                    state[w["name"]] = {"healthy_since": now.isoformat()}
                continue

        dead.append(w["name"])
        log(f"{w['name']}: DEAD (pid={pid}) — restarting")

        if restart_watcher(w):
            restarted.append(w["name"])
        else:
            failed_restart.append(w["name"])

    if not dead:
        # Everything healthy — touch state and exit
        save_state(state)
        return 0

    # We had to restart something. Decide whether to DM Rafael (debounced).
    should_alert = []
    for name in dead:
        last_alert = state.get(name, {}).get("last_alert")
        if last_alert:
            try:
                last_alert_dt = datetime.fromisoformat(last_alert)
                if now - last_alert_dt < ALERT_COOLDOWN:
                    log(f"{name}: alert suppressed (last alert {last_alert})")
                    continue
            except ValueError:
                pass
        should_alert.append(name)
        state[name] = {
            "last_alert": now.isoformat(),
            "dead_since": now.isoformat(),
        }

    if should_alert:
        lines = [":rotating_light: *Watcher health alert*"]
        for name in should_alert:
            if name in restarted:
                lines.append(f"• `{name}` watcher was dead — *I restarted it automatically*. ✓")
            elif name in failed_restart:
                lines.append(f"• `{name}` watcher was dead — *restart FAILED*. Check `.runtime/{name}_watcher.log`. ✗")
        lines.append(f"\n_Next check in ~5 min. Cooldown: 1 alert/hr/watcher._")
        dm_rafael("\n".join(lines))

    save_state(state)
    return 0 if not failed_restart else 1


if __name__ == "__main__":
    sys.exit(main())
