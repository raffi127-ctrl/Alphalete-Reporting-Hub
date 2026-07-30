"""One-off: create the 12 'Captainship - <Name>' contact groups from the lists
currently hardcoded in config.RECIPIENTS.

Run ONCE, then Eve manages the lists in Contacts and the code lists become a
dormant fallback (see distro.py).

Needs the READ-WRITE contacts token for alphaletereporting@gmail.com. That is a
one-time interactive consent — it opens a browser, so it has to be run by a
human at a screen (NOT on the mini):

    python -m automations.fiber_owners_distro.contacts_write \
        --authorize --account alphaletereporting@gmail.com

Then:

    python -m automations.captainship_drafts.seed_groups --dry-run   # plan only
    python -m automations.captainship_drafts.seed_groups            # create

Idempotent: a group that already holds the right people is left alone. Members
are matched by email, so re-running never duplicates anyone.
"""
from __future__ import annotations

import argparse
import sys

from automations.captainship_drafts import config, distro

ACCOUNT = "alphaletereporting@gmail.com"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="captainship_drafts.seed_groups")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan; create nothing.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated captain keys. Default: all 12.")
    ap.add_argument("--account", default=ACCOUNT,
                    help=f"Contacts account holding the groups (default {ACCOUNT}).")
    args = ap.parse_args(argv)

    keys = ([k.strip() for k in args.only.split(",")] if args.only
            else [c.key for c in config.CAPTAINS])
    unknown = [k for k in keys if k not in config.BY_KEY]
    if unknown:
        print(f"Unknown captain key(s): {unknown}. "
              f"Valid: {[c.key for c in config.CAPTAINS]}")
        return 1

    from automations.fiber_owners_distro import contacts_write as cw

    print(f"=== Seeding captainship contact groups in {args.account} ==="
          + (" (DRY-RUN)" if args.dry_run else ""))

    failures = 0
    for key in keys:
        name = distro.group_name(key)
        addrs = distro.code_list(key)
        # sync_group wants (email, display_name) — that order, not the other.
        target = [(a, a.split("@")[0]) for a in addrs]
        print(f"\n{key}: {name!r} <- {len(addrs)} address(es) from config.py")
        try:
            result = cw.sync_group(args.account, name, target,
                                   dry_run=args.dry_run,
                                   create_group_if_missing=True)
            print(f"  {'(dry-run) ' if args.dry_run else '✓ '}{result}")
        except Exception as e:                    # noqa: BLE001
            failures += 1
            print(f"  ✗ {key}: {type(e).__name__}: {e}")
            if "token" in str(e).lower() or "not found" in str(e).lower():
                print("     → authorize once (opens a browser, sign in as "
                      f"{args.account}):\n"
                      "       python -m automations.fiber_owners_distro."
                      f"contacts_write --authorize --account {args.account}")
                break

    if args.dry_run:
        print("\n(dry-run — nothing created. Drop --dry-run to apply.)")
        return 0
    print(f"\nDone. {failures} failure(s).")
    print("Verify with:  python -m automations.captainship_drafts.run --distro-check")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
