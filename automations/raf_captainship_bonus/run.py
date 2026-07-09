"""Raf Captainship Bonus — weekly hub run.

Inserts a fresh week column on the "Captainship Bonuses" tab of the
*Alphalete Org/Captainship Reports* sheet, fills each active rep's Total
Activations for Raf's team (Tableau CaptainsBonus, current cycle), sets the
team New Internet 60-day Churn % + Activation % (Rolling 4 Weeks), lets the
Total Sales / Money Made / TOTAL MONEY MADE formulas recompute, re-points the
performance chart's series at the Total Sales row, and DMs the 4-week + chart
PDF (Raf Captainship WE <M.D>.pdf) to Raf, Dylan + Maud on Slack as Lucy. The
PDF is built in a temp file and deleted after sending — nothing is saved to
Downloads (this runs unattended, where a local file is nobody's inbox). Pass
--pdf-dir to ALSO drop a local copy for debugging.

Idempotent: if this week's column already exists it refreshes in place
(override with --force-insert).

  python -m automations.raf_captainship_bonus.run
  python -m automations.raf_captainship_bonus.run --dry-run
  python -m automations.raf_captainship_bonus.run --week 2026-07-05
  python -m automations.raf_captainship_bonus.run --tab "Copy of Captainship Bonuses"
  python -m automations.raf_captainship_bonus.run --force-insert --skip-download --no-pdf
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import traceback
from pathlib import Path

REPORT_ID = "raf_captainship_bonus"

# Lucy DMs the finished PDF to these people every run (Slack user ids — same
# ids as fiber_activations / focus_slack). Raf = the captain, Maud = report
# owner, Dylan on the distro.
SLACK_RECIPIENTS = ("U045Z8N0ZQC", "U045USN7NCD", "U048V0YA5FC")  # Rafael Hidalgo, Maud Miller, Dylan


def _slack_comment(rep: dict) -> str:
    """The DM's message text — emoji + Title Case title, then the headline number
    (the PDF carries the full breakdown). Matches the Hub's metrics-post style."""
    return (f"💰 *Raf Captainship Bonus — {rep['label']}*\n"
            f"Total sales: {rep['total']} ({len(rep['matched'])} owners) · "
            f"churn {rep['churn']} · activation {rep['rolling']}")


def _current_we_sunday(today: dt.date | None = None) -> dt.date:
    """Sunday of the last completed week (matches the sheet's WE column)."""
    from automations.fiber_activations import pull as P
    today = today or dt.date.today()
    return P.cycle_sunday(today)


def _run(args) -> dict:
    if args.tab:
        os.environ["RCB_TAB"] = args.tab
    from automations.raf_captainship_bonus import sheet_fill, tableau_pull, pdf_export

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    we = dt.date.fromisoformat(args.week) if args.week else _current_we_sunday(today)
    label = sheet_fill.week_label(we)
    print(f"Raf Captainship Bonus → week ending {we} (col '{label}') · "
          f"tab '{sheet_fill.TAB}' · {'DRY-RUN' if args.dry_run else 'LIVE'}",
          flush=True)

    # 1) Tableau pull (per-rep Total Activations + team churn/rolling).
    if args.skip_download:
        pull = tableau_pull.parse_cached()
        print(f"  Tableau (cached): {len(pull.reps)} Raf reps, "
              f"grand {pull.grand_total}, churn {pull.churn}, "
              f"activation {pull.rolling}", flush=True)
    else:
        pull = tableau_pull.pull_raf(today, verbose=True)
        print(f"  Tableau: {len(pull.reps)} Raf reps pulled, "
              f"grand {pull.grand_total}, churn {pull.churn}, "
              f"activation {pull.rolling}", flush=True)
    if not pull.reps:
        raise RuntimeError("Tableau returned no Raf reps — aborting.")

    # 2) Fill the sheet.
    ws, sh = sheet_fill.open_tab()
    rep = sheet_fill.run_fill(ws, sh, pull, we, dry_run=args.dry_run,
                              force_insert=args.force_insert,
                              auto_roster=not args.no_roster)

    verb_add = "will add" if args.dry_run else "added"
    verb_hide = "will hide" if args.dry_run else "hid"
    print("\n=== " + ("PLAN" if args.dry_run else "RESULT") + " ===", flush=True)
    for line in rep["log"]:
        print(line if line.startswith("  ") else "  " + line, flush=True)
    print(f"\n  Total Sales {rep['label']} = {rep['total']}  "
          f"({len(rep['matched'])} reps)  · churn {rep['churn']} · "
          f"activation {rep['rolling']}", flush=True)
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

    # 3) PDF + Slack DM (skip on dry-run or --no-pdf).
    rep["pdf"] = None
    rep["slack"] = None
    if not args.dry_run and not args.no_pdf:
        import shutil
        import tempfile

        # The column fill above is the critical work and is already done. PDF
        # export + Slack DM are DELIVERY — keep them best-effort so a Sheets/
        # Slack hiccup (e.g. the Lucy bot token not yet seeded on this machine)
        # never fails an otherwise-good run. Failures print a loud ⚠ (surfaced
        # in the log + orchestrator email) so we notice and fix, without losing
        # the fill.
        tmpdir = Path(tempfile.mkdtemp(prefix="rcb_pdf_"))
        try:
            from automations.shared import slack_metrics_post as smp
            pdf_path = tmpdir / pdf_export.default_name(we)
            pdf_export.export_pdf(sheet_fill.SPREADSHEET_ID, ws.id, pdf_path)
            # Optional local copy for debugging — OFF by default so nothing lands
            # in Downloads on the unattended runner.
            if args.pdf_dir:
                dest = Path(args.pdf_dir).expanduser() / pdf_path.name
                shutil.copy2(pdf_path, dest)
                rep["pdf"] = str(dest)
                print(f"\n  📄 PDF also saved → {dest}", flush=True)
            res = smp.dm_users_with_file(
                pdf_path, users=list(SLACK_RECIPIENTS),
                comment=_slack_comment(rep),
                # Use the provisioned 'Lucy Reporting' USER token (slack-user-
                # token, the same one the metrics posts use) — the separate
                # bot-app token (SLACK_BOT_TOKEN) was never created on the mini,
                # so as_bot=True fails here (unlike the Carlos twin, which runs
                # on Lucy 2 where the bot token is seeded). Matches leaders_call.
                as_bot=False)
            rep["slack"] = res
            print(f"\n  💬 PDF DM'd to Raf + Dylan + Maud via Lucy "
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
    ap = argparse.ArgumentParser(description="Raf Captainship Bonus")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + match + show the plan, write nothing")
    ap.add_argument("--week", help="WE Sunday YYYY-MM-DD (default: last "
                    "completed week)")
    ap.add_argument("--today", help="override 'today' YYYY-MM-DD (drives the "
                    "Tableau Weekending filter)")
    ap.add_argument("--tab", help="target tab (default 'Captainship Bonuses'; "
                    "use 'Copy of Captainship Bonuses' to test)")
    ap.add_argument("--force-insert", action="store_true",
                    help="insert a new column even if this week's exists")
    ap.add_argument("--skip-download", action="store_true",
                    help="reuse the cached Tableau CSVs (no live pull)")
    ap.add_argument("--no-pdf", action="store_true",
                    help="skip the PDF + Slack DM entirely (sheet fill only)")
    ap.add_argument("--pdf-dir", default=None,
                    help="ALSO save a local copy of the PDF here (default: none — "
                         "the PDF is DM'd to Raf, Dylan + Maud on Slack, not saved)")
    ap.add_argument("--no-roster", action="store_true",
                    help="don't auto add/hide rows for roster changes (just flag them)")
    ap.add_argument("--check-slack", action="store_true",
                    help="verify the Lucy Slack token on THIS machine (auth_test "
                         "only — no message, no fill, no PDF) and exit")
    args = ap.parse_args()

    if args.check_slack:
        # Delivery uses the USER token (as_bot=False), so verify THAT one — the
        # bot-app token was never seeded on the mini.
        from automations.shared import slack_metrics_post as smp
        who = smp._client().auth_test()
        print(f"✅ Lucy Slack (user) token OK here — authed as {who.get('user')} "
              f"({who.get('user_id')}) in team {who.get('team')}. "
              f"The Tuesday PDF DM to Raf, Dylan + Maud will send.", flush=True)
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
        print(f"\n❌ Raf Captainship Bonus FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
