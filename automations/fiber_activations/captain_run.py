"""Per-captain Captainship Activations runner — daily Wed→Tue, 5 tabs.

One Tableau pull per run (country + every captain), then iterate the 5 captain
tabs writing the violet (captain) cells + the orange (country) cells. Country is
pulled ONCE and written into all 5 tabs.

  python -m automations.fiber_activations.captain_run [--dry-run] [--date YYYY-MM-DD] [--only Wayne]

--dry-run prints what WOULD be written without touching the Sheet.
--only <team> limits the run to one captain (debugging / single re-run).
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

from automations.fiber_activations import captains as C
from automations.fiber_activations import captain_pull as CP
from automations.fiber_activations import captain_fill as CF
from automations.fiber_activations import captain_render as CR
from automations.fiber_activations import drive_upload as DU
from automations.recruiting_report import fill as rfill

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "captainship_pngs"
# Where the manual run drops the finished PNGs. ~/Downloads is the standard
# cross-platform user Downloads folder (Windows + macOS + Linux).
DOWNLOADS_DIR = Path.home() / "Downloads"


def _deliver(sh, today, *, want_drive: bool, dry_run: bool) -> None:
    """Render the 6 PNGs, save them to Downloads, and (optionally) upload to
    Drive. Drive is best-effort: a failure (e.g. Drive API not enabled) is
    logged and SWALLOWED so the run still succeeds with the local copies."""
    print("\n--- Render PNGs (cols A–L minus K for captains; Q–Z for country) ---")
    imgs = CR.render_all(sh, today, OUTPUT_DIR)
    for label, path in imgs.items():
        print(f"   {label:8s} -> {path}")

    if dry_run:
        print(f"\n--- (dry-run) WOULD copy {len(imgs)} PNGs to {DOWNLOADS_DIR} ---")
        if want_drive:
            for name in DU.upload_all(list(imgs.values()), dry_run=True):
                print(f"   would-upload: {name}")
        return

    # Always save locally to Downloads.
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n--- Save {len(imgs)} PNGs to {DOWNLOADS_DIR} ---")
    for path in imgs.values():
        dest = DOWNLOADS_DIR / Path(path).name
        shutil.copy2(path, dest)
        print(f"   saved -> {dest}")

    if not want_drive:
        print("\n  (Drive upload OFF — pass --drive to also upload. PNGs are in "
              "Downloads.)")
        return

    # Optional Drive upload — never fatal.
    print(f"\n--- Upload {len(imgs)} PNGs to Drive '{C.DRIVE_FOLDER_NAME}' ---")
    try:
        results = DU.upload_all(list(imgs.values()))
        for name, status in results.items():
            print(f"   {status:8s} {name}")
    except Exception as e:
        print(f"  ⚠ Drive upload skipped — {type(e).__name__}: {str(e)[:160]}")
        print("    (Likely the Drive API isn't enabled yet. The PNGs are saved "
              "in Downloads; re-run with --drive once the API is on.)")

# Windows consoles default to cp1252; emoji status lines would crash AFTER the
# sheet write. Force UTF-8 (same guard as Raf's run.py).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _print_tab(cap, anchors, writes):
    print(f"\n--- {cap.team}  ({cap.tab}, gid {cap.gid}) ---")
    print(f"  data_row={anchors['data_row']} avg_row={anchors['avg_row']} "
          f"churn={anchors['churn_cell']} rolling={anchors['rolling_cell']} "
          f"inserted={anchors['inserted_new_row']}")
    for cell, val in writes.items():
        print(f"    {cell:5s} = {val}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="captain_run")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be written; don't touch the Sheet.")
    p.add_argument("--date", default=None, help="Override today (YYYY-MM-DD).")
    p.add_argument("--only", default=None,
                   help="Limit to one captain by team short-name (e.g. Wayne).")
    p.add_argument("--drive", action="store_true",
                   help="Also upload the PNGs to Drive (needs the Drive API "
                        "enabled in the GCP project). Off by default — PNGs "
                        "always save to your Downloads folder. Upload failures "
                        "are non-fatal.")
    args = p.parse_args(argv)

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    roster = [c for c in C.CAPTAINS
              if (args.only is None or c.team.lower() == args.only.lower())]
    if not roster:
        print(f"No captain matches --only {args.only!r}. "
              f"Known: {[c.team for c in C.CAPTAINS]}")
        return 2

    print(f"=== Captainship Activations ({'DRY-RUN' if args.dry_run else 'LIVE'}) "
          f"— {today.isoformat()} ({today.strftime('%A')}) ===")

    pull = CP.pull_run(today, verbose=False)
    print(f"Country: activations={pull.country_activations}  EOW={pull.country_eow}")
    if pull.missing:
        print(f"⚠ captains with NO data on the dashboard this run: {pull.missing} "
              f"— their tabs are skipped (no wrong number written).")

    sh = rfill.open_by_key(C.NEW_SHEET_ID)
    written = 0
    for cap in roster:
        cp = pull.captains.get(cap.team)
        if cp is None:
            print(f"\n--- {cap.team}: SKIPPED (no dashboard data) ---")
            continue
        ws = sh.worksheet(cap.tab)
        anchors = CF.find_anchors(ws, today, dry_run=args.dry_run)
        writes = CF.write_tab(
            ws, anchors, today,
            cap_activations=cp.activations, cap_eow=cp.eow,
            churn=cp.churn, appr=cp.appr,
            country_activations=pull.country_activations,
            country_eow=pull.country_eow,
            dry_run=args.dry_run,
        )
        _print_tab(cap, anchors, writes)
        written += 1

    verb = "WOULD WRITE" if args.dry_run else "WROTE"
    print(f"\n{verb} {written}/{len(roster)} captain tab(s). "
          f"(Orange Z left to formula; row 8 / formatting untouched.)")

    # Render the 6 PNGs (read-only), save to Downloads, optional non-fatal Drive.
    _deliver(sh, today, want_drive=args.drive, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
