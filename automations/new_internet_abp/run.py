"""New Internet ABP% — daily run (Raf's Local Office).

Pulls the ABP crosstab from the RafLocalofficeINTABP custom view
(ATT TRACKER 2.1 - D2D → Metrics tab, pre-filtered to Raf's office),
fills the 'Local Office - New Internet ABP%' tab, then renders a
multi-week PNG and posts it into today's 7am Metrics thread in
#alphalete-sales (💳 reaction on the parent).

  python -m automations.new_internet_abp.run                # today, live
  python -m automations.new_internet_abp.run --dry-run      # no writes / no post
  python -m automations.new_internet_abp.run --skip-download
  python -m automations.new_internet_abp.run --skip-slack   # sheet-only
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

from automations.new_internet_abp import pull, fill, render

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="new_internet_abp")
    ap.add_argument("--date", default=None, help="Override date (YYYY-MM-DD).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the plan; write nothing; don't post to Slack.")
    ap.add_argument("--skip-download", action="store_true",
                    help="Reuse the cached crosstab CSV in the temp dir.")
    ap.add_argument("--force-insert", action="store_true",
                    help="Insert a fresh B+C column even if today's date is "
                         "already present (side-by-side verification).")
    ap.add_argument("--skip-slack", action="store_true",
                    help="Fill the sheet but don't post to Slack.")
    args = ap.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"=== New Internet ABP% — Local Office — {today.isoformat()} ({mode}) ===")

    # --- Pull ---
    print("Step 1: Tableau ABP crosstab pull (RafLocalofficeINTABP)...")
    if args.skip_download:
        csv_path = Path(tempfile.gettempdir()) / "new_internet_abp_local_office.csv"
        if not csv_path.exists():
            print(f"  ⚠ --skip-download but no cached CSV at {csv_path}")
            return 1
        print(f"  ✓ Reusing cached {csv_path}")
    else:
        csv_path = pull.fetch_crosstab(verbose=False)
        print(f"  ✓ {csv_path}")

    parsed = pull.parse(csv_path)
    office = parsed["office_total"]
    reps = parsed["reps"]
    n_data = sum(1 for s in reps.values() if pull.has_pct(s))
    print(f"Step 2: Parsed — office {office.get('pct','-')} "
          f"({pull.fmt_units(office) or '-'}); {n_data} reps with ABP data "
          f"({len(reps)} in roster).")
    if not office and n_data == 0:
        print("  ⚠ No ABP data parsed — aborting so we don't blank the tab.")
        return 1

    # --- Fill ---
    print(f"Step 3: Fill '{fill.TAB}'...")
    ws = fill.open_ws()
    fill.fill_office(ws, today, parsed, force_insert=args.force_insert,
                     dry_run=args.dry_run, logfn=print)

    # --- Standing terminated-rep check (advisory, never fails the run) ---
    try:
        from automations.shared import terminated_icds as ti
        names = [n for n, s in reps.items() if pull.has_pct(s)]
        ti.alert_terminated(names, "New Internet ABP%")
    except Exception as e:  # noqa: BLE001
        print(f"  (terminated check skipped: {e})")

    # --- Render + Slack ---
    if args.dry_run:
        print("Step 4: (dry-run) skipping render + Slack post.")
        print("=== done ===")
        return 0
    if args.skip_slack:
        print("Step 4: (--skip-slack) sheet filled, no Slack post.")
        print("=== done ===")
        return 0

    print("Step 4: Render PNG + post to Metrics thread...")
    from automations.shared.slack_metrics_post import post_reply_with_file, SlackPostError
    out_dir = Path(tempfile.gettempdir()) / "abp_slack_post"
    png = render.render(ws, today, out_dir / f"New Internet ABP {today:%m-%d-%Y}.png")
    print(f"  rendered {png}")
    try:
        result = post_reply_with_file(
            png,
            comment="💳 New Internet ABP %",
            react_emoji="credit_card",
            file_name=f"New Internet ABP {today:%m-%d-%Y}.png",
        )
        print(f"  posted (file={result.get('file')})")
        if not result.get("ok", True):
            print("  ✗ Slack post returned ok=false")
            return 1
    except SlackPostError as e:
        print(f"  ✗ Slack post failed: {e}")
        return 1

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
