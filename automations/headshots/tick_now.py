"""Run the headshot tick once, on demand (`lucy rerun headshots_tick_now`).

Same code as the 5-min launchd tick (automations.headshots.run). It lives
under its own module name on purpose: the queue's duplicate-run guard spots a
running report by MODULE NAME, so when the launchd tick hung (2026-11-11) it
refused every rerun of automations.headshots.run -- the one thing that could
clear it. Under this name the rerun starts, and run.acquire_lock ends a run
that has held the lock for over 20 minutes.
"""
import os
import sys

from automations.headshots import run

if __name__ == "__main__":
    # A person asked for a run NOW: end whatever run holds the lock, however
    # young (Megan 2026-11-11, "just kill it").
    os.environ["HEADSHOTS_TAKE_LOCK"] = "1"
    sys.exit(run.main())
