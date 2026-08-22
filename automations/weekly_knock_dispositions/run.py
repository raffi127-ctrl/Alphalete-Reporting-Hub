"""Weekly Knock Dispositions — Sunday runner.

    python -m automations.weekly_knock_dispositions.run             # DRY-RUN
    python -m automations.weekly_knock_dispositions.run --live      # post
    python -m automations.weekly_knock_dispositions.run --office "Rafael Hidalgo"
    python -m automations.weekly_knock_dispositions.run 2026-08-22  # that week

Dry-run is the DEFAULT — a bare run pulls + renders to output/ and cannot
post by accident (--live opts in; the two flags are mutually exclusive).

The date positional is ANY day inside the wanted Mon–Sat window; no date
means the completed week (shared.report_week — on Sunday that's the Mon–Sat
that just ended, and a Monday catch-up rerun still resolves to the same
week, not the empty new one).

Order of work: the org-wide PSS crosstab downloads FIRST in its own Tableau
session, then ONE ownerville session (own Chrome profile — the shared one is
first-come-first-served) walks the offices. One office failing never aborts
the rest; the manifest says exactly who's missing and the retry re-runs only
them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.shared.report_week import week_ending
from automations.total_knocks.pull import central_today
from automations.weekly_knock_dispositions import apps as A
from automations.weekly_knock_dispositions import board as B
from automations.weekly_knock_dispositions import pull as P
from automations.weekly_knock_dispositions.offices import enabled

REPORT_ID = "weekly_knock_dispositions"
# NO card of its own (Megan 2026-08-22): the Sunday board reports onto the
# shared Metrics card — same card daily_metrics + the office runner publish
# to. The curated map in day_orchestrator/hub_publish.py points this
# report_id there too, so the orchestrator pill can't auto-create a dupe.
CARD_ID = "office-metrics"
CARD_NAME = "Weekly Knock Dispositions"
ESTIMATED_MINUTES = 18   # 1 office ≈ 6 day pulls + 6 gap calls + 1 crosstab

REPORT_BREAKDOWN = """\
Every Sunday, for each configured office (offices.py):
1. Downloads ONE org-wide rep-level PRODUCT SALES SUMMARY crosstab
   (DailyRepBDreportpull) for the completed Mon–Sat week.
2. In one ownerville session: Disposition by Rep filtered to Mon–Sat via
   URL (?startDate/endDate), plus 6 daily Time Tracker calls for gap
   minutes. Talk-to = every disposition EXCEPT No answer / Inaccessible
   (Raf's rule, verified against his own sheet).
3. Renders one board per office — Rep | Total Talk To's | Avg/Day (÷6)
   | Total Apps | Avg Talk To's per App | First/Last Knock | Avg Gap/Day
   | Total Gap Hours — plus an OFFICE TOTALS row.
4. Posts each board as Lucy into that office's EXISTING Sunday Metrics
   thread ("Metrics for: <date>") — Raf's in #alphalete-sales; enrolled
   offices (gated off until Raf's go) in their own metrics channels.
   Needs a browser login? YES (warm ownerville session — runs on Lucy 1)."""
INCIDENT_KEY = f"standalone-{REPORT_ID}"     # prefix is load-bearing (notify)
# Raf 2026-08-22 (via Megan): the boards go into the EXISTING daily Metrics
# thread ("Metrics for: <date>"), not a thread of their own — Sunday's board
# reads as one more metric in the morning stack.
THREAD_NAME = "Metrics"                      # for log/manifest wording only
MEGAN = "U04G5HJBGFN"                        # --preview DM recipient

OUT_DIR = Path("output") / "weekly_knock_dispositions"
# Own Chrome profile — the shared .browser_profile is first-come-first-served
# and this run may overlap other browser reports (same escape hatch
# other_office_knocks uses; login comes from the shared storage_state).
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_weekly_knock_dispo")


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def _week(anchor: dt.date | None) -> tuple[dt.date, dt.date, dt.date]:
    """(monday, saturday, we_sunday) for the board's window."""
    sunday = (week_ending(anchor) if anchor
              else week_ending(central_today() - dt.timedelta(days=1)))
    return sunday - dt.timedelta(days=6), sunday - dt.timedelta(days=1), sunday


def _retry_args(offices: list[str]) -> list[str]:
    out = ["--live"]
    for o in offices:
        out += ["--office", o]
    return out


def _write_manifest(all_names: list[str], ran: list[str],
                    failed: list[str], note_extra: str = "") -> None:
    """Best-effort record for the Hub card + failure alert. A scoped re-run
    (--office X) merges into today's manifest, same rules as
    other_office_knocks."""
    try:
        from automations.shared import run_manifest as _rm
        ok = [o for o in ran if o not in failed]
        if set(ran) != set(all_names):          # scoped re-run → merge
            prior = _rm.read_manifest(REPORT_ID) or {}
            if str(prior.get("run_ts") or "").startswith(
                    dt.date.today().isoformat()):
                failed = [o for o in prior.get("failed", [])
                          if o not in ran] + failed
                ok = [o for o in prior.get("succeeded", [])
                      if o not in ran] + ok
        rem = None
        if failed:
            rem = _rm.make_remediation(
                reason=f"{len(failed)} office(s) missing from Sunday's "
                       f"{THREAD_NAME} thread in #alphalete-sales: "
                       f"{', '.join(failed)}.",
                fix="Re-run ONLY the missing office(s): "
                    f"lucy rerun {REPORT_ID} " + " ".join(_retry_args(failed)),
                message=f"Sunday's {THREAD_NAME} thread is missing "
                        f"{', '.join(failed)}. Usual causes: ownerville "
                        "session/impersonation, or the PSS crosstab pull — "
                        "the run log names which.")
        _rm.write_manifest(
            REPORT_ID, kind="office", failed=failed, succeeded=ok,
            retry_args=(_retry_args(failed) if failed else []),
            note=(f"{len(ok)}/{len(set(ok) | set(failed))} office board(s) "
                  f"posted to the {THREAD_NAME} thread"
                  + (f"; ⚠ MISSING: {', '.join(failed)}" if failed else "")
                  + note_extra),
            remediation=rem)
    except Exception:  # noqa: BLE001 — manifest must never fail the run
        pass


def _publish_outcome(status: str, headline: str, details: list[str], *,
                     started_at=None, dry_run: bool = False) -> None:
    """Hub run row + corrections alert, both best-effort (indeed_source_report
    pattern). Skipped on --dry-run; pill row skipped under the orchestrator."""
    if dry_run:
        return
    import os
    if not os.environ.get("HUB_REPORT_ID"):
        try:
            from automations.shared import hub_activity
            hub_activity.log_completed(CARD_ID, CARD_NAME, status=status,
                                       started_at=started_at)
        except Exception:  # noqa: BLE001 — reporting never sinks the report
            pass
    try:
        if status == "success":
            from automations.shared import incident_thread as _inc
            _inc.resolve_if_open(INCIDENT_KEY, what=f"*{CARD_NAME}*",
                                 detail="Clean run — every office posted.")
        else:
            from automations.day_orchestrator import notify
            notify.post_alert(headline, details, tag=INCIDENT_KEY,
                              incident=INCIDENT_KEY, label=f"*{CARD_NAME}*")
    except Exception as e:  # noqa: BLE001 — Slack must not fail the run
        print(f"  (corrections post skipped: {e})", flush=True)


def _print_board(office: str, rows: list[list[str]],
                 dispo_cols: list[str] | None = None) -> None:
    print(f"\n=== {office} ===")
    print("  " + " | ".join(B.headers_for(dispo_cols)))
    for r in rows:
        print("  " + " | ".join(r))


def run(anchor: dt.date | None = None, *, only: list[str] | None = None,
        dry_run: bool = True, preview_dm: str | None = None) -> int:
    started_at = dt.datetime.now()
    offices = enabled(only)
    all_names = [o["name"] for o in enabled(None)]
    monday, saturday, we_sunday = _week(anchor)
    print(f"[wkd] {CARD_NAME} — {monday} → {saturday} "
          f"({len(offices)} office(s): "
          f"{', '.join(o['name'] for o in offices)}) — "
          f"{'DRY-RUN' if dry_run else 'LIVE'}", flush=True)

    # Terminated-ICD guard (standing rule): flag, never block.
    term_flag = None
    try:
        from automations.shared.terminated_icds import alert_terminated
        _, term_flag = alert_terminated([o["name"] for o in offices],
                                        CARD_NAME)
    except Exception:  # noqa: BLE001
        pass

    # --- 1. The org-wide PSS crosstab, once for every office ---------------
    pss_path = None
    try:
        pss_path = A.download(we_sunday)
    except Exception as e:  # noqa: BLE001 — apps go blank, boards still post
        print(f"[wkd] ⚠ PSS crosstab failed ({type(e).__name__}: "
              f"{str(e)[:160]}) — apps columns will be blank, boards flagged "
              "INCOMPLETE.", flush=True)

    from automations.focus_office_att.aliases import load_aliases
    aliases_raw = load_aliases()
    try:
        aliases_map = dict(aliases_raw)
    except Exception:  # noqa: BLE001
        aliases_map = {}

    # --- 2. One ownerville session, offices in turn ------------------------
    from automations.shared.tableau_patchright import ownerville_session
    boards: list[tuple[dict, Path | None, str]] = []  # (cfg, png, comment_extra)
    failed: list[str] = []
    try:
        with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
            for cfg in offices:
                name = cfg["name"]
                try:
                    ov_rows, dispo_cols = P.pull_office_week(
                        page, cfg, aliases_raw, monday, saturday)
                    office_apps, extra = None, ""
                    if cfg.get("pss_owner") is None:
                        # NDS office: sales live in the NDS workbook, not the
                        # D2D PSS — blank apps, flagged (fill-but-flag).
                        extra = " — ⚠ INCOMPLETE: apps not wired (NDS)"
                    elif pss_path is None:
                        extra = " — ⚠ INCOMPLETE: apps unavailable"
                    else:
                        office_apps = A.rep_apps_for_owner(
                            pss_path, cfg["pss_owner"], aliases_map)
                    if not ov_rows and not office_apps:
                        # Visible absence, never a blank board (standing rule).
                        boards.append((cfg, None, extra))
                        continue
                    rows = B.compute_rows(ov_rows, office_apps, dispo_cols)
                    out_dir = OUT_DIR / _slug(name)
                    png = B.render(name, monday, saturday, rows, out_dir,
                                   dispo_cols)
                    boards.append((cfg, png, extra))
                    if (cfg.get("pss_owner") is not None and pss_path is None
                            and name not in failed):
                        failed.append(name)     # retry posts the full board
                    _print_board(name, rows, dispo_cols)
                    print(f"[wkd] rendered {name} -> {png}", flush=True)
                except Exception as e:  # noqa: BLE001 — one office ≠ the run
                    print(f"[wkd] ❌ {name} failed: {type(e).__name__}: "
                          f"{str(e)[:200]}", flush=True)
                    failed.append(name)
    except Exception as e:  # noqa: BLE001 — the session itself never opened
        print(f"[wkd] ❌ ownerville session failed: {type(e).__name__}: {e}",
              flush=True)
        failed = [o["name"] for o in offices]
        if not dry_run:
            _write_manifest(all_names, [o["name"] for o in offices], failed)
            _publish_outcome("failed", f"{CARD_NAME} — ownerville session "
                             "failed", [str(e)[:300]], started_at=started_at)
        return 1

    span = f"{monday.strftime('%b')} {monday.day}–{saturday.day}"

    if dry_run:
        print("[wkd] --dry-run — rendered only, NO channel post.", flush=True)
        for cfg, png, extra in boards:
            what = str(png) if png else "'No data available' line"
            where = cfg.get("channel_name") or "#alphalete-sales"
            print(f"[wkd]   would post: {cfg['name']} → {where} Metrics "
                  f"thread: {what}{extra}", flush=True)
        if preview_dm:
            # DM the rendered board(s) to Megan as Lucy — the gated-preview
            # path, so she can see the real image without a channel post.
            from automations.shared import slack_metrics_post as smp
            for cfg, png, extra in boards:
                if png is None:
                    continue
                try:
                    # as_bot=False: Lucy 1 has no BOT token file — its xoxp
                    # USER token IS Lucy, so the DM still arrives from Lucy
                    # (the bot-token path crashed the first preview,
                    # 2026-08-22). A DM problem never fails the run.
                    resp = smp.dm_user_with_file(
                        Path(png), user=preview_dm, as_bot=False,
                        comment=f"📋 PREVIEW — {CARD_NAME} — {cfg['name']} — "
                                f"{span}{extra} (dry-run; nothing posted to "
                                "the channel)",
                        file_name=f"{Path(png).stem}_{_slug(cfg['name'])}.png")
                    print(f"[wkd]   preview DM {cfg['name']}: "
                          f"{'✅' if resp.get('ok') else resp}", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"[wkd]   ⚠ preview DM {cfg['name']} failed: "
                          f"{type(e).__name__}: {str(e)[:160]}", flush=True)
        print(f"[wkd] {'⚠' if failed else '✅'} finished (dry-run)"
              + (f" — failed: {', '.join(failed)}" if failed else ""),
              flush=True)
        return 1 if failed else 0

    if not boards:
        print("[wkd] ❌ nothing to post — every office failed.", flush=True)
        _write_manifest(all_names, [o["name"] for o in offices], failed)
        _publish_outcome("failed", f"{CARD_NAME} — nothing posted",
                         [f"Every office failed: {', '.join(failed)}"],
                         started_at=started_at)
        return 1

    # --- 3. Post into each office's EXISTING Sunday Metrics thread ---------
    # (Raf 2026-08-22: no thread of its own — the board is one more metric in
    # the morning stack.) ensure_metrics_thread is find-or-create with the
    # exact header daily_metrics posts, so whichever report gets there first
    # on Sunday opens the one thread and the other reuses it. Per-office
    # channels (enrolled offices) post into THEIR thread by overriding the
    # smp module channel/label around the calls — the same values the office
    # runner injects via env for its subprocesses.
    from automations.shared import slack_metrics_post as smp
    slack_today = central_today()
    for cfg, png, extra in boards:
        name = cfg["name"]
        if cfg.get("slack_token_file"):
            # Cross-workspace office (e.g. trang/FRESH SUCCESS): posting with
            # its bot token is not wired here yet — loud skip, counted missing.
            print(f"[wkd] ⚠ {name}: cross-workspace posting "
                  f"({cfg['slack_token_file']}) not wired — SKIPPED.",
                  flush=True)
            if name not in failed:
                failed.append(name)
            continue
        keep_chan, keep_label = smp.CHANNEL_ID, smp.HEADER_LABEL
        try:
            if cfg.get("channel_id"):
                smp.CHANNEL_ID = cfg["channel_id"]
                smp.HEADER_LABEL = cfg.get("header_label", "")
            head = smp.ensure_metrics_thread(slack_today)
            thread_ts = head.get("thread_ts")
            if not thread_ts:
                print(f"[wkd] ❌ {name}: couldn't open the {THREAD_NAME} "
                      "thread in "
                      f"{cfg.get('channel_name') or '#alphalete-sales'}: "
                      f"{head}", flush=True)
                if name not in failed:
                    failed.append(name)
                continue
            comment = f"📋 {CARD_NAME} — {name} — {span}{extra}"
            if term_flag:
                comment += f"\n{term_flag}"
            if png is None:
                resp = smp.post_reply_text_only(
                    f"{comment} — No data available",
                    today=slack_today, thread_ts=thread_ts)
            else:
                resp = smp.post_reply_with_image(
                    Path(png), comment=comment, today=slack_today,
                    thread_ts=thread_ts, wait_visible=True,
                    file_name=f"{Path(png).stem}_{_slug(name)}.png")
            if resp.get("ok"):
                print(f"[wkd] ✅ posted {name}.", flush=True)
            else:
                print(f"[wkd] ⚠ Slack response for {name}: {resp}",
                      flush=True)
                if name not in failed:
                    failed.append(name)
        finally:
            smp.CHANNEL_ID, smp.HEADER_LABEL = keep_chan, keep_label

    _write_manifest(all_names, [o["name"] for o in offices], failed)
    _publish_outcome(
        "success" if not failed else "failed",
        f"{CARD_NAME} — {len(failed)} office(s) missing",
        [f"Missing: {', '.join(failed)}"] if failed else [],
        started_at=started_at)
    print(f"[wkd] {'⚠' if failed else '✅'} finished"
          + (f" — failed: {', '.join(failed)}" if failed else ""), flush=True)
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="weekly_knock_dispositions",
        description="Sunday per-rep knock/talk-to productivity board(s) → "
                    "#alphalete-sales.")
    ap.add_argument("date", nargs="?", default=None,
                    help="any day inside the wanted Mon–Sat week "
                         "(default: the completed week)")
    ap.add_argument("--office", action="append", default=None,
                    help="run ONE configured office (repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + render to output/, NO Slack post (default)")
    ap.add_argument("--live", action="store_true",
                    help="pull + render + POST into the Sunday Metrics "
                         "thread(s)")
    ap.add_argument("--preview", action="store_true",
                    help="dry-run, then DM the rendered board(s) to Megan "
                         "as Lucy (no channel post)")
    args = ap.parse_args(argv)
    if args.live and args.dry_run:
        # `lucy rerun` appends extra args AFTER the scheduler entry's
        # base_args (--live), so the safe probe arrives as `--live --dry-run`.
        # The safe flag wins — treating this as an error failed the very
        # first mini dry-run (2026-08-22, exit 2 → incident).
        print("[wkd] both --live and --dry-run given — dry-run wins.",
              flush=True)
    anchor = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    return run(anchor, only=args.office,
               dry_run=(args.dry_run or args.preview or not args.live),
               preview_dm=(MEGAN if args.preview else None))


if __name__ == "__main__":
    raise SystemExit(main())
