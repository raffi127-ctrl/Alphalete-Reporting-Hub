"""Materialize the 'Thread Plans' sheet into automations/shared/thread_plans.json
— the bridge that makes a web-admin edit live on the next reporting run WITHOUT a
git deploy.

Run it on the reporting machine (Lucy) as the FIRST step of the morning flow, so
that day's threads reflect the latest admin edits:

    python -m automations.thread_builder.sync            # sync from the sheet
    python -m automations.thread_builder.sync --dry-run  # show, don't write

SAFETY: best-effort. If the sheet can't be reached (no creds, API error), it
LEAVES the committed thread_plans.json untouched and exits 0 — a sync hiccup must
never wipe plans or block the reports. Only a SUCCESSFUL read replaces the file.
"""
from __future__ import annotations

import argparse
import sys


def _default_client():
    """The standard non-interactive Lucy Sheets client (same one the board
    reports use). None if it can't be built here."""
    try:
        from automations.recruiting_report.fill import _client
        return _client()
    except Exception as e:  # noqa: BLE001
        print("[thread_builder.sync] no Sheets client ({}: {})".format(
            type(e).__name__, e), file=sys.stderr)
        return None


def sync(client=None, *, dry_run: bool = False, verbose: bool = True) -> dict:
    """Read every plan from the sheet and write thread_plans.json. Returns the
    materialized {campaign: {office: ids}} map (empty on a failed/absent read,
    in which case the existing file is left as-is)."""
    from automations.thread_builder import store
    from automations.shared import thread_plans as tp

    gc = client or _default_client()
    if gc is None:
        if verbose:
            print("[thread_builder.sync] no client — leaving thread_plans.json "
                  "as-is (reports use the committed plans).")
        return {}
    store.set_client(gc)
    try:
        data = store.load_all()
    except Exception as e:  # noqa: BLE001 — a bad read must not wipe the file
        print("[thread_builder.sync] sheet read failed ({}: {}) — leaving "
              "thread_plans.json as-is.".format(type(e).__name__, e),
              file=sys.stderr)
        return {}

    n = sum(len(v) for v in data.values())
    if verbose:
        print("[thread_builder.sync] {} plan(s) from the sheet: {}".format(
            n, {c: list(v) for c, v in data.items()}))
    if dry_run:
        print("[thread_builder.sync] --dry-run: not writing.")
        return data
    tp.replace_all(data)
    if verbose:
        print("[thread_builder.sync] wrote {}".format(tp._path()))
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="thread_builder.sync")
    ap.add_argument("--dry-run", action="store_true",
                    help="read + print, but don't write thread_plans.json")
    args = ap.parse_args(argv)
    sync(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
