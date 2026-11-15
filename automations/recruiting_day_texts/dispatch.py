"""The clock's half: queue today's read on the LIGHTEST Lucy.

Run by ONE Report Library card on Lucy 1 that fires at every zone's trigger
(8 times a day, Central). Works out from each office's own clock which live
offices are due for which text, and for each mode with any due queues ONE
`rerun recruiting_day_texts --mode X --due --send` with
NO machine -- mini_control's routing (day_orchestrator/routing.py) gives it to
the least-loaded Lucy that holds AppStream, never one still on its 4am batch.
Nothing due -> nothing queued.

    python -m automations.recruiting_day_texts.dispatch            # whatever is due now
    python -m automations.recruiting_day_texts.dispatch --dry-run
"""
from __future__ import annotations

import argparse
import sys

from automations.recruiting_day_texts import run as RUN


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("morning", "showed"),
                    help="only this text (default: whichever is due)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    queued = 0
    for mode in ([a.mode] if a.mode else ["morning", "showed"]):
        due = RUN.due_offices(mode)
        if not due:
            continue
        args = "%s --mode %s --due --send" % (RUN.REPORT_ID, mode)
        RUN._log("dispatch %s: %d due (%s)" % (mode, len(due),
                                              ", ".join(o.key for o in due)))
        if a.dry_run:
            RUN._log("dry run -- would queue: rerun " + args)
            continue
        from automations.day_orchestrator import mini_control as mc
        # NOT auto=True: an auto row is pinned home by routing.pick. A plain row
        # is what lets routing move it to the lightest Lucy (Megan 2026-11-13).
        mc.enqueue("rerun", args, by="recruiting_day_texts dispatch")
        RUN._log("queued: rerun " + args + " (routing picks the Lucy)")
        queued += 1
    if not queued:
        RUN._log("dispatch: no live office due right now")
    return 0


if __name__ == "__main__":
    sys.exit(main())
