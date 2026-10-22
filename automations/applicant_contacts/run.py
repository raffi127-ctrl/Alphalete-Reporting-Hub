"""Try the applicant -> reception Contacts flow without Slack.

    python -m automations.applicant_contacts.run --text "Juan Perez 214-555-0101"
    python -m automations.applicant_contacts.run --image shot.png
    python -m automations.applicant_contacts.run --image shot.png --write

Dry-run unless --write: reads reception's contacts (to show what's already
there) and prints the reply Jiraiya would send.
"""
from __future__ import annotations  # Lucy runs Python 3.9

import argparse
import mimetypes
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main(argv=None) -> int:
    from automations.applicant_contacts import contacts as K
    from automations.applicant_contacts import extract as X
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--text", default="")
    ap.add_argument("--image", action="append", default=[])
    ap.add_argument("--write", action="store_true",
                    help="actually create the contacts")
    args = ap.parse_args(argv)
    if not args.text and not args.image:
        ap.error("give --text and/or --image")
    imgs = [(Path(p).read_bytes(), mimetypes.guess_type(p)[0] or "image/png")
            for p in args.image]
    applicants = X.extract(args.text, imgs)
    print("Read:", applicants)
    rows = K.add_all(applicants, write=args.write, added_by="Hub test")
    print(K.summary(rows, write=args.write))
    return 0


if __name__ == "__main__":
    sys.exit(main())
