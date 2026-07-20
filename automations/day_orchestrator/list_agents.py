"""List every com.alphalete.* LaunchAgent loaded on THIS machine — a read-only
inventory, runnable via `lucy rerun list_agents --machine "Lucy 2"`.

WHY: `diag` only checks a hardcoded handful (keep-awake, session-holder,
mini-control, day-orchestrator, box-order-log), so any other agent installed on
a runner is invisible from the laptop — e.g. box_order_log carries no `machine`
tag in schedule_config yet runs on Lucy 2, which hid it from a config-based
inventory (found 2026-07-20 while lining Lucy 2's reports up for the 4am flow).
This dumps the FULL loaded set so the line-up is checked against ground truth,
not the repo's (incomplete) machine tags.

Read-only: `launchctl list` only. Never loads, unloads, or changes anything.
Output goes to the rerun log, so `lucy logtail rerun-...-list_agents` shows the
whole list untruncated.

    python -m automations.day_orchestrator.list_agents
"""
from __future__ import annotations

import subprocess
import sys


def loaded_alphalete_labels() -> list[str]:
    try:
        out = subprocess.run(["/bin/launchctl", "list"], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception as e:  # noqa: BLE001
        print(f"(launchctl list failed: {type(e).__name__})", flush=True)
        return []
    labels = set()
    for ln in out.splitlines():
        for tok in ln.split():
            if tok.startswith("com.alphalete."):
                labels.add(tok)
    return sorted(labels)


def main(argv=None) -> int:
    labels = loaded_alphalete_labels()
    print(f"{len(labels)} com.alphalete agents loaded on this machine:", flush=True)
    for lbl in labels:
        print("  " + lbl, flush=True)
    print("=== done ===", flush=True)   # clean-run sentinel for the poller
    return 0


if __name__ == "__main__":
    sys.exit(main())
