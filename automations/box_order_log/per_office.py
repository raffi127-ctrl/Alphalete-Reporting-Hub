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
    # The Box thread's three boards are separately enrollable since 2026-08-20
    # (owner-key -> run.py --sections name). Enrolling ANY of them puts the
    # office on the Box run; the run posts only the enrolled boards.
    BOX_SECTION_KEYS = {"b2b_order_log_box": "order_log",
                        "b2b_box_accepted": "accepted",
                        "b2b_box_tier_bonus": "tier_bonus"}
    for r in rows:
        plans = r.get("channel_plans") or []
        enrolled = set(r.get("enrolled_reports") or [])
        for p in plans:
            enrolled |= set(p.get("report_keys") or [])
        box_keys = enrolled & set(BOX_SECTION_KEYS)
        if not box_keys:
            continue
        cid, cname = r.get("channel_id", ""), r.get("channel_name", "")
        for p in plans:                              # a plan that picked Box wins
            if set(p.get("report_keys") or []) & set(BOX_SECTION_KEYS):
                cid = p.get("channel_id") or cid
                cname = p.get("channel_name") or cname
                break
        out.append({"key": r.get("key", ""),
                    "owner_office": (r.get("owner_office") or "").strip(),
                    "channel_id": cid, "channel_name": cname,
                    "sections": [s for k, s in BOX_SECTION_KEYS.items()
                                 if k in box_keys]})
    return out


def probe(from_file: str = "", verbose: bool = True) -> int:
    """Verification: pull the TEAM ALLEXP view (or a file) and print every distinct
    'Owner & Office' it returns, with row counts — so we can confirm the pull sees
    ALL offices from whatever machine runs it, before enabling --post. No filter,
    no Slack."""
    import collections
    from automations.box_order_log import clean
    try:
        src = _ensure_team_export(from_file, verbose)
    except Exception as exc:                          # noqa: BLE001
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

    # RAW newest sale date per office, straight off the crosstab — no collapse,
    # no status filtering. Added 2026-08-13 to answer the one question the
    # collapsed numbers can't: when Roshan's and Abel's logs suddenly stopped
    # at 8/4 and 7/30 while Carlos stayed current, was it (a) their recent rows
    # being DROPPED by clean.load as Draft / TPV Failed / Rejected QC, or (b)
    # those rows simply not being in the export at all? Same export, two very
    # different owners of the problem — us vs Smart Circle. Printing the raw max
    # beside the kept max says which, in one line, on any day it happens again.
    kept, _stats = clean.load(src)
    kept_max = {}
    for s in kept:
        o = (s.fields.get(col) or "").strip()
        if o and s.sale_date and (o not in kept_max or s.sale_date > kept_max[o]):
            kept_max[o] = s.sale_date
    print("\n[box probe] newest Sale Date per office — RAW vs KEPT:")
    for val, _n in counts.most_common():
        raws = [d for d in (clean._parse_date(r.get("Sale Date", ""))
                            for r in rows
                            if (r.get(col) or "").strip() == val) if d]
        print("   raw {}  kept {}   {!r}".format(
            max(raws) if raws else "(none)   ",
            kept_max.get(val, "(none)   "), val))

    # WHY the kept date lags the raw one. Roshan's log stopped at 8/4 on
    # 2026-08-13 while her rows ran to 8/11 — seven days present in the export
    # and dropped by clean.load. "Dropped" alone doesn't say whether that's
    # correct (genuine Drafts) or a status we've started mis-reading, so name
    # the statuses: for every office, count the raw rows dated PAST its kept
    # max, grouped by Status / sub-status. If those read Draft, the log is
    # honest and the sales just haven't firmed up. If they read anything else,
    # JUNK_STATUSES / DEAD_VERIFICATION_SUBS has drifted from the source.
    print("\n[box probe] statuses on raw rows NEWER than the kept max:")
    for val, _n in counts.most_common():
        cut = kept_max.get(val)
        if not cut:
            continue
        late = collections.Counter()
        for r in rows:
            if (r.get(col) or "").strip() != val:
                continue
            d = clean._parse_date(r.get("Sale Date", ""))
            if d and d > cut:
                late[((r.get("Status") or "").strip(),
                      (r.get("Contr. Sub-status") or "").strip())] += 1
        if not late:
            print("   {!r}: none — the export simply stops there".format(val))
            continue
        print("   {!r}: {} row(s) past {}".format(val, sum(late.values()), cut))
        for (st, sub), n in late.most_common(6):
            print("      {:5d}  Status={!r} Sub={!r}".format(n, st, sub))
    return 0


# The SHARED all-owners team export — same filename run_owner.py writes/reads, so
# Roshan's email run + this per-office Slack run + any future owner all reuse ONE
# pull. Whoever runs first that morning pulls it; everyone else reads the file.
def _shared_team_file() -> Path:
    return boxrun.OUTPUT_DIR / "box_order_log_all_{}.csv".format(
        dt.date.today().isoformat())


def _ensure_team_export(from_file: str, verbose: bool) -> Path:
    """Return a team export path, reusing today's shared file if it's already been
    pulled (by run_owner or an earlier per-office pass) — one pull serves all."""
    if from_file:
        return Path(from_file)
    shared = _shared_team_file()
    if shared.exists():
        if verbose:
            print("[box] reusing today's shared team export {} (no pull)".format(
                shared.name))
        return shared
    boxrun._pull(shared, verbose=verbose, view_url=TEAM_VIEW_URL,
                 crosstab_sheet=TEAM_CROSSTAB_SHEET)
    return shared


def run_all(*, post: bool = False, weeks: int = 6, from_file: str = "",
            verbose: bool = True) -> int:
    offs = box_offices()
    if not offs:
        print("[box per-office] no onboarded B2B office enrolled the Box order log "
              "— nothing to do.")
        return 0

    # ONE pull serves every office (reuses the shared box_order_log_all_<date>.csv).
    try:
        src = _ensure_team_export(from_file, verbose)
    except Exception as exc:                         # noqa: BLE001
        print("[box per-office] team pull failed: {}".format(exc), file=sys.stderr)
        return 1

    # Opportunistically refresh the onboarding form's Owner & Office pick list from
    # this same export (it carries every owner). Best-effort — a cache miss just
    # means the form falls back to free-text, so a failure here never sinks Box.
    try:
        from automations.office_onboarding import tableau_owners, store
        from automations.recruiting_report.fill import _client
        store.set_client(_client())
        n = tableau_owners.refresh_from_box_export(src, updated=dt.date.today().isoformat())
        if verbose and n >= 0:
            print("[box per-office] refreshed 'Tableau Owners' pick list ({} owners)".format(n))
    except Exception:                                # noqa: BLE001
        pass

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
               "--sections", ",".join(o.get("sections") or
                                      ["order_log", "accepted", "tier_bonus"]),
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
