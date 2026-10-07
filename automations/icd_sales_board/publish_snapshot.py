"""Refresh the snapshot that ships with the code, for the hosted page.

    python -m automations.icd_sales_board.publish_snapshot

WHY THERE IS ONE. output/ is gitignored, so a Streamlit Cloud container
starts with no snapshot and every visitor pays a cold read: about forty
serial Sheets calls against a quota the whole Hub shares. One person can
wait; a link sent to every ICD at once cannot, and they would all be
queueing behind each other on the same quota.

Run it after anything that changes who is enrolled, then commit the file
it writes. Reading it is read-only and writes nothing to any Sheet.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from automations.icd_sales_board import enrollment as EN  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Read and report, write nothing.")
    ap.add_argument("--out", default="", help="Write somewhere else.")
    args = ap.parse_args()

    if args.dry_run:
        got = EN.rows()
        print("would publish %d offices" % len(got))
        for r in got[:3]:
            print("   %s" % (r.get("ICD") or ""))
        return 0 if got else 1

    n = EN.publish_snapshot(args.out or None)
    where = Path(args.out) if args.out else EN.PUBLISHED
    print("published %d offices -> %s" % (n, where))
    print("commit that file so the hosted page ships with it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
