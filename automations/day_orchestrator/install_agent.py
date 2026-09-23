"""Install (or refresh) a committed LaunchAgent on THIS machine — the manual
scheduler-mini.md step, made runnable via `lucy rerun`.

WHY this exists as a runnable module (not just a mini_control action): the mini's
control poller is a long-lived `--loop` process, so a brand-new poller action
isn't live until the process restarts — and nothing in the running poller
restarts it. But `rerun` loads schedule_config fresh and runs the target as a
SUBPROCESS (fresh code from disk), so routing the install through a (non-
scheduled) registry entry lets a new LaunchAgent go live with just
`lucy update` + `lucy rerun install_<x>_agent` — no one at the mini.

What it does for `com.alphalete.<name>`:
  1. read deploy/com.alphalete.<name>.plist, rewrite the committed laptop path to
     THIS machine's repo path,
  2. write it to ~/Library/LaunchAgents/,
  3. make the referenced wrapper .sh executable,
  4. plutil -lint it,
  5. launchctl bootout (ignore if absent) + bootstrap into gui/<uid> — a clean,
     idempotent reload,
  6. verify with launchctl print.

Only ever touches com.alphalete.* agents shipped in this repo's deploy/ — never
an arbitrary plist. Read-only w.r.t. any Google Sheet / report data.

    python -m automations.day_orchestrator.install_agent je-sunday-catchup
"""
from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER = "/Users/megan/1st Claude Folder"   # committed laptop path in the plists


# EVERY AGENT GETS A REAL FILE-DESCRIPTOR CEILING (2026-09-20).
#
# A launchd job inherits macOS's default soft limit of **256 open files**, and
# none of the 117 committed plists set one. That is low for what these agents
# actually do: on Lucy 2 the session holder's Chrome sat at 211 descriptors, and
# the mini-control poller — a process that has run for days at a time while
# shelling out, talking to Sheets and driving reports — kept hitting the wall.
# On 2026-09-18 `git_status` failed there three times with
# `OSError: [Errno 24] Too many open files`, once for another person's command,
# while the box was otherwise healthy. A limit that low turns an ordinary busy
# stretch into a fleet-visible failure.
#
# 4096 is deliberately far under this hardware's kern.maxfilesperproc (10240 on
# Lucy 2), so it cannot starve the system, and far over anything these jobs
# legitimately need — the point is that a descriptor spike stops being fatal,
# not that we expect to use them.
#
# Injected HERE rather than edited into 117 plists: this is the one place every
# agent passes through on its way to ~/Library/LaunchAgents, so a new plist can
# never be added without it. A plist that already declares its own
# SoftResourceLimits is left ALONE — a job that asked for a specific ceiling
# meant it.
FD_SOFT_LIMIT = 4096


def _with_fd_limit(plist_xml: str, label: str) -> str:
    """Return the plist with SoftResourceLimits.NumberOfFiles set, unless it
    already declares its own. Best-effort: an unparseable plist is returned
    untouched so `plutil -lint` below reports the real problem."""
    try:
        pl = plistlib.loads(plist_xml.encode())
    except Exception:  # noqa: BLE001 — let the lint step name the failure
        return plist_xml
    limits = pl.get("SoftResourceLimits")
    if isinstance(limits, dict) and "NumberOfFiles" in limits:
        return plist_xml
    if not isinstance(limits, dict):
        limits = {}
    limits["NumberOfFiles"] = FD_SOFT_LIMIT
    pl["SoftResourceLimits"] = limits
    try:
        return plistlib.dumps(pl).decode()
    except Exception:  # noqa: BLE001
        return plist_xml


def install(name: str) -> tuple[bool, str]:
    name = name.strip().replace("com.alphalete.", "").replace(".plist", "")
    if not name or "/" in name or ".." in name:
        return False, f"bad launchagent name {name!r}"
    label = f"com.alphalete.{name}"
    src = REPO_ROOT / "deploy" / f"{label}.plist"
    if not src.exists():
        return False, f"{label}.plist not found in {src.parent} — git pull first?"

    fixed = src.read_text().replace(PLACEHOLDER, str(REPO_ROOT))
    fixed = _with_fd_limit(fixed, label)
    la_dir = Path(os.path.expanduser("~/Library/LaunchAgents"))
    la_dir.mkdir(parents=True, exist_ok=True)
    dest = la_dir / f"{label}.plist"
    dest.write_text(fixed)

    # ensure the wrapper .sh is executable (git keeps 0755; belt + suspenders)
    try:
        for a in plistlib.loads(fixed.encode()).get("ProgramArguments", []):
            if isinstance(a, str) and a.endswith(".sh") and os.path.exists(a):
                os.chmod(a, os.stat(a).st_mode | stat.S_IXUSR | stat.S_IXGRP
                         | stat.S_IXOTH)
    except Exception:  # noqa: BLE001 — chmod is best-effort
        pass

    lint = subprocess.run(["plutil", "-lint", str(dest)],
                          capture_output=True, text=True, timeout=30)
    if lint.returncode != 0:
        return False, f"plutil lint failed: {(lint.stdout + lint.stderr).strip()[:160]}"

    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"

    def _loaded() -> bool:
        return subprocess.run(["launchctl", "print", target],
                              capture_output=True, text=True,
                              timeout=30).returncode == 0

    # `launchctl bootout` is ASYNCHRONOUS — it returns before the old job is fully
    # torn down. Bootstrapping immediately (as this used to) races: launchd still
    # sees the old job, the bootstrap silently no-ops, and the STALE schedule keeps
    # firing while we falsely report "loaded ✓" (it only checked the label exists).
    # That's the 2026-07-08 bug: the plist FILE said Hour 4, but launchd kept firing
    # the boot-time Hour 6 schedule for 15 days across repeated "successful" reloads.
    # Fix: bootout, then POLL until the job is genuinely gone, THEN bootstrap, and
    # fail LOUDLY (never a false ✓) if either step doesn't take.
    subprocess.run(["launchctl", "bootout", target],
                   capture_output=True, text=True, timeout=30)   # ignore if absent
    gone = False
    for _ in range(40):                     # up to ~10s for launchd to release it
        if not _loaded():
            gone = True
            break
        time.sleep(0.25)
    if not gone:
        return False, (f"{label}: old job STILL loaded 10s after bootout — launchd "
                       "won't release it (may need `launchctl remove` or a reboot); "
                       "reload aborted, schedule UNCHANGED")

    # ENABLE BEFORE BOOTSTRAP. A DISABLED label cannot be bootstrapped at all,
    # and launchd says so in the least helpful way available: `bootstrap` returns
    # exit 5 "Input/output error" and `kickstart` returns "Could not find service
    # … in domain for user gui: 501" — as if the job had never been installed.
    # Nothing in either message contains the word "disabled".
    #
    # WHAT THAT COST (2026-09-02). Lucy 1's session-holder was disabled. On a
    # code change it exited for its usual relaunch, launchd declined to bring a
    # disabled job back, and it stayed down — through the evening, with the
    # ownerville export frozen at the last good copy. The 6pm watch read the
    # stale export and paged "Session re-seed needed", which sent everyone at a
    # perfectly healthy 48h token. install_agent could not fix it either: it
    # failed with the EIO above, so the one command that should have recovered
    # the machine looked like a broken installer.
    #
    # `launchctl enable` is idempotent and a no-op on an already-enabled label,
    # and the disabled state persists across reboots — so this belongs on every
    # install, not behind a retry. Its failure is non-fatal: bootstrap's own
    # error is the better diagnostic if something else is wrong.
    en = subprocess.run(["launchctl", "enable", target],
                        capture_output=True, text=True, timeout=30)
    boot = subprocess.run(["launchctl", "bootstrap", domain, str(dest)],
                          capture_output=True, text=True, timeout=30)
    if boot.returncode != 0 or not _loaded():
        hint = ""
        if boot.returncode == 5:
            hint = (" — exit 5 is usually a DISABLED label; `launchctl enable "
                    f"{target}` was attempted first (exit {en.returncode})")
        return False, (f"{label}: bootstrap failed (exit {boot.returncode}): "
                       f"{(boot.stdout + boot.stderr).strip()[:180]}{hint}")
    # Guarantee the newly-installed agent has a Hub card, so a scheduled
    # automation can never run invisibly ("we keep losing automations" fix,
    # 2026-07-27). Confident-only (publish-id / module match) — never guesses a
    # card. Best-effort: a card hiccup must never fail an install.
    card_note = ""
    try:
        from automations.day_orchestrator import hub_coverage
        rid, why = hub_coverage._agent_report_id(name)
        if rid and not hub_coverage.resolve_card(rid, create=False):
            hub_coverage.resolve_card(rid, create=True)
            card_note = f"; auto-created Hub card for {rid!r}"
        elif rid is None and why == "unresolved":
            card_note = "; ⚠️ no Hub card could be resolved — review coverage"
    except Exception:
        pass
    return True, (f"{label} reloaded in {domain} ✓ "
                  "(race-free: old job confirmed gone before bootstrap)" + card_note)


def kick(name: str) -> tuple[bool, str]:
    """Fire an installed agent RIGHT NOW, on its own schedule's terms.

    WHY (Megan 2026-09-02). A job that only runs at 1:00 AM could not be tested
    at all: `lucy rerun` runs a report_id from schedule_config, so it reaches the
    MODULE but never the wrapper — and the recruiting chain's two-night failure
    was IN the wrapper. The only ways left were editing RunAtLoad in the plist
    and reinstalling (which leaves a job that fires on every reboot) or waiting
    until 1 AM to find out. `launchctl kickstart -k` runs the real job, with the
    real environment launchd gives it, which is the whole point of the test.

    -k restarts it if a copy is somehow already running, so this can't stack two
    chains; the wrapper's own overlap guard is the second line of defence."""
    target = f"gui/{os.getuid()}/com.alphalete.{name}"
    p = subprocess.run(["launchctl", "kickstart", "-k", target],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        return False, (f"kickstart {target} failed (exit {p.returncode}): "
                       f"{(p.stdout + p.stderr).strip()[:180]}")
    return True, (f"kickstarted {target} — it is running NOW; watch its own log "
                  f"(`lucy logtail <name>`), not this result")


def remove(name: str) -> tuple[bool, str]:
    """Unload a LaunchAgent and delete its plist -- the other half of
    install(). Built 2026-09-22 to move the ICD poster off Lucy 3: texts
    sent from that box were reaching some phones and not others (Colten,
    two of his reps) while the same messages from Lucy 1 reached everyone.
    Two boxes running the same poster would double-post, so the old one
    has to come off before the new one goes on."""
    name = name.strip().replace("com.alphalete.", "").replace(".plist", "")
    if not name or "/" in name or ".." in name:
        return False, f"bad launchagent name {name!r}"
    label = f"com.alphalete.{name}"
    dest = Path(os.path.expanduser("~/Library/LaunchAgents")) / f"{label}.plist"
    target = f"gui/{os.getuid()}/{label}"
    subprocess.run(["launchctl", "bootout", target],
                   capture_output=True, text=True, timeout=30)
    for _ in range(20):
        if subprocess.run(["launchctl", "print", target], capture_output=True,
                          text=True, timeout=30).returncode != 0:
            break
        time.sleep(0.5)
    else:
        return False, f"{label}: still loaded 10s after bootout"
    existed = dest.exists()
    if existed:
        dest.unlink()
    return True, f"{label}: unloaded" + (" and plist removed" if existed else " (no plist was installed)")


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m automations.day_orchestrator.install_agent "
              "<name> [--now | --remove]")
        return 2
    if "--remove" in args:
        name = next((a for a in args if not a.startswith("-")), "")
        ok, msg = remove(name)
        print(msg, flush=True)
        if ok:
            print("=== done ===", flush=True)
        return 0 if ok else 1
    # --now = install (refresh the plist), THEN run it immediately. Install
    # first, always: kicking the OLD job would test code that is about to be
    # replaced, which is the same false pass as running a report on a runner
    # that hasn't pulled. [[reference_lucy_update_before_testing]]
    now = "--now" in args
    name = next((a for a in args if not a.startswith("-")), "")
    ok, msg = install(name)
    print(msg, flush=True)
    if ok and now:
        ok, msg = kick(name)
        print(msg, flush=True)
    if ok:
        print("=== done ===", flush=True)   # clean-run sentinel for the poller
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
