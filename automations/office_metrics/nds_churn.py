"""NDS Wireless Churn — office-level churn board for an NDS owner.

The office_metrics Wireless Churn board pulls the ATT-D2D per-rep wireless-churn
view, which is EMPTY for an NDS owner (they're not in that workbook). NDS owners'
churn lives in the NDS-SN (RES-ATT-OOF) CHURNRATES view at the OFFICE level:
0-30 / 30 / 60 / 90 day churn rate, activated wireless lines, and disconnect count.
This pulls that view, slices to one owner, and renders a small table posted as the
📊 Wireless Churn reply in today's Metrics thread — same posting path as the knocks
board (no Sheet fill needed).

  python -m automations.office_metrics.nds_churn --owner "Isaiah Revelle" --dry-run
  python -m automations.office_metrics.nds_churn --owner "Isaiah Revelle" --live
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

# opt_nds already parses this exact crosstab; reuse its reader + owner-normalizer
# rather than re-deriving them (keeps NDS churn parsing in ONE place).
from automations.alphalete_org_report.opt_nds import _read_tab_csv, _norm_owner
from automations.shared.tableau_patchright import (
    tableau_session, download_crosstab_patchright)
from automations.total_knocks.render import _draw

CHURNRATES_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                  "NDS-SNRES-ATT-OOFWorkbook/CHURNRATES/"
                  "c289786d-e0d4-4de7-825a-264c21e133c1/THISWEEK?:iid=1")
WORKSHEET = "Churn Rates (ICD)"

# CHURNRATES layout (UTF-16 tab crosstab): col0 = "OWNER[office]", col1 = status,
# col2 = metric, cols 3-6 = the four period columns below (proven from a live
# export 2026-08-05). One owner has ~4 metric rows.
PERIOD_COLS = [3, 4, 5, 6]
PERIOD_LABELS = ["0-30 Day", "30 Day", "60 Day", "90 Day"]
# Metrics we render, in display order (exact col2 strings from the crosstab).
METRICS = ["Churn Rate", "Activated Wireless Lines", "Disconnect count"]

# 📊 Wireless Churn — blue, matching the bar_chart reaction the D2D board uses.
THEME_BLUE = {"title_bg": (37, 99, 175), "header_bg": (23, 42, 71),
              "stripe": (232, 240, 251)}
POST_LABEL = "📊 Wireless Churn"
POST_EMOJI = "bar_chart"


def pull(out_path: Path | None = None, verbose: bool = False) -> Path:
    """Download the NDS CHURNRATES crosstab (its own Tableau session)."""
    out_path = out_path or Path(tempfile.gettempdir()) / "nds_churn.csv"
    with tableau_session(verbose=verbose) as page:
        download_crosstab_patchright(CHURNRATES_URL, WORKSHEET, out_path,
                                     verbose=verbose, page=page)
    return out_path


def parse_owner(path: Path, owner: str) -> dict:
    """{metric: [0-30, 30, 60, 90]} for ONE owner. Empty dict if not found.

    Owner match is via opt_nds._norm_owner, which drops the "[office]" suffix and
    lowercases — so "Isaiah Revelle" matches "ISAIAH REVELLE[legacy ...]"."""
    rows = _read_tab_csv(path)
    want = _norm_owner(owner)
    out: dict = {}
    for r in rows[1:] if rows else []:
        if len(r) <= max(PERIOD_COLS):
            continue
        if _norm_owner(r[0]) != want:
            continue
        metric = (r[2] or "").strip()
        out[metric] = [(r[c] or "").strip() for c in PERIOD_COLS]
    return out


def render(owner: str, data: dict, target: dt.date, out_dir: Path) -> Path:
    """One table PNG: metrics (rows) × periods (cols)."""
    header = ["Metric", *PERIOD_LABELS]
    body = [[m, *data.get(m, ["", "", "", ""])] for m in METRICS]
    # Cross-platform date (no %-d): "Aug 5, 2026".
    title = f"WIRELESS CHURN — {target.strftime('%b')} {target.day}, {target.year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"nds_wireless_churn_{target.isoformat()}.png"
    return _draw(header, body, title, THEME_BLUE, out_path, name_col=0)


def run(owner: str, *, target: dt.date | None = None, dry_run: bool = False,
        out_dir: Path | None = None, verbose: bool = False) -> int:
    target = target or dt.date.today()
    out_dir = out_dir or (Path(__file__).resolve().parents[2] / "output"
                          / "nds_churn")
    csv_path = pull(verbose=verbose)
    data = parse_owner(csv_path, owner)
    print(f"[nds_churn] {owner} — {len(data)} metric row(s): {sorted(data)}",
          flush=True)

    if not data:
        # No churn row for this owner today — post (or describe) a one-liner,
        # same convention as the knocks board.
        text = (f"{POST_LABEL} — {target.strftime('%b')} {target.day} "
                f"— No data available")
        if dry_run:
            print(f"[nds_churn] --dry-run — would post: {text}", flush=True)
            return 0
        from automations.shared.slack_metrics_post import post_reply_text_only
        post_reply_text_only(text, react_emoji=POST_EMOJI)
        return 0

    img = render(owner, data, target, out_dir)
    print(f"[nds_churn] Rendered -> {img}", flush=True)
    if dry_run:
        print("[nds_churn] --dry-run — rendered only, NO Slack post.", flush=True)
        return 0

    from automations.shared.slack_metrics_post import post_reply_with_image
    comment = f"{POST_LABEL} — {target.strftime('%b')} {target.day}"
    resp = post_reply_with_image(Path(img), comment=comment,
                                 react_emoji=POST_EMOJI)
    print(f"[nds_churn] {'✅ Posted' if resp.get('ok') else '⚠ ' + str(resp)}",
          flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="office_metrics.nds_churn",
                                 description="NDS office-level Wireless Churn board.")
    ap.add_argument("--owner", required=True, help="office owner name, e.g. "
                    "'Isaiah Revelle' (matched loosely against the crosstab).")
    ap.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD (default today).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true",
                   help="pull + render, NO Slack post.")
    g.add_argument("--live", action="store_true", help="pull + render + post.")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    # Default to dry-run when neither flag is given (safe).
    return run(args.owner, target=target, dry_run=not args.live,
               verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
