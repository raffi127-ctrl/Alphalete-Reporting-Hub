"""Per-ICD Box Order Log — post an OWN thread for every onboarded B2B office that
enrolled "Box Order Log", each filtered to only that office's rows.

The team ALLEXP Box order-log export carries every office's energy sales in one
crosstab (with an "Owner & Office" column). We pull it ONCE, then run the normal
box_order_log report per office with `--owner-office <that office's exact Owner &
Office value>` so each office's thread shows only its own sales — the same
isolation the B2B metric views use. Carlos's existing standalone post is untouched
(it runs separately off his single-office view).

    python -m automations.box_order_log.per_office            # build only (no post)
    python -m automations.box_order_log.per_office --post     # post each office

Runs on Lucy 2 (Carlos's login — the Box Energy Tableau session lives there).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict

from automations.box_order_log import run as boxrun

# The TEAM view (all offices, owner-sliceable) Megan provisioned 2026-07-29. The
# single-office CarlosOrderLog view stays the source for Carlos's standalone post.
TEAM_VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                 "B2BBOXEnergyTracker/BoxOrderLog/"
                 "28f5e64c-6758-424d-8759-887f5c9b3ab6/ALLEXPORDERLOG?:iid=1")
TEAM_CROSSTAB_SHEET = "Order Log"
BOX_KEY = "b2b_order_log_box"


def box_offices() -> List[Dict[str, str]]:
    """Onboarded B2B offices that enrolled the Box order log, each with its exact
    Owner & Office slice value and the channel its Box thread posts to (the channel
    whose plan includes Box, else the office's primary channel)."""
    from automations.b2b_metrics import offices as bo
    out: List[Dict[str, str]] = []
    if not bo._ONBOARDED_FILE.exists():
        return out
    try:
        rows = json.loads(bo._ONBOARDED_FILE.read_text())
    except Exception:                                # noqa: BLE001
        return out
    for r in rows:
        plans = r.get("channel_plans") or []
        enrolled = set(r.get("enrolled_reports") or [])
        for p in plans:
            enrolled |= set(p.get("report_keys") or [])
        if BOX_KEY not in enrolled:
            continue
        cid, cname = r.get("channel_id", ""), r.get("channel_name", "")
        for p in plans:                              # a plan that picked Box wins
            if BOX_KEY in (p.get("report_keys") or []):
                cid = p.get("channel_id") or cid
                cname = p.get("channel_name") or cname
                break
        out.append({"key": r.get("key", ""),
                    "owner_office": (r.get("owner_office") or "").strip(),
                    "channel_id": cid, "channel_name": cname})
    return out


def probe(from_file: str = "", verbose: bool = True) -> int:
    """Verification: pull the TEAM ALLEXP view (or a file) and print every distinct
    'Owner & Office' it returns, with row counts — so we can confirm the pull sees
    ALL offices from whatever machine runs it, before enabling --post. No filter,
    no Slack."""
    import collections
    from automations.box_order_log import clean
    src = Path(from_file) if from_file else (
        boxrun.OUTPUT_DIR / "box_team_orderlog_probe_{}.csv".format(
            dt.date.today().isoformat()))
    if not from_file:
        try:
            boxrun._pull(src, verbose=verbose, view_url=TEAM_VIEW_URL,
                         crosstab_sheet=TEAM_CROSSTAB_SHEET)
        except Exception as exc:                     # noqa: BLE001
            print("[box probe] team pull failed: {}".format(exc), file=sys.stderr)
            return 1
    rows = clean.read_rows(src)
    col = clean.OWNER_OFFICE_COL
    if not rows or col not in rows[0]:
        print("[box probe] ✗ no {!r} column in the export — wrong view?".format(col))
        return 1
    counts = collections.Counter((r.get(col) or "").strip() for r in rows)
    print("[box probe] ALLEXP export has {} row(s), {} distinct office(s):".format(
        len(rows), len(counts)))
    for val, n in counts.most_common():
        print("   {:6d}  {!r}".format(n, val))
    return 0


def run_all(*, post: bool = False, weeks: int = 6, from_file: str = "",
            verbose: bool = True) -> int:
    offs = box_offices()
    if not offs:
        print("[box per-office] no onboarded B2B office enrolled the Box order log "
              "— nothing to do.")
        return 0

    # Pull the team export ONCE (unless a file is provided), then filter per office.
    src = Path(from_file) if from_file else (
        boxrun.OUTPUT_DIR / "box_team_orderlog_{}.csv".format(dt.date.today().isoformat()))
    if not from_file:
        try:
            boxrun._pull(src, verbose=verbose, view_url=TEAM_VIEW_URL,
                         crosstab_sheet=TEAM_CROSSTAB_SHEET)
        except Exception as exc:                     # noqa: BLE001
            print("[box per-office] team pull failed: {}".format(exc), file=sys.stderr)
            return 1

    rc = 0
    for o in offs:
        if not o["owner_office"] or not o["channel_id"]:
            print("[box per-office] SKIP {} — missing {}".format(
                o["key"], "owner_office" if not o["owner_office"] else "channel id"))
            continue
        cmd = [sys.executable, "-m", "automations.box_order_log.run",
               "--from-file", str(src),
               "--owner-office", o["owner_office"],
               "--channel", o["channel_id"],
               "--channel-name", o["channel_name"] or o["channel_id"],
               "--weeks", str(weeks), "--xlsx"]
        if post:
            cmd.append("--post")
        print("\n[box per-office] === {} -> {} ===".format(o["key"], o["channel_name"]))
        r = subprocess.run(cmd)
        rc = rc or r.returncode
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="box_order_log.per_office")
    ap.add_argument("--post", action="store_true", help="post each office's thread")
    ap.add_argument("--probe", action="store_true",
                    help="verify only: pull the team view and list every office it "
                         "returns (no filter, no post)")
    ap.add_argument("--weeks", type=int, default=6)
    ap.add_argument("--from-file", metavar="CSV",
                    help="use an existing TEAM export instead of pulling")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    if args.probe:
        return probe(from_file=(args.from_file or ""), verbose=not args.quiet)
    return run_all(post=args.post, weeks=args.weeks,
                   from_file=(args.from_file or ""), verbose=not args.quiet)


if __name__ == "__main__":
    sys.exit(main())
