"""Refresh the Ad Sales Board — the Source Report week by week, pull + names.

  python -m automations.ad_sales_board.run              # live: current + previous ad-week
  python -m automations.ad_sales_board.run --dry-run    # pull + report, write nothing
  python -m automations.ad_sales_board.run --office 11580
  python -m automations.ad_sales_board.run --weeks 4    # backfill: current + 3 back
  python -m automations.ad_sales_board.run --anchor 08-12-2026   # one explicit week

An ad-week runs WEDNESDAY → TUESDAY (see weeks.py). Each run re-pulls its
target weeks from AppStream's Source Report (p=702) per office, joins the
applicant names from the Call List import, and rewrites ONLY the
(manager, week) pairs it actually pulled — everything older stays frozen
exactly as it was last written, same freeze rule as the monthly dashboard.

On Wednesdays a live default run also flips the visible tab's week picker (C2)
to the week that just finished, so the morning look-back opens on the right
week without anyone touching the dropdown.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import datetime as dt
import sys
import traceback

from automations.indeed_source_report import fetch, parse
from automations.indeed_source_report.offices import OFFICES
from automations.indeed_source_report.run import CITY_AGNOSTIC, _headline

from . import names, sheet, weeks

CARD_ID = "ad-sales-board"
CARD_NAME = "Ad Sales Board (weekly Source Report)"
# Same `standalone-` family prefix as the monthly job, for the same reason: the
# watcher's miss reports and this job's own crash posts must share one incident
# thread instead of talking past each other.
INCIDENT_KEY = "standalone-ad-sales-board"


def _publish_outcome(status, headline, details, *, started_at=None, dry_run=False):
    """Hub run row + corrections-channel alert, both best-effort — copied from
    the monthly job (see its comment for the standing rules this implements)."""
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
            _inc.resolve_if_open(INCIDENT_KEY, what="*Ad Sales Board*",
                                 detail="Clean refresh — every office wrote.")
        else:
            from automations.day_orchestrator import notify
            notify.post_alert(headline, details, tag=INCIDENT_KEY,
                              incident=INCIDENT_KEY, label="*Ad Sales Board*")
    except Exception as e:  # noqa: BLE001 — Slack must not fail the run
        print("  (corrections post skipped: %s)" % e, flush=True)


def ads_for_week(html):
    """Merged ad rows for one office-week — the monthly parse, with the
    "[Action required] New application for" wrapper stripped BEFORE the noise
    filter sees it (parse.NOISE would junk those rows; they are real
    applicants). Subjects live in table cells, so a plain text substitution on
    the HTML reaches exactly them."""
    return parse.ads_for_month(names.WRAPPER.sub("", html))


def rows_for(manager, label, week_start, ads, name_rows):
    """The data-tab rows for one (manager, week): one row per ad (Pull + its
    names), an unmatched-names row when the join couldn't place someone, and a
    TOTAL row last. Names never total into one cell — the TOTAL's # Names is
    the count, which includes the unmatched."""
    iso = week_start.isoformat()
    names_for, unmatched = names.attach(ads, name_rows, manager in CITY_AGNOSTIC)
    out = []
    tot = parse.blank()
    for g in ads:
        for f in parse.FIELDS:
            tot[f] += g["rec"][f]
    for g in ads:
        got = names_for.get(id(g), [])
        out.append([manager, label, parse.account_name(g["inbox"]), g["inbox"],
                    g["title"], g["city"], g["rec"]["apps"], g["rec"]["scl"],
                    len(got), ", ".join(got), iso])
    if unmatched:
        out.append([manager, label, "—", "", "(names with no matching ad row)",
                    "", "", "", len(unmatched), ", ".join(unmatched), iso])
    out.append([manager, label, "TOTAL", "", "", "", tot["apps"], tot["scl"],
                sum(len(v) for v in names_for.values()) + len(unmatched), "", iso])
    return out


def _advance_week_picker(sess, label):
    """Point the visible tab's C2 at `label`. RAW write, so the cell keeps its
    plain-text format and the label lands verbatim."""
    sheet.put_values(sess, sheet.view_range("C2"), [[label]])
    print("[ad_sales_board] week picker -> %s" % label, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--office", action="append", help="limit to office id(s)")
    ap.add_argument("--weeks", type=int, default=2,
                    help="how many ad-weeks back from today, current included (default 2)")
    ap.add_argument("--anchor", action="append",
                    help="explicit week anchor(s) mm-dd-yyyy (any day in the week works)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    run_started = dt.datetime.now()
    today = dt.date.today()

    if a.anchor:
        wins = [weeks.window(weeks.anchor_for(
            dt.datetime.strptime(x, "%m-%d-%Y").date())) for x in a.anchor]
    else:
        wins = weeks.windows_back(max(1, a.weeks), today)
    targets = [(o, n) for o, n in OFFICES if not a.office or o in a.office]
    print("[ad_sales_board] weeks: %s — %d offices"
          % (", ".join(w[0] for w in wins), len(targets)), flush=True)

    # Preflight, same reason as the monthly job: prove the write BEFORE a long
    # browser pull, or a permission fault wastes the whole pass.
    sess = sheet.session(verbose=True)
    if not a.dry_run:
        try:
            sheet.probe_write(sess)
        except Exception as e:  # noqa: BLE001 — the reason matters more than the trace
            print("[ad_sales_board] ABORT — cannot write the workbook as this "
                  "machine's identity: %s" % str(e)[:200], flush=True)
            print("  fix: run build_tab.py once if the 'Ad Sales Data' tab does "
                  "not exist yet; otherwise install the applicant_tracker "
                  "service-account key or share the workbook with this machine. "
                  "Nothing was pulled and nothing was changed.", flush=True)
            _publish_outcome(
                "failed",
                "🧲 *Ad Sales Board ABORTED — this machine can't write the workbook*",
                ["• Preflight write failed before anything was pulled: %s" % str(e)[:200],
                 "• If the 'Ad Sales Data' tab is missing, run "
                 "automations/ad_sales_board/build_tab.py once from the laptop.",
                 "• Nothing was pulled and nothing was changed."],
                started_at=run_started, dry_run=a.dry_run)
            return 3

    # Names first — a plain Sheets read; if it fails nothing was pulled yet.
    call_rows = names.load_call_list(sess, sheet.API)
    print("[ad_sales_board] call-list rows loaded: %d" % len(call_rows), flush=True)

    from automations.shared.tableau_patchright import appstream_direct_session
    fresh, failures = {}, []      # fresh[(manager, label)] = data rows
    rescued_total = 0
    with appstream_direct_session(headless=not a.headed, verbose=False,
                                  allow_form_login=True) as page:
        tok = fetch.token(page)
        for oid, name in targets:
            try:
                fetch.select_office(page, tok, oid)
                for label, start, end in wins:
                    html, _owner, nrows = fetch.source_report(
                        page, tok, weeks.fmt_mdY(start), weeks.fmt_mdY(end))
                    rescued = len(names.WRAPPER.findall(html))
                    rescued_total += rescued
                    ads, _flags = ads_for_week(html)
                    if name in CITY_AGNOSTIC:
                        ads = parse.merge_across_cities(ads)
                    wk_names = names.in_window(call_rows, name, start, end)
                    fresh[(name, label)] = rows_for(name, label, start, ads, wk_names)
                    print("  OK   %-24s %-22s raw=%-4d ads=%-3d pull=%-5d names=%d%s"
                          % (name[:24], label, nrows, len(ads),
                             sum(g["rec"]["apps"] for g in ads), len(wk_names),
                             "  (+%d wrapped subjects kept)" % rescued if rescued else ""),
                          flush=True)
            except Exception as e:  # noqa: BLE001 — one office must not kill the run
                failures.append((oid, name, _headline(e)))
                print("  FAIL %-24s %s" % (name, _headline(e)[:70]), flush=True)
                # The WHOLE error, unclipped — a failure you cannot read is a
                # failure you cannot fix (see the monthly job, 2026-08-24).
                for ln in str(e).strip().splitlines():
                    print("       | %s" % ln.rstrip()[:200], flush=True)

    if not fresh:
        print("nothing pulled — leaving the sheet alone", flush=True)
        _publish_outcome("failed",
                         "🧲 *Ad Sales Board — nothing pulled, sheet left alone*",
                         ["• Every office failed; see the log."],
                         started_at=run_started, dry_run=a.dry_run)
        return 1

    # Freeze rule: rewrite only the (manager, week) pairs this run pulled.
    existing = sheet.get_values(sess, sheet.data_range("A2:K20000"))
    pulled = set(fresh)
    keep = [r for r in existing
            if len(r) > 1 and r[0] and (r[0], r[1]) not in pulled]
    new = list(keep)
    for key in fresh:
        new.extend(fresh[key])
    print("[ad_sales_board] refreshed %d manager-weeks; kept %d existing rows"
          % (len(pulled), len(keep)), flush=True)

    # Deterministic order: roster, then week newest-first (column K is ISO so
    # it sorts as text), leaving each block's internal pull-desc order alone.
    order = {n: i for i, (_o, n) in enumerate(OFFICES)}
    block = {}
    for i, r in enumerate(new):
        block.setdefault((r[0], r[1]), i)
    new.sort(key=lambda r: (order.get(r[0], 999),
                            _desc_iso(r[10] if len(r) > 10 else ""),
                            block[(r[0], r[1])]))
    new = _numeric_cols(new)

    managers = sorted({r[0] for r in new}, key=lambda m: order.get(m, 999))
    week_list = sorted({(r[10] if len(r) > 10 else "", r[1]) for r in new},
                       reverse=True)
    week_labels = [w[1] for w in week_list]

    if a.dry_run:
        print("\nDRY RUN — would write %d rows (%d managers, %d weeks: %s)"
              % (len(new), len(managers), len(week_labels),
                 ", ".join(week_labels[:6])), flush=True)
    else:
        sheet.clear(sess, sheet.data_range("A2:K20000"))
        sheet.put_values(sess, sheet.data_range("A2"), new)
        sheet.put_values(sess, sheet.data_range("W2"),
                         [[managers[i] if i < len(managers) else "",
                           week_labels[i] if i < len(week_labels) else ""]
                          for i in range(max(len(managers), len(week_labels)))])
        print("[ad_sales_board] wrote %d rows" % len(new), flush=True)
        # Wednesday morning, default windows: open the board on the week that
        # just finished. Backfills and office-limited runs leave the picker be.
        if today.weekday() == weeks.WEDNESDAY and not a.office and not a.anchor:
            done = weeks.window(weeks.anchor_for(today) - dt.timedelta(days=7))[0]
            try:
                _advance_week_picker(sess, done)
            except Exception as e:  # noqa: BLE001 — cosmetic, never fails the run
                print("  (week picker not advanced: %s)" % str(e)[:120], flush=True)

    if rescued_total:
        print("\n%d '[Action required] New application for …' subjects were kept "
              "as real ads this run — the MONTHLY Source Report - Indeed still "
              "junk-filters these." % rescued_total, flush=True)
    if failures:
        print("\nFAILED OFFICES (%d) — their weeks were left untouched:" % len(failures),
              flush=True)
        for oid, name, err in failures:
            print("   %-8s %-30s %s" % (oid, name[:30], err), flush=True)
        _publish_outcome(
            "partial",
            "🧲 *Ad Sales Board — %d of %d office(s) did not refresh*"
            % (len(failures), len(targets)),
            ["• %s (%s): %s" % (name, oid, str(err)[:160])
             for oid, name, err in failures]
            + ["• Their weeks were left untouched; every other office wrote."],
            started_at=run_started, dry_run=a.dry_run)
        return 2
    _publish_outcome("success", "", [], started_at=run_started, dry_run=a.dry_run)
    return 0


def _desc_iso(iso):
    """Sort helper: ISO date -> string that orders newest FIRST under plain
    ascending sort (works because the digits are fixed-width)."""
    return "".join(chr(255 - ord(c)) for c in str(iso))


def _numeric_cols(rows):
    """Re-type Pull / To Call List / # Names (G,H,I = idx 6..8) on recycled
    rows, same reason as the monthly job's _numeric: sheet-recycled values come
    back as strings and text numbers kill numeric formats and future CF."""
    out = []
    for r in rows:
        rr = list(r)
        for i in (6, 7, 8):
            if i < len(rr) and isinstance(rr[i], str) and rr[i].strip():
                try:
                    rr[i] = int(float(rr[i]))
                except ValueError:
                    pass
        out.append(rr)
    return out


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        _tail = traceback.format_exc().strip().splitlines()[-1][:200]
        _publish_outcome(
            "failed",
            "🧲 *Ad Sales Board CRASHED before finishing*",
            ["• %s" % _tail,
             "• Full traceback in output/logs/ad_sales_board_*.log on the "
             "machine that ran it."],
            dry_run=("--dry-run" in sys.argv))
        sys.exit(1)
