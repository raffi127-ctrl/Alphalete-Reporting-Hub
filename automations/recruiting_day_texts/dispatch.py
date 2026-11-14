"""The clock's half: queue today's read on the LIGHTEST Lucy.

Run by Lucy 1's Report Library cards (one per zone trigger, all on Central
time). Works out from each office's own clock which live offices are due, and
if any are, queues ONE `rerun recruiting_day_texts --mode X --due --send` with
NO machine -- mini_control's routing (day_orchestrator/routing.py) gives it to
the least-loaded Lucy that holds AppStream, never one still on its 4am batch.
Nothing due -> nothing queued.

    python -m automations.recruiting_day_texts.dispatch --mode morning
    python -m automations.recruiting_day_texts.dispatch --mode morning --dry-run
"""
from __future__ import annotations

import argparse
import sys

from automations.recruiting_day_texts import run as RUN


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("morning", "showed"), required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    due = RUN.due_offices(a.mode)
    if not due:
        RUN._log("dispatch %s: no live office due right now" % a.mode)
        return 0
    args = "%s --mode %s --due --send" % (RUN.REPORT_ID, a.mode)
    RUN._log("dispatch %s: %d due (%s)" % (a.mode, len(due),
                                          ", ".join(o.key for o in due)))
    if a.dry_run:
        RUN._log("dry run -- would queue: rerun " + args)
        return 0
    from automations.day_orchestrator import mini_control as mc
    # NOT auto=True: an auto row is pinned home by routing.pick. A plain row is
    # what lets routing move it to the lightest Lucy (Megan 2026-11-13).
    mc.enqueue("rerun", args, by="recruiting_day_texts dispatch")
    RUN._log("queued: rerun " + args + " (routing picks the Lucy)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
