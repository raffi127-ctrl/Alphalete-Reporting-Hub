"""Carlos Captainship Headcount — weekly Monday hub run.

Fills a fresh week column on the "Captainship Head count" tab of the
*All In One - CARLOS* sheet with each active owner's **Rep Count**, pulled
live from Tableau (ATTTRACKER-B2B / D2D1-PAGERV3, current week). Recomputes
the Total (SUM formula) and sorts the active owners high->low.

Idempotent: if this week's column already exists it refreshes in place
instead of inserting a duplicate (override with --force-insert).

  python -m automations.carlos_captainship_headcount.run
  python -m automations.carlos_captainship_headcount.run --dry-run
  python -m automations.carlos_captainship_headcount.run --week 2026-07-05
  python -m automations.carlos_captainship_headcount.run --force-insert
  python -m automations.carlos_captainship_headcount.run --skip-download
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

from automations.recruiting_report.opt_phase_carlos import _current_we_sunday
from automations.carlos_captainship_headcount import sheet_fill, tableau_pull

REPORT_ID = "carlos_captainship_headcount"

# Lucy DMs the finished 4-week screenshot to these people on every LIVE run
# (Slack user ids — same as the carlos_captainship_bonus twin). Carlos = the
# captain, Maud = report owner.
SLACK_RECIPIENTS = ("U046G04P5LG", "U045USN7NCD")  # Carlos Hidalgo, Maud Miller
SCREENSHOT_WEEKS = 4                                 # newest week columns shown


def _slack_comment(label: str, total, owners: int) -> str:
    """DM text — emoji + Title Case title, then the headline (the image carries
    the table). Matches the Hub's metrics-post style."""
    return (f"🧮 *Carlos Captainship Headcount — WE {label}*\n"
            f"Total: {total} ({owners} owners)")


def _build_screenshot(ws, sh, we: dt.date, out_path: Path):
    """Export the past-{SCREENSHOT_WEEKS}-weeks range (names + newest weeks +
    Total) of the current sheet to a PNG at out_path. Returns (path, range)."""
    from automations.carlos_captainship_headcount import image_export
    grid, lay = sheet_fill.load_layout(ws, sh)
    rng = sheet_fill.screenshot_range(grid, lay, n_weeks=SCREENSHOT_WEEKS)
    image_export.export_png(sheet_fill.SPREADSHEET_ID, ws.id, rng, out_path)
    return out_path, rng


def _run(args) -> dict:
    we = (dt.date.fromisoformat(args.week) if args.week
          else _current_we_sunday())
    label = sheet_fill.week_label(we)
    print(f"Carlos Captainship Headcount → week ending {we} (col '{label}') "
          f"· {'DRY-RUN' if args.dry_run else 'LIVE'}", flush=True)

    # 1) Rep Counts from Tableau (live pull unless --skip-download reuses cache).
    if args.skip_download:
        counts = tableau_pull.parse_counts(tableau_pull.CACHE)
        print(f"  Tableau (cached): {len(counts)} B2B ICD rep counts", flush=True)
    else:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=True) as page:
            counts = tableau_pull.pull_rep_counts(page=page, verbose=True)
        print(f"  Tableau: {len(counts)} B2B ICD rep counts pulled", flush=True)
    if not counts:
        raise RuntimeError("Tableau returned no rep counts — aborting "
                           "(nothing filled).")

    # 2) Fill the sheet.
    ws, sh = sheet_fill.open_tab()
    rep = sheet_fill.run_fill(ws, sh, counts, we,
                              dry_run=args.dry_run,
                              force_insert=args.force_insert)

    print("\n=== " + ("PLAN" if args.dry_run else "RESULT") + " ===", flush=True)
    for line in rep["log"]:
        print(line if line.startswith("  ") else "  " + line, flush=True)
    print(f"\n  Total {rep['label']} = {rep['total']}  "
          f"({len(rep['matched'])} owners matched)", flush=True)
    if rep["ambiguous"]:
        print("  ⚠ AMBIGUOUS (pin one in sheet_fill.ALIASES): "
              + "; ".join(rep["ambiguous"]), flush=True)
    if rep["unmatched"]:
        print("  ⚠ NOT FOUND in Tableau — possible roster change; if an owner "
              "left Carlos' team move+hide their row, if new add a row: "
              + ", ".join(rep["unmatched"]), flush=True)

    # --- DELIVERY: screenshot the past-4-weeks view + DM it to Carlos + Maud ---
    # The column fill above is the critical work and is already done. Screenshot
    # + Slack DM are DELIVERY — best-effort so a Sheets/Slack hiccup (e.g. the
    # Lucy token not yet seeded on Lucy 2) never fails an otherwise-good run.
    rep["image"] = None
    rep["slack"] = None
    if not args.dry_run and not args.no_image:
        import shutil
        import tempfile
        tmpdir = Path(tempfile.mkdtemp(prefix="cch_png_"))
        try:
            from automations.carlos_captainship_headcount import image_export
            png = tmpdir / image_export.default_name(we)
            _, rng = _build_screenshot(ws, sh, we, png)
            if args.image_dir:                     # optional local copy for debug
                dest = Path(args.image_dir).expanduser() / png.name
                shutil.copy2(png, dest)
                rep["image"] = str(dest)
                print(f"\n  🖼  PNG also saved → {dest}", flush=True)
            if args.no_send:
                print(f"\n  🖼  Screenshot built ({rng}) — NOT sent (--no-send).",
                      flush=True)
            else:
                from automations.shared import slack_metrics_post as smp
                res = smp.dm_users_with_file(
                    png, users=list(SLACK_RECIPIENTS),
                    comment=_slack_comment(rep["label"], rep["total"],
                                           len(rep["matched"])),
                    as_bot=True)
                rep["slack"] = res
                print(f"\n  💬 Screenshot DM'd to Carlos + Maud via Lucy "
                      f"({res.get('mode', 'sent')}).", flush=True)
        except Exception as e:  # noqa: BLE001 — delivery must not fail the fill
            rep["slack"] = {"ok": False, "error": str(e)[:200]}
            print(f"\n  ⚠ Screenshot delivery FAILED ({type(e).__name__}: "
                  f"{str(e)[:160]}). The column IS filled — resend once the Slack "
                  f"(Lucy) token is available on this machine.", flush=True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Carlos Captainship Headcount")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + match + show the plan, write nothing")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD "
                    "(default: last completed week)")
    ap.add_argument("--force-insert", action="store_true",
                    help="insert a new column even if this week's exists")
    ap.add_argument("--skip-download", action="store_true",
                    help="reuse the cached Tableau CSV (no live pull)")
    ap.add_argument("--no-image", action="store_true",
                    help="skip the screenshot + Slack DM (sheet fill only)")
    ap.add_argument("--no-send", action="store_true",
                    help="build the screenshot but DON'T DM it (preview a live run)")
    ap.add_argument("--image-dir", default=None,
                    help="ALSO save a local PNG copy here (default: none — the "
                         "screenshot is DM'd to Carlos + Maud, not saved)")
    ap.add_argument("--preview-image", nargs="?", const="output", default=None,
                    metavar="DIR",
                    help="build the screenshot from the CURRENT sheet only (no "
                         "Tableau pull, no fill, no DM), save to DIR (default "
                         "output/), print the path, and exit")
    ap.add_argument("--send-now", action="store_true",
                    help="render the CURRENT sheet + DM it to Carlos + Maud now "
                         "(no Tableau pull, no fill) — a test send or a resend "
                         "after a delivery failure")
    ap.add_argument("--check-slack", action="store_true",
                    help="verify the Lucy Slack token on THIS machine and exit")
    args = ap.parse_args()

    if args.check_slack:
        from automations.shared import slack_metrics_post as smp
        who = smp._bot_client().auth_test()
        print(f"✅ Lucy Slack token OK here — authed as {who.get('user')} "
              f"({who.get('user_id')}) in team {who.get('team')}. "
              f"The Monday screenshot DM to Carlos + Maud will send.", flush=True)
        return 0

    if args.preview_image is not None:
        # No pull, no fill, no send — just render the CURRENT sheet for review.
        we = (dt.date.fromisoformat(args.week) if args.week
              else _current_we_sunday())
        ws, sh = sheet_fill.open_tab()
        from automations.carlos_captainship_headcount import image_export
        out_dir = Path(args.preview_image).expanduser()
        out = out_dir / image_export.default_name(we)
        _, rng = _build_screenshot(ws, sh, we, out)
        print(f"🖼  Preview screenshot ({rng}) → {out}", flush=True)
        return 0

    if args.send_now:
        # Render the CURRENT sheet + DM it — no Tableau pull, no fill. Caption
        # fields are read straight from the sheet (newest week header + Total).
        import shutil
        import tempfile
        ws, sh = sheet_fill.open_tab()
        grid, lay = sheet_fill.load_layout(ws, sh)
        wk = lay.first_week_col
        label = (grid[lay.header][wk] if len(grid[lay.header]) > wk else "").strip()
        total = (grid[lay.total][wk] if len(grid[lay.total]) > wk else "").strip()
        owners = len(lay.active)
        we = (dt.date.fromisoformat(args.week) if args.week
              else _current_we_sunday())
        tmpdir = Path(tempfile.mkdtemp(prefix="cch_png_"))
        try:
            from automations.carlos_captainship_headcount import image_export
            png = tmpdir / image_export.default_name(we)
            _, rng = _build_screenshot(ws, sh, we, png)
            from automations.shared import slack_metrics_post as smp
            res = smp.dm_users_with_file(
                png, users=list(SLACK_RECIPIENTS),
                comment=_slack_comment(label, total, owners), as_bot=True)
            print(f"💬 Screenshot ({rng}) DM'd to Carlos + Maud via Lucy "
                  f"({res.get('mode', 'sent')}, ok={res.get('ok')}).", flush=True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return 0

    rep = _run(args)
    if args.dry_run:
        print("\n(dry-run — nothing written)")
    elif rep["unmatched"] or rep["ambiguous"]:
        print("\n✅ Filled — but review the ⚠ flags above.")
    else:
        print("\n✅ Done — column filled, total recomputed, owners sorted.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ Carlos Captainship Headcount FAILED: "
              f"{type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
