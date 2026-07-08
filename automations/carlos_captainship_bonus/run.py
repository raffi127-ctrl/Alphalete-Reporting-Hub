"""Carlos B2B Captainship Bonus — weekly hub run.

Inserts a fresh week column on the "Carlos B2B Captainship" tab of the
*All In One - CARLOS* sheet, fills each active rep's Total Activations for
Carlos' B2B team (Tableau ATTTRACKER-B2B / Captain Team, current cycle), sets
the four metric cells (team 0-30 churn %, personal 0-30 churn %, 31-60
activation %, non-payment %), lets the Total Activations / Money Made / TOTAL
AMOUNT formulas recompute, re-points the chart's series at the Total - All
Units row, and DMs the 5-week + chart PDF (Carlos Captainship Weekending
<M.D>.pdf) to Carlos + Maud on Slack as Lucy. The PDF is built in a temp
file and deleted after sending — nothing is saved to Downloads (this runs
unattended on Lucy 2, where a local file is nobody's inbox). Pass --pdf-dir
to ALSO drop a local copy for debugging.

Idempotent: re-running the same week refreshes in place (--force-insert to
override).

  python -m automations.carlos_captainship_bonus.run
  python -m automations.carlos_captainship_bonus.run --dry-run
  python -m automations.carlos_captainship_bonus.run --tab "Copy of Carlos B2B Captainship"
  python -m automations.carlos_captainship_bonus.run --week 2026-07-05 --skip-download --no-pdf
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

REPORT_ID = "carlos_captainship_bonus"

# Lucy DMs the finished PDF to these people every run (Slack user ids — same
# ids as focus_slack / leaders_call). Carlos = the captain, Maud = report owner.
SLACK_RECIPIENTS = ("U046G04P5LG", "U045USN7NCD")  # Carlos Hidalgo, Maud Miller


def _slack_comment(rep: dict) -> str:
    """The DM's message text — emoji + Title Case title, then the headline number
    (the PDF carries the full breakdown). Matches the Hub's metrics-post style."""
    return (f"💰 *Carlos B2B Captainship Bonus — {rep['label']}*\n"
            f"Total activations: {rep['total']} ({len(rep['matched'])} reps)")


def _current_we_sunday(today: dt.date | None = None) -> dt.date:
    from automations.fiber_activations import pull as P
    return P.cycle_sunday(today or dt.date.today())


def _run(args) -> dict:
    if args.tab:
        os.environ["CCB_TAB"] = args.tab
    from automations.carlos_captainship_bonus import sheet_fill, tableau_pull, pdf_export

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    we = dt.date.fromisoformat(args.week) if args.week else _current_we_sunday(today)
    label = sheet_fill.week_label(we)
    print(f"Carlos B2B Captainship → week ending {we} (col '{label}') · "
          f"tab '{sheet_fill.TAB}' · {'DRY-RUN' if args.dry_run else 'LIVE'}",
          flush=True)

    if args.skip_download:
        pull = tableau_pull.parse_cached()
        src = "cached"
    else:
        pull = tableau_pull.pull_carlos(today, verbose=True)
        src = "pulled"
    print(f"  Tableau ({src}): {len(pull.reps)} Carlos reps, team total "
          f"{pull.grand_total}, churn(team) {pull.churn_team}, churn(Carlos) "
          f"{pull.churn_personal}, activation {pull.activation}, non-pmt "
          f"{pull.nonpmt}", flush=True)
    if not pull.reps:
        raise RuntimeError("Tableau returned no Carlos reps — aborting.")

    ws, sh = sheet_fill.open_tab()
    rep = sheet_fill.run_fill(ws, sh, pull, we, dry_run=args.dry_run,
                              force_insert=args.force_insert,
                              auto_roster=not args.no_roster)

    verb_add = "will add" if args.dry_run else "added"
    verb_hide = "will hide" if args.dry_run else "hid"
    print("\n=== " + ("PLAN" if args.dry_run else "RESULT") + " ===", flush=True)
    for line in rep["log"]:
        print(line if line.startswith("  ") else "  " + line, flush=True)
    print(f"\n  Total Activations {rep['label']} = {rep['total']}  "
          f"({len(rep['matched'])} reps)", flush=True)
    if rep["ambiguous"]:
        print("  ⚠ AMBIGUOUS (pin in sheet_fill.ALIASES): "
              + "; ".join(rep["ambiguous"]), flush=True)
    if not args.no_roster:
        if rep["new_reps"]:
            print(f"  ➕ New rep(s) {verb_add} (Tableau roster, no sheet row): "
                  + ", ".join(f"{n} ({v})" for n, v in rep["new_reps"]), flush=True)
        if rep["hidden_departed"]:
            print(f"  ➖ Departed rep(s) {verb_hide} (off the Tableau roster): "
                  + ", ".join(rep["hidden_departed"]), flush=True)
    elif rep["unmatched"]:
        print("  ⚠ ACTIVE rep NOT in Tableau (roster off — handle manually): "
              + ", ".join(rep["unmatched"]), flush=True)

    rep["pdf"] = None
    rep["slack"] = None
    if not args.dry_run and not args.no_pdf:
        import shutil
        import tempfile

        # The column fill above is the critical work and is already done. PDF
        # export + Slack DM are DELIVERY — keep them best-effort so a Sheets/
        # Slack hiccup (e.g. the Lucy bot token not yet seeded on Lucy 2) never
        # fails an otherwise-good run. Failures print a loud ⚠ (surfaced in the
        # log + orchestrator email) so we notice and fix, without losing the fill.
        tmpdir = Path(tempfile.mkdtemp(prefix="ccb_pdf_"))
        try:
            from automations.shared import slack_metrics_post as smp
            pdf_path = tmpdir / pdf_export.default_name(we)
            pdf_export.export_pdf(sheet_fill.SPREADSHEET_ID, ws.id, pdf_path)
            # Optional local copy for debugging — OFF by default so nothing lands
            # in Downloads on the unattended Lucy 2 runner.
            if args.pdf_dir:
                dest = Path(args.pdf_dir).expanduser() / pdf_path.name
                shutil.copy2(pdf_path, dest)
                rep["pdf"] = str(dest)
                print(f"\n  📄 PDF also saved → {dest}", flush=True)
            res = smp.dm_users_with_file(
                pdf_path, users=list(SLACK_RECIPIENTS),
                comment=_slack_comment(rep), as_bot=True)
            rep["slack"] = res
            print(f"\n  💬 PDF DM'd to Carlos + Maud via Lucy "
                  f"({res.get('mode', 'sent')}).", flush=True)
        except Exception as e:  # noqa: BLE001 — delivery must not fail the fill
            rep["slack"] = {"ok": False, "error": str(e)[:200]}
            print(f"\n  ⚠ PDF delivery FAILED ({type(e).__name__}: "
                  f"{str(e)[:160]}). The column IS filled — resend the PDF once "
                  f"the Slack (Lucy) token is available on this machine.",
                  flush=True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Carlos B2B Captainship Bonus")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD (default last week)")
    ap.add_argument("--today", help="override 'today' YYYY-MM-DD (drives the "
                    "Tableau Weekending filter)")
    ap.add_argument("--tab", help="target tab (default 'Carlos B2B Captainship'; "
                    "use 'Copy of Carlos B2B Captainship' to test)")
    ap.add_argument("--force-insert", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--no-pdf", action="store_true",
                    help="skip the PDF + Slack DM entirely (sheet fill only)")
    ap.add_argument("--pdf-dir", default=None,
                    help="ALSO save a local copy of the PDF here (default: none — "
                         "the PDF is DM'd to Carlos + Maud on Slack, not saved)")
    ap.add_argument("--no-roster", action="store_true",
                    help="don't auto add/hide rows for roster changes (just flag them)")
    ap.add_argument("--check-slack", action="store_true",
                    help="verify the Lucy Slack token on THIS machine (auth_test "
                         "only — no message, no fill, no PDF) and exit")
    args = ap.parse_args()

    if args.check_slack:
        from automations.shared import slack_metrics_post as smp
        who = smp._bot_client().auth_test()
        print(f"✅ Lucy Slack token OK here — authed as {who.get('user')} "
              f"({who.get('user_id')}) in team {who.get('team')}. "
              f"The Tuesday PDF DM to Carlos + Maud will send.", flush=True)
        return 0

    rep = _run(args)
    if args.dry_run:
        print("\n(dry-run — nothing written)")
    elif rep["ambiguous"] or (args.no_roster and rep["unmatched"]):
        print("\n✅ Filled — but review the ⚠ flags above.")
    elif rep["new_reps"] or rep["hidden_departed"]:
        print("\n✅ Done — column filled, roster synced (see ➕/➖ above), "
              "chart re-pointed.")
    else:
        print("\n✅ Done — column filled, formulas recomputed, chart re-pointed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n❌ Carlos B2B Captainship FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
