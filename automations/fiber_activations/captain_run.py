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

# Run-manifest id (matches the orchestrator's verify.report_id for
# captainship_activations + the Hub card id) so a clean run verifies DONE and a
# partial run (skipped tabs) surfaces as INCOMPLETE naming them.
MANIFEST_ID = "captainship-activations"

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "captainship_pngs"
# Where the manual run drops the finished PNGs. ~/Downloads is the standard
# cross-platform user Downloads folder (Windows + macOS + Linux).
DOWNLOADS_DIR = Path.home() / "Downloads"


def _deliver(sh, today, *, want_drive: bool, dry_run: bool) -> None:
    """Render the 6 PNGs, save them to Downloads, and (optionally) upload to
    Drive. Drive is best-effort: a failure (e.g. Drive API not enabled) is
    logged and SWALLOWED so the run still succeeds with the local copies."""
    print("\n--- Render PNGs (cols A–L minus K for captains; Q–Z for country) ---")
    imgs, skipped = CR.render_all(sh, today, OUTPUT_DIR)
    for label, path in imgs.items():
        print(f"   {label:8s} -> {path}")

    if dry_run:
        print(f"\n--- (dry-run) WOULD copy {len(imgs)} PNGs to {DOWNLOADS_DIR} ---")
        if want_drive:
            for name in DU.upload_all(list(imgs.values()), dry_run=True):
                print(f"   would-upload: {name}")
        return skipped

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
        return skipped

    # Optional Drive upload — never fatal.
    print(f"\n--- Upload {len(imgs)} PNGs to Drive '{C.DRIVE_FOLDER_NAME}' ---")
    try:
        results = DU.upload_all(list(imgs.values()))
        for name, status in results.items():
            print(f"   {status:8s} {name}")
    except Exception as e:
        print(f"  ⚠ Drive upload skipped — {type(e).__name__}: {str(e)[:200]}")
        print("    (PNGs are saved in Downloads. Most likely the one-time Drive "
              "token is missing — authorize ONCE as alphaletereporting@gmail.com "
              "on this machine:  python -m automations.fiber_activations.drive_auth)")
    return skipped

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
                   help="(Deprecated — Drive upload is ON by default now. Kept "
                        "so older callers passing --drive still work.)")
    p.add_argument("--no-drive", action="store_true",
                   help="Skip the Drive upload (PNGs still save to Downloads). "
                        "Use this for a local-only run. Upload failures are "
                        "non-fatal regardless.")
    args = p.parse_args(argv)
    # Drive upload is ON by default — every live run pushes the PNGs to the
    # 'Captainship Activations - PNGs' folder (overwrite same-name + prune the
    # prior day) so Drive always mirrors Downloads. --no-drive opts out.
    want_drive = not args.no_drive

    today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    roster = [c for c in C.CAPTAINS
              if (args.only is None or c.team.lower() == args.only.lower())]
    if not roster:
        print(f"No captain matches --only {args.only!r}. "
              f"Known: {[c.team for c in C.CAPTAINS]}")
        return 2

    print(f"=== Captainship Activations ({'DRY-RUN' if args.dry_run else 'LIVE'}) "
          f"— {today.isoformat()} ({today.strftime('%A')}) ===")

    # Seed an ok=false manifest up-front for a full LIVE run so a mid-run crash
    # leaves the report non-clean (no stale-clean re-verify to DONE); mark_clean
    # at the end overwrites it. Skipped for --only (a single-captain run isn't
    # the full set) and --dry-run (no writes).
    _manifest_live = not args.dry_run and not args.only
    if _manifest_live:
        try:
            from automations.shared import run_manifest as _rm
            _rm.write_manifest(MANIFEST_ID, failed=["captainship activations"],
                               retry_args=[], kind="captain",
                               note="run started but did not complete")
        except Exception:  # noqa: BLE001 — manifest is best-effort, never fail the run
            pass

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
    skipped = _deliver(sh, today, want_drive=want_drive, dry_run=args.dry_run)

    # A tab that's missing its 'WE'/AVG header is reported per-tab and the run
    # is marked INCOMPLETE — the healthy tabs still filled + uploaded, but the
    # Hub must NOT read this as a clean run (it scans for 'run incomplete').
    if skipped:
        names = ", ".join(team for team, _ in skipped)
        print(f"\n⚠ RUN INCOMPLETE — {len(skipped)} PNG(s) not rendered: {names}")
        for team, reason in skipped:
            print(f"    • {team}: {reason}")
        print("  (The other tabs filled + uploaded fine. Fix the tab(s) above — "
              "usually a missing 'WE' header in cell A1 — then re-run.)")
        if _manifest_live:
            try:
                from automations.shared import run_manifest as _rm
                _rm.write_manifest(
                    MANIFEST_ID, failed=[team for team, _ in skipped],
                    retry_args=[], kind="captain",
                    note=f"{len(skipped)} captain tab(s) not rendered: {names}")
            except Exception:  # noqa: BLE001 — manifest is best-effort
                pass
        return 1

    # Fill + render completed cleanly — overwrite the seeded manifest so the
    # orchestrator verifies this run as DONE.
    if _manifest_live:
        try:
            from automations.shared import run_manifest as _rm
            _rm.mark_clean(MANIFEST_ID, kind="captain")
        except Exception:  # noqa: BLE001 — manifest is best-effort
            pass

    # Canonical success sentinel — the Hub scans the log for this to mark the
    # run 'success'. Without it the run reads as 'unknown' → defaulted to
    # 'failed' (dashboard.py orphan detector), even on a clean run.
    print("\n=== done (dry-run) ===" if args.dry_run else "\n=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
