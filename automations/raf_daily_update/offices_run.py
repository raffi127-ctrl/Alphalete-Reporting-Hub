"""The Daily Update for any office other than Raf's — same report, one office
per run, picked with --office (see offices.py).

Its own module on purpose: Raf's 5pm job (deploy/raf_daily_update.sh) starts
automations.raf_daily_update.run, and routing treats anything a deploy script
starts as scheduled, so it never leaves its machine. This entry point
(schedule id daily_update_offices) names no machine and has no timer, so a
build/fix rerun goes to the least-loaded Lucy with AppStream.

    lucy rerun daily_update_offices --office 12345            # dry preview
    lucy rerun daily_update_offices --office jairo --write --test-sheet
"""
from __future__ import annotations

import sys

from automations.raf_daily_update import run


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not any(a == "--office" or a.startswith("--office=") for a in argv):
        print("--office is required (a key from offices.py or an "
              "ApplicantStream office id)", file=sys.stderr)
        return 2
    return run.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
