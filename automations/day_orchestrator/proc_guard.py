"""Is a copy of this report ALREADY running on this machine?

One shared answer for every launcher on the box — the manual `lucy rerun` path
(mini_control._action_rerun) and the scheduled batch (run._attempt_report_inner).
Two copies of one heavy browser report collide on the shared Chrome profile and
BOTH lose: each waits out tableau_patchright's 30-minute profile lock and then
dies at its own timeout.

WHY THIS FILE EXISTS AT ALL (Eve 2026-08-24). Both launchers already had a guard
— and both were silently dead on macOS. They ran:

    pgrep -f "-m automations.captainship_drafts.run"

with the pattern passed as its own argv element. BSD pgrep parses that leading
`-m` as an OPTION, not as the pattern:

    $ pgrep -f "-m automations.foo"
    pgrep: illegal option -- m        (exit 2, nothing on stdout)

Both callers read stdout, saw "", and concluded "nothing is running" — every
time, for every report, on every machine in the fleet. That is how 2026-08-24
ran THREE copies of captainship_drafts at once (Eve's 09:11 manual rerun, then
the orchestrator at 09:14 and again at 09:18): the guards weren't bypassed, they
were answering "" to a question they never got to ask. A guard that fails OPEN
and says nothing is the worst kind, so the pattern below is built so it can
never start with a dash again:

  • "[-]m …" — a bracket expression matching a literal '-'. It is a normal ERE
    on every pgrep (BSD + procps) and, unlike `--` separators, does not depend
    on the local pgrep supporting option termination at all.
  • the module's dots are escaped, so 'automations.a.b' can't match
    'automations_a_b';
  • "( |$)" anchors the end, so '…captainship_drafts.run' doesn't match a
    longer '…captainship_drafts.run_v2'.

PRECISION: pgrep -f matches the WHOLE command line, so a wrapper shell
(`zsh -c '… python -m automations.x …'`) or a grep for the module name matches
too. A false "busy" costs a real deferral, so each hit is confirmed with `ps`:
only a process whose argv[0] is a python binary counts.

SCOPE — this answers a question about the MODULE, not about one report. A
multi-tenant module (automations.office_metrics.runner, shared by all 39
office-metrics reports on Lucy 4, differing only in `--office`) makes every
sibling look "busy" to every other. For a module whose runs share one browser
profile that is the CORRECT answer — they really would collide — but a caller
must not word it as "<my report> is already running", and must not spend a
retry attempt on it. See describe() and run._retry_incomplete_parts. Best-effort — if ps
can't answer we keep the pid (a spurious deferral is recoverable; a missed
collision is the 2.5-hour morning this file is named after).

Stdlib only, and NOTHING here raises: a guard that crashes takes out the run it
was protecting. Windows (and any box without pgrep) gets [] — the mini is macOS,
and a report there has no shared-profile collision to guard against.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List


def _pattern(module: str) -> str:
    """pgrep -f pattern for `python -m <module>` that never starts with a dash."""
    return "[-]m {}( |$)".format(module.replace(".", r"\."))


def _ps_command(pid: str):
    """`pid`'s full command line per ps.

    Tri-state, and the caller must keep the three apart: None means ps itself
    could not answer (we cannot tell), "" means the process is already gone,
    and a string is the command line."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", pid],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001 — caller decides what "can't tell" means
        return None
    return (out or "").strip()


def _is_python_process(pid: str) -> bool:
    """True if `pid`'s argv[0] looks like a python binary — i.e. it really is the
    `python -m <module>` run and not a shell/grep that merely mentions it.

    Tri-state on purpose: ps failing (exception) keeps the pid (we can't tell,
    so assume busy); ps returning nothing means the process is already gone, so
    it is dropped."""
    line = _ps_command(pid)
    if line is None:
        return True            # can't tell → treat it as busy
    if not line:
        return False           # exited between pgrep and here
    argv0 = line.split()[0]
    return "python" in os.path.basename(argv0).lower()


def _args_after(module: str, command: str) -> str:
    """Whatever follows `<module>` on a command line — the part that says WHICH
    run it is. "" when the module isn't on it (or ps couldn't answer)."""
    if not command:
        return ""
    toks = command.split()
    try:
        i = toks.index(module)
    except ValueError:
        return ""
    return " ".join(toks[i + 1:])


def describe(module: str, pids=None) -> str:
    """"pid 50306 (--office jacob --live)" per copy of `module` running here.

    WHY THE ARGS AND NOT JUST THE PID (Megan 2026-11-17). The pattern keys on
    the MODULE, and a module can be multi-tenant: all 39 office-metrics reports
    run `automations.office_metrics.runner`, differing only in `--office`, and
    they all live on Lucy 4. So the guard fires for a SIBLING office, and both
    callers' messages used to name the report being BLOCKED as though it were
    the one running — "lajahnik_metrics is ALREADY running here (pid 50306)"
    when what held the profile was jacob's run. That reads as a report
    relaunching itself in a loop, which is a different bug entirely and the one
    it sent a person off to chase (three refusals, ~40 minutes, before the
    module pattern explained it). The args are what tell the two apart.

    Pass `pids` when you already probed, so this doesn't re-run pgrep and
    describe a different set than the one you decided on. Best-effort: never
    raises, and falls back to the bare pid when ps can't answer."""
    pids = running_pids(module) if pids is None else list(pids)
    bits = []
    for pid in pids:
        try:
            tail = _args_after(module, _ps_command(pid) or "")
        except Exception:  # noqa: BLE001 — a message helper must never raise
            tail = ""
        bits.append("pid {}{}".format(pid, " ({})".format(tail) if tail else ""))
    return ", ".join(bits)


def running_pids(module: str) -> List[str]:
    """PIDs on this machine already running `python -m <module>`.

    [] on Windows, when pgrep is missing, or on any error — best-effort by
    design (see the module docstring). Our own pid is never reported."""
    if sys.platform == "win32":
        return []
    try:
        proc = subprocess.run(["pgrep", "-f", _pattern(module)],
                              capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001 — a guard must never raise
        return []
    # pgrep: 0 = matched, 1 = no match, >=2 = it never ran the search (bad
    # pattern, usage error). Only 0 carries pids; treating anything else as
    # "nothing running" is exactly the bug this module was written to end, so
    # >=2 is logged loudly rather than swallowed.
    if proc.returncode >= 2:
        sys.stderr.write(
            "[proc_guard] pgrep could not check for a running copy of {} "
            "(exit {}): {}\n".format(module, proc.returncode,
                                     (proc.stderr or "").strip()[:160]))
        return []
    me = str(os.getpid())
    hits = [p for p in (proc.stdout or "").split() if p and p != me]
    return [p for p in hits if _is_python_process(p)]
