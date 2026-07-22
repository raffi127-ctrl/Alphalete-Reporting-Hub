"""Clear the saved ApplicantStream browser session (the persistent
`.browser_profile`).

Safe + non-destructive: the next run just logs in again and recreates it. Use it
to (a) force a fresh login if the session went stale, or (b) remove a
wrong-identity / leftover session from a machine that no longer runs these
reports (e.g. the rcaptain session left on Lucy 2 during setup).

Run it targeted at a machine:
    lucy rerun applicant_clear_session --machine "Lucy 2"
"""
from __future__ import annotations  # Lucy 1 / mini run Python 3.9

import shutil
from pathlib import Path

from . import config


def main() -> None:
    p = Path(config.USER_DATA_DIR)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
        print(f"cleared ApplicantStream browser session: {p}")
    else:
        print(f"no browser session at {p} — nothing to clear")


if __name__ == "__main__":
    main()
