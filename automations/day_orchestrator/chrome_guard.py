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


if __name__ == "__main__":
    # Standalone: default DRY (list only) so you can confirm it targets the
    # right process on the mini before trusting it. Pass --close to act.
    _dry = "--close" not in sys.argv
    acted = close_stray_chrome(dry=_dry)
    print(f"{'would close' if _dry else 'closed'}: {acted or 'nothing'}")
