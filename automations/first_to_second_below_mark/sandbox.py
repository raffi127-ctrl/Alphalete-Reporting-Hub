"""Create the working tab from the real one.

NOTE (2026-09-17): the tab this module names is no longer a throwaway. Eve
promoted it to the live tab -- the report is new, so nothing was displaced --
and it keeps the SANDBOX suffix only until Rafael signs off. Do not `--refresh`
it: that deletes and re-copies, which would throw away her layout. The guard
below already refuses without `--force`.

Original purpose follows.

A duplicated '1st to 2nd below the mark' tab to build against.

House rule for anything new: point it at a DUPLICATE until Eve says "use the
real Sheet". The duplicate is a TAB IN THE SAME WORKBOOK, not a separate file --
the Hub's Google token holds the `spreadsheets` scope only (no Drive scope), so
it cannot create a spreadsheet at all.

ADDITIVE ONLY: this creates a clearly-named tab and never removes anything but
the sandbox tab it made itself.

    python -m automations.first_to_second_below_mark.sandbox
    python -m automations.first_to_second_below_mark.sandbox --refresh
    python -m automations.first_to_second_below_mark.sandbox --drop
"""
from __future__ import annotations

import argparse

from automations.recruiting_report import fill
from automations.first_to_second_below_mark import run as rep


def _find(sh, title: str):
    return next((w for w in sh.worksheets()
                 if w.title.strip().lower() == title.strip().lower()), None)


def ensure(*, refresh: bool = False, force: bool = False, logfn=print) -> str:
    """Make sure the sandbox tab exists. `refresh` re-copies it from the real
    tab, which DELETES whatever is there now.

    A sandbox is not scratch space: Eve formats it by hand while a report is
    being built, and a refresh threw that away once (2026-09-17). So a refresh
    of an EXISTING tab now refuses unless `force` is passed, and the caller has
    to have decided that the contents are expendable. Nothing in the report's
    own run path refreshes."""
    sh = fill.open_by_key(rep.SHEET_ID)
    existing = _find(sh, rep.SANDBOX_TAB)
    if existing is not None and not refresh:
        logfn(f"  sandbox tab: {rep.SANDBOX_TAB!r} (reusing)")
        return rep.SANDBOX_TAB
    if existing is not None and not force:
        raise SystemExit(
            f"{rep.SANDBOX_TAB!r} already exists and --refresh would DELETE it, "
            "losing any formatting done there by hand. Re-run with --force if "
            "that is really what you want, or drop --refresh to reuse the tab.")
    real = fill.worksheet_ci(sh, rep.TARGET_TAB)
    if existing is not None:
        sh.del_worksheet(existing)          # only ever the tab WE made
        logfn(f"  sandbox tab: {rep.SANDBOX_TAB!r} (re-copied from the real tab)")
    else:
        logfn(f"  sandbox tab: {rep.SANDBOX_TAB!r} (created from the real tab)")
    sh.duplicate_sheet(real.id, new_sheet_name=rep.SANDBOX_TAB,
                       insert_sheet_index=len(sh.worksheets()))
    return rep.SANDBOX_TAB


def drop(*, logfn=print) -> bool:
    sh = fill.open_by_key(rep.SHEET_ID)
    existing = _find(sh, rep.SANDBOX_TAB)
    if existing is None:
        logfn(f"  no {rep.SANDBOX_TAB!r} tab to remove")
        return False
    sh.del_worksheet(existing)
    logfn(f"  removed {rep.SANDBOX_TAB!r}")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="first_to_second_below_mark.sandbox")
    ap.add_argument("--refresh", action="store_true",
                    help="re-copy the sandbox from the real tab's current "
                         "contents -- DELETES the existing sandbox tab")
    ap.add_argument("--force", action="store_true",
                    help="allow --refresh to delete an existing sandbox tab")
    ap.add_argument("--drop", action="store_true", help="delete the sandbox tab")
    args = ap.parse_args(argv)
    if args.drop:
        drop()
        return 0
    print("OK -", ensure(refresh=args.refresh, force=args.force))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
