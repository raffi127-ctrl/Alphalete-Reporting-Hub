"""NDS Rep Activations — per-rep wireless sales for an NDS owner.

The office_metrics order-log/activations board pulls the ATT-D2D workbook, which is
empty for an NDS owner. NDS per-rep sales live in the NDS-SN (RES-ATT-OOF)
ProductSalesSummaryRep view ("Sales By ICD (Weekly View)"). This pulls that view,
slices to one owner, and renders a per-rep table (each rep's WIRELESS sales by day
+ weekly total, best sellers first, zero-sellers dropped) posted as the 🆕 Rep
Activations reply in today's Metrics thread.

  python -m automations.office_metrics.nds_activations --owner "Isaiah Revelle" --dry-run
  python -m automations.office_metrics.nds_activations --owner "Isaiah Revelle" --live
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

# Reuse the proven NDS ProductSalesSummary parser + day order + owner-norm.
from automations.alphalete_org_report.opt_nds import (
    parse_rep_breakdown_per_owner, DAY_ORDER, _norm_owner)
from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)
from automations.total_knocks.render import _draw

# NDS ProductSalesSummary — "This week and last" custom view; the parser picks the
# LATEST week block. Same URL opt_nds pulls (NDS_VIEWS personal-production entry).
PSS_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
           "NDS-SNRES-ATT-OOFWorkbook/ProductSalesSummaryRep/"
           "5e31de75-1d1c-4f23-b234-4148516134c0/Thisweekandlast?:iid=1")
WORKSHEET = "Sales By ICD (Weekly View)"
DAY_ABBR = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
            "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat",
            "Sunday": "Sun"}

THEME_GREEN = {"title_bg": (21, 128, 61), "header_bg": (20, 45, 30),
               "stripe": (233, 246, 236)}
POST_LABEL = "🆕 Rep Activations"
POST_EMOJI = "new"


def pull(out_path: Path | None = None, verbose: bool = False) -> Path:
    out_path = out_path or Path(tempfile.gettempdir()) / "nds_activations.csv"
    with tableau_session(verbose=verbose) as page:
        download_crosstab_patchright(PSS_URL, WORKSHEET, out_path,
                                     verbose=verbose, page=page)
    return out_path


def reps_for(path: Path, owner: str) -> list[dict]:
    """[{rep, days{Monday..Sunday: int}, total}] for one owner, sorted by total
    desc (zero-sellers already dropped). Empty if the owner isn't present."""
    bucket = parse_rep_breakdown_per_owner(path, ptype_filter="WIRELESS")
    return bucket.get(_norm_owner(owner), [])


def render(owner: str, reps: list[dict], target: dt.date, out_dir: Path) -> Path:
    header = ["Rep", *[DAY_ABBR[d] for d in DAY_ORDER], "Total"]
    body = []
    for r in reps:
        days = r.get("days", {})
        row = [r["rep"]]
        row += [str(days.get(d, "")) for d in DAY_ORDER]
        row.append(str(r["total"]))
        body.append(row)
    title = (f"REP ACTIVATIONS (WIRELESS) — "
             f"{target.strftime('%b')} {target.day}, {target.year}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"nds_rep_activations_{target.isoformat()}.png"
    return _draw(header, body, title, THEME_GREEN, out_path, name_col=0)


def run(owner: str, *, target: dt.date | None = None, dry_run: bool = False,
        out_dir: Path | None = None, verbose: bool = False) -> int:
    target = target or dt.date.today()
    out_dir = out_dir or (Path(__file__).resolve().parents[2] / "output"
                          / "nds_activations")
    csv_path = pull(verbose=verbose)
    reps = reps_for(csv_path, owner)
    print(f"[nds_activations] {owner} — {len(reps)} rep(s) with wireless sales",
          flush=True)

    if not reps:
        text = (f"{POST_LABEL} — {target.strftime('%b')} {target.day} "
                f"— No data available")
        if dry_run:
            print(f"[nds_activations] --dry-run — would post: {text}", flush=True)
            return 0
        from automations.shared.slack_metrics_post import post_reply_text_only
        post_reply_text_only(text, react_emoji=POST_EMOJI)
        return 0

    img = render(owner, reps, target, out_dir)
    print(f"[nds_activations] Rendered -> {img}", flush=True)
    if dry_run:
        print("[nds_activations] --dry-run — rendered only, NO Slack post.",
              flush=True)
        return 0

    from automations.shared.slack_metrics_post import post_reply_with_image
    comment = f"{POST_LABEL} — {target.strftime('%b')} {target.day}"
    resp = post_reply_with_image(Path(img), comment=comment,
                                 react_emoji=POST_EMOJI)
    print(f"[nds_activations] {'✅ Posted' if resp.get('ok') else '⚠ ' + str(resp)}",
          flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="office_metrics.nds_activations",
                                 description="NDS per-rep Wireless Rep Activations board.")
    ap.add_argument("--owner", required=True)
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (default today).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--live", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    return run(args.owner, target=target, dry_run=not args.live,
               verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
