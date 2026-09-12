"""Print the exact line to send one office. Read-only.

  python -m automations.icd_alerts.invite kash
  python -m automations.icd_alerts.invite --all

WHY A COMMAND AND NOT A NOTE SOMEWHERE. The install line is the same for every
office except the code on the end, and that code lives on a tab. Copying it by
hand is the step that sent one office another office's package on 2026-09-12 --
the failure was never the software, it was a human assembling a string.

It prints the office's OWN line, ready to paste into an email, and refuses if
that office's key is switched off -- an install that completes and is then
refused by the relay is a worse first impression than being told to wait.
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, Optional

from automations.icd_alerts import offices as O, post as P

RAW = ("https://raw.githubusercontent.com/raffi127-ctrl/"
       "Alphalete-Reporting-Hub/main/automations/icd_alerts")
INSTALL = "curl -fsSL %s/install.sh | bash -s -- %%s" % RAW
UPDATE = "curl -fsSL %s/update.sh | bash" % RAW


def keys(book=None) -> Dict[str, Dict]:
    """{office: {key, active}} off the 'Relay Keys' tab."""
    if book is None:
        from automations.recruiting_report.fill import open_by_key
        book = open_by_key(P.RELAY_SPREADSHEET_ID)
    out = {}
    for row in book.worksheet("Relay Keys").get_all_values()[1:]:
        if len(row) < 3 or not (row[0] or "").strip():
            continue
        out[row[0].strip().lower()] = {
            "key": (row[1] or "").strip(),
            "active": (row[2] or "").strip().upper() in ("TRUE", "YES", "Y"),
        }
    return out


def show(office_key: str, rows: Dict, log=print) -> bool:
    office = O.get(office_key)
    rec = rows.get(office_key)
    if not office:
        log("%s is not in offices.py — add the row first." % office_key)
        return False
    if not rec or not rec["key"]:
        log("%s has no relay key on the 'Relay Keys' tab." % office_key)
        return False
    if not rec["active"]:
        log("%s's key is switched OFF. Turn Active to TRUE before sending, or "
            "their install will finish and then be refused." % office_key)
        return False

    log("")
    log("=" * 72)
    log("  %s — %s" % (office.owner, office.label))
    log("=" * 72)
    log("")
    log("  Paste this into Terminal:")
    log("")
    log("  " + INSTALL % rec["key"])
    log("")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Print an office's install line")
    ap.add_argument("office", nargs="?", help="office key, e.g. kash")
    ap.add_argument("--all", action="store_true", help="every active office")
    args = ap.parse_args(argv)

    rows = keys()
    if args.all:
        ok = [show(o.key, rows) for o in O.active()]
        print("=" * 72)
        print("\nSame for everyone, any time something changes:\n")
        print("  " + UPDATE + "\n")
        return 0 if all(ok) else 1
    if not args.office:
        ap.print_help()
        return 2
    return 0 if show(args.office, rows) else 1


if __name__ == "__main__":
    sys.exit(main())
