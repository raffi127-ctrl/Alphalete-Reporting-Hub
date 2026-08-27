"""Clear today's "already checked, no number" cache so the next walk re-reads.

WHY THIS IS ITS OWN MODULE and not a flag on applicant_push.run: the rerun guard
refuses to start a second copy of a report whose module is already running
(mini_control._running_pids matches on command[0]), which is correct — two walks
collide on the shared Chrome profile and both time out. But the push walks run
nearly back-to-back inside the 7am-10pm window, so a recheck asked for through
`applicant_push` loses that race over and over (it did, ~10 times, 2026-08-27).

This module touches NO browser and NO session — it only renames two JSON caches —
so it is a different command path, finishes in about a second, and can run while a
walk is in flight without disturbing it.

WHEN TO USE IT: right after fixing the resume READ itself. The cache is
deliberately sticky (it is what stops us reopening dead-end resumes every five
minutes), but that also pins in place every applicant written off for a reason
that has since been fixed — until the date-keyed file rolls at midnight. Claudia
Ceniceros applied 2026-08-21 and was still unprocessed on 08-27 for exactly that
reason: her number is in her resume header, and the frame-blind read missed it
every single day.

  python -m automations.applicant_push.recheck                 # every office
  python -m automations.applicant_push.recheck --office 23467  # just Atef's
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import argparse
import sys

from automations.applicant_push import offices


def run(office: str = None) -> int:
    """Archive the no-number caches for one office, or for all of them."""
    from automations.oat_processing import run as oat

    targets = [office] if office else list(offices.OFFICES)
    total = 0
    for oid in targets:
        o = offices.activate(oid)
        n = oat.reset_nophone_cache()
        total += n
        print("[recheck] office %s (%s): archived %d cache file(s)"
              % (o["office_id"], o["owner"], n), flush=True)
    print("[recheck] done — %d file(s) archived across %d office(s). The next LIVE "
          "walk re-reads those resumes (a --dry-run does NOT read resumes)."
          % (total, len(targets)), flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Clear today's no-number cache so the next walk re-reads "
                    "those resumes (no browser, no sends)")
    p.add_argument("--office", default=None, choices=sorted(offices.OFFICES),
                   help="Only this office (default: every office)")
    args = p.parse_args(argv)
    return run(office=args.office)


if __name__ == "__main__":
    sys.exit(main())
