"""Close a stray HUMAN Google Chrome before the batch runs.

Why: the reports + the ownerville session-holder drive REAL Google Chrome
(channel="chrome") because Tableau's bot-detection blocks bundled Chromium.
macOS only allows one "primary" Google Chrome instance, so if a person leaves
their normal Chrome open on the mini, our automation launches get adopted into
it and fail with "Opening in existing browser session" (blank about:blank tabs)
— which broke every browser report on 2026-07-01.

Fix: at batch start, close any HUMAN Chrome. Automation Chrome is PROTECTED:
the holder + reports + appstream all run under a profile inside
`automations/uploaded/` (`.browser_profile`, `.browser_profile_holder`,
`.appstream_profile`), so any Chrome process whose command line contains that
path is left alone. Only the top-level browser process (no `--type=`) that is
NOT one of ours is signalled — killing it closes that Chrome and its helpers.

macOS only (the mini is a Mac). No-op elsewhere, and never raises — a guard
that crashes the batch is worse than the collision it prevents.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import List

# Any Chrome running under this path is one of ours — never touch it.
_AUTOMATION_MARKER = "automations/uploaded"
_CHROME_EXE = "Google Chrome.app/Contents/MacOS/Google Chrome"


def _stray_human_chrome_pids() -> List[int]:
    """PIDs of top-level HUMAN Chrome browser processes (main process only,
    not helper renderers, not our automation profiles)."""
    try:
        out = subprocess.run(
            ["ps", "-Ao", "pid=,command="],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return []
    pids: List[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or _CHROME_EXE not in line:
            continue
        if _AUTOMATION_MARKER in line:
            continue          # one of ours (holder / report / appstream) — protect
        if "--type=" in line:
            continue          # a helper (renderer/gpu/utility), not the main proc
        try:
            pids.append(int(line.split(None, 1)[0]))
        except ValueError:
            continue
    return pids


def close_stray_chrome(*, dry: bool = False, verbose: bool = True) -> List[int]:
    """Close stray human Chrome. Returns the PIDs acted on. macOS only; on
    other platforms (or any error) it's a quiet no-op. Never raises."""
    if sys.platform != "darwin":
        return []
    try:
        pids = _stray_human_chrome_pids()
        if not pids:
            if verbose:
                print("[chrome-guard] no stray human Chrome to close", flush=True)
            return []
        if dry:
            print(f"[chrome-guard] DRY: would close human Chrome PIDs {pids} "
                  f"(automation Chrome under {_AUTOMATION_MARKER}/ is protected)",
                  flush=True)
            return pids
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)   # graceful quit
            except ProcessLookupError:
                pass
            except Exception as e:  # noqa: BLE001
                if verbose:
                    print(f"[chrome-guard] couldn't signal PID {pid}: {e}",
                          flush=True)
        # Give Chrome a moment to fully exit before reports launch their own.
        time.sleep(3)
        # Escalate to SIGKILL for anything that ignored SIGTERM.
        for pid in _stray_human_chrome_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:  # noqa: BLE001
                pass
        if verbose:
            print(f"[chrome-guard] closed {len(pids)} stray human Chrome "
                  f"process(es): {pids}", flush=True)
        return pids
    except Exception as e:  # noqa: BLE001 — best-effort; never break the batch
        if verbose:
            print(f"[chrome-guard] skipped (error: {e})", flush=True)
        return []


def profile_holder_pids(profile: str = ".browser_profile", *,
                        orphans_only: bool = True) -> List[int]:
    """PIDs of AUTOMATION Chrome browser processes holding `profile`.

    The mirror image of _stray_human_chrome_pids: that one skips everything under
    automations/uploaded because those are ours; this one wants exactly one of
    ours — the Chrome that outlived its Python parent and still owns the
    profile's ProcessSingleton.

    Matched on the `--user-data-dir=` VALUE by EXACT directory name, never a
    substring: '.browser_profile' must not also match the session holder's
    '.browser_profile_holder' (killing the holder logs every report out).
    Same rule mini_control's chrome_unstick action uses.

    `orphans_only` (the default) additionally requires PPID 1 — reparented to
    launchd, i.e. its Python/driver parent is gone. That distinction is what
    makes this safe to fire automatically after a timeout: a run can time out
    precisely because ANOTHER report legitimately holds the profile, and killing
    that live report's Chrome would turn one late report into two broken ones.
    An orphan has no parent left to break. The manual `lucy chrome_unstick`
    stays unconditional — that one is a human deciding."""
    if sys.platform != "darwin":
        return []
    try:
        out = subprocess.run(["ps", "-Ao", "pid=,ppid=,command="],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:  # noqa: BLE001
        return []
    pids: List[int] = []
    for line in out.splitlines():
        line = line.strip()
        if _CHROME_EXE not in line or "--type=" in line:
            continue
        udd = ""
        for tok in line.split():
            if tok.startswith("--user-data-dir="):
                udd = tok.split("=", 1)[1]
                break
        if not udd or os.path.basename(udd.rstrip("/")) != profile:
            continue
        try:
            pid, ppid = (int(x) for x in line.split(None, 2)[:2])
        except ValueError:
            continue
        if orphans_only and ppid != 1:
            continue
        pids.append(pid)
    return pids


def unstick_profile(profile: str = ".browser_profile", *,
                    verbose: bool = True) -> List[int]:
    """Close any orphan automation Chrome still holding `profile`. Returns the
    PIDs acted on ([] when there was nothing to do). Never raises.

    WHY (Eve 2026-08-19): killing a browser report at its timeout does NOT take
    its Chrome with it — Playwright's browser outlives the process group — so the
    orphan keeps the shared profile's ProcessSingleton. The next run then waits
    out the full 30-minute profile lock (tableau_patchright._PROFILE_LOCK_WAIT_S)
    and gets killed at ITS timeout, leaving one more orphan. That loop cost the
    whole 2026-08-19 morning: tableau_screenshots was killed at 04:52, 05:53,
    06:50 and 07:30 and the Country Trackers reached zero channels. Clearing the
    orphan at the moment of the kill is what breaks the cycle — the retry then
    starts on a free profile instead of paying 30 minutes to fail again."""
    pids = profile_holder_pids(profile)
    if not pids:
        return []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001
            pass
    time.sleep(3)
    for pid in profile_holder_pids(profile):
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass
    if verbose:
        print(f"[chrome-guard] unstuck {profile!r}: closed PID(s) {pids}",
              flush=True)
    return pids


if __name__ == "__main__":
    # Standalone: default DRY (list only) so you can confirm it targets the
    # right process on the mini before trusting it. Pass --close to act.
    _dry = "--close" not in sys.argv
    acted = close_stray_chrome(dry=_dry)
    print(f"{'would close' if _dry else 'closed'}: {acted or 'nothing'}")
