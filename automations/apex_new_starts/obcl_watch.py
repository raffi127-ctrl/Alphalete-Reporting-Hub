"""The OBCL watcher, as its own entry point — and that is the whole point.

The Hub finds runs it did not start by scanning the process list for
`-m <a card's action module>`. The watcher used to be `run.py --watch-obcl`,
which is exactly that string, so a watcher sitting there for its two hours made
the card read RUNNING NOW the entire time and disabled its own button
(Megan, 2026-09-17: "it's stuck here").

No card names this module, so the scan does not match it. Nothing else about
the watcher changes: it is started by `--button`, looks only for text beginning
APEX-OBCL, keeps nothing else it sees, and exits when it has marked the sheet
or after two hours.
"""
from __future__ import annotations

import sys


def main() -> int:
    from automations.apex_new_starts.run import watch_obcl
    return watch_obcl()


if __name__ == "__main__":
    sys.exit(main())
