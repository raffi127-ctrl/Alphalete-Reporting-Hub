"""Scheduled 6 days out — daily run.

For each captainship (Raf, Starr): pull the Order Log custom view for YESTERDAY
(Central time), keep installs scheduled 6+ days out, overwrite that team's tab
(sorted by Owner, each Owner group its own family-gradient color), and save a
high-quality PNG of the full table to the machine's Downloads folder.

Raf only: also render a PNG filtered to Owner = 'Rafael Hidalgo' (his Local
Office) and post it in today's #alphalete-sales Metrics thread with a :calendar:
reaction. Starr is a silent sheet update (no Slack).

After the run, each captainship's full PNG is emailed from
alphaletereporting@gmail.com to that team (see email_send.py).

This report OVERWRITES prior data each run — it's a daily snapshot, no history.

Outward actions are OFF by default while building:
  --post-slack       actually post Raf's Local Office image to the Metrics thread
  --send-email       actually email both captainships their full PNG
  --email-test-to A  email for real but ONLY to address A (safe live test)
Sheet writes go to the production 'VAs' Data' Sheet (see fill.SHEET_ID).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

# Force UTF-8 console output. Shared Tableau code (opt_phase) prints arrows/
# emoji; on a Windows cp1252 console (e.g. launched outside the Hub) those
# raise UnicodeEncodeError mid-run. errors='replace' keeps any odd glyph from
# ever crashing the pull.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from automations.scheduled_6_days_out import email_send, fill, pull, render
from automations.recruiting_report import fill as rfill
from automations.shared import slack_metrics_post
from automations.shared.tableau_patchright import tableau_session

LOCAL_OFFICE_OWNER = "Rafael Hidalgo"

# Subject line per captainship. {date} is filled with yesterday in M/D/YYYY.
_SUBJECTS = {
    "raf": "{date} Scheduled 6+ Days out, Rafael Hidalgo: Captainship",
    "starr": "{date} Scheduled 6+ Days out, Starr Rodenhurst: Captainship",
}


def downloads_dir() -> Path:
    d = Path.home() / "Downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _date_tag(day: dt.date) -> str:
    return day.strftime("%Y-%m-%d")


def _subject_date(day: dt.date) -> str:
    # M/D with no year, no leading zeros (cross-platform — avoid %-m, Mac-only).
    return f"{day.month}/{day.day}"


def _email_team(team: str, png_path: Path, day: dt.date, *,
                send_email: bool, test_to: str | None) -> None:
    subject = _SUBJECTS[team].format(date=_subject_date(day))
    try:
        if test_to:
            res = email_send.send(team, png_path, subject, test_to=test_to)
            mode = f"TEST→{test_to}"
        elif send_email:
            res = email_send.send(team, png_path, subject)
            mode = "LIVE"
        else:
            res = email_send.send(team, png_path, subject, dry_run=True)
            mode = "DRY-RUN"
        print(f"  ✓ Email {team} ({mode}): {res}")
    except email_send.EmailSendError as e:
        print(f"  ⚠ Email {team} failed: {e}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scheduled_6_days_out")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't write to the Sheet (still pulls + renders PNGs).")
    p.add_argument("--post-slack", action="store_true",
                   help="Actually post Raf's Local Office image to the Metrics "
                        "thread. Off by default (logs what it WOULD post).")
    p.add_argument("--send-email", action="store_true",
                   help="Actually email both captainships their full PNG. Off "
                        "by default (writes a .eml + logs, doesn't send).")
    p.add_argument("--email-test-to", default=None,
                   help="Send the emails for REAL but only to this one address "
                        "(safe live test before emailing the whole group).")
    p.add_argument("--day", default=None,
                   help="Override the data day (YYYY-MM-DD). Default = yesterday "
                        "(Central time).")
    args = p.parse_args(argv)

    day = (dt.date.fromisoformat(args.day) if args.day
           else pull.yesterday_central())
    tag = _date_tag(day)
    dl = downloads_dir()
    slack_dry = not args.post_slack

    print(f"=== Scheduled 6 days out — data day {day.isoformat()} "
          f"(Central) ===")

    # 1) Pull both custom views in ONE Tableau session (avoids relaunching
    #    Chrome twice). load_view_url raises a clear error if views.json is
    #    missing — surface it before opening the browser.
    raf_url = pull.load_view_url("raf")
    starr_url = pull.load_view_url("starr")
    print(f"  Raf view:   {raf_url[:70]}…")
    print(f"  Starr view: {starr_url[:70]}…")

    print("Step 1: Tableau Order Log pull (Raf + Starr, 1-day range)…")
    with tableau_session(verbose=True) as page:
        raf_csv = pull.fetch_crosstab("raf", day, page=page, verbose=True)
        starr_csv = pull.fetch_crosstab("starr", day, page=page, verbose=True)
    print(f"  ✓ {raf_csv}\n  ✓ {starr_csv}")

    print("Step 2: Parse + filter (Days to Appointment >= 6, sort by Owner)…")
    raf_rows = pull.parse_and_filter(raf_csv)
    starr_rows = pull.parse_and_filter(starr_csv)
    print(f"  ✓ Raf: {len(raf_rows)} rows   Starr: {len(starr_rows)} rows")

    print("Step 3: Overwrite tabs + color Owner groups…")
    sh = rfill.open_by_key(fill.SHEET_ID)
    r1 = fill.write_tab(sh, fill.TAB_RAF, raf_rows, dry_run=args.dry_run)
    r2 = fill.write_tab(sh, fill.TAB_STARR, starr_rows, dry_run=args.dry_run)
    print(f"  ✓ Raf tab:   {r1}")
    print(f"  ✓ Starr tab: {r2}")

    print("Step 4: Render full-team PNGs → Downloads…")
    raf_png = dl / f"Scheduled 6 days out - Raf - {tag}.png"
    starr_png = dl / f"Scheduled 6 days out - Starr - {tag}.png"
    render.render(raf_rows, raf_png,
                  title=f"Scheduled 6 days out — Raf's Captainship ({tag})")
    render.render(starr_rows, starr_png,
                  title=f"Scheduled 6 days out — Starr's Captainship ({tag})")
    print(f"  ✓ {raf_png}\n  ✓ {starr_png}")

    print("Step 5: Raf Local Office (Owner = Rafael Hidalgo) → Metrics thread…")
    local_rows = [r for r in raf_rows
                  if r.get("Owner Name", "").strip().casefold()
                  == LOCAL_OFFICE_OWNER.casefold()]
    local_png = Path(tempfile.gettempdir()) / f"scheduled_6days_local_{tag}.png"
    render.render(local_rows, local_png,
                  title=f"Scheduled 6 days out — Rafael Hidalgo (Local Office) "
                        f"({tag})",
                  color_by="Rep")
    # Also keep a copy in Downloads for the record.
    render.render(local_rows, dl / f"Scheduled 6 days out - Local Office - "
                                   f"{tag}.png",
                  title=f"Scheduled 6 days out — Rafael Hidalgo (Local Office) "
                        f"({tag})",
                  color_by="Rep")
    try:
        res = slack_metrics_post.post_reply_with_image(
            local_png,
            comment="📅 Scheduled 6 days out",
            react_emoji="calendar",
            today=pull.central_today(),
            dry_run=slack_dry,
        )
        print(f"  ✓ Slack ({'DRY-RUN' if slack_dry else 'LIVE'}): {res}")
    except slack_metrics_post.SlackPostError as e:
        print(f"  ⚠ Slack post failed: {e}")

    print("Step 6: Email each captainship its full PNG…")
    _email_team("raf", raf_png, day,
                send_email=args.send_email, test_to=args.email_test_to)
    _email_team("starr", starr_png, day,
                send_email=args.send_email, test_to=args.email_test_to)

    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
