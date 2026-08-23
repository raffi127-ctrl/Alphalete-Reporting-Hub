"""Refresh the CURRENT month of the Source Report - Indeed dashboard.

  python -m automations.indeed_source_report.run            # live, all offices
  python -m automations.indeed_source_report.run --dry-run  # pull + report, write nothing
  python -m automations.indeed_source_report.run --office 11580
  python -m automations.indeed_source_report.run --month 2026-07

Only the month being refreshed is rewritten; earlier months on the DATA tab are
left exactly as they are. Each manager's YTD block is then recomputed from every
month present, because YTD depends on the month that just changed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
import urllib.parse

from . import fetch, parse, sheet
from .offices import OFFICES, month_window

# Hub identity. log_completed self-registers a Report Library card under this
# id on the first real run, so the report is visible on the Hub (card + pill +
# needs-attention strip) — Megan's standing rule: a LaunchAgent report must
# publish its runs, or silence and success look identical.
CARD_ID = "indeed-source-report"
CARD_NAME = "Source Report - Indeed (Source Report)"
# The `standalone-` family prefix matters: the mini's watcher files this
# report's misses as `standalone-indeed-source-report` (notify.py builds
# `standalone-<registry id>`), and a bare un-prefixed key lives outside every
# incident family — on 2026-08-21 the 4:02 crash post and the watcher's 4:08
# "didn't run clean" post couldn't find each other and the channel got both.
# Same key = one thread, whichever side speaks first, and a clean run here
# closes the watcher's post too.
INCIDENT_KEY = "standalone-indeed-source-report"


def _publish_outcome(status, headline, details, *, started_at=None,
                     dry_run=False):
    """Hub run row + corrections-channel alert, both best-effort.

    Standing rules this implements (same shape as applicant_tracker/run.py):
    every run lands in Hub Activity so the card's pill tells the truth, and
    every failure posts to #claudecorrections-and-requests in real time —
    NOT into a log nobody reads. A clean run closes the incident thread.
    Skipped entirely on --dry-run. Under the orchestrator (HUB_REPORT_ID set)
    the pill row is the orchestrator's job; the alert is still ours."""
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
            _inc.resolve_if_open(INCIDENT_KEY, what="*Indeed Source Report*",
                                 detail="Clean refresh — every office wrote.")
        else:
            from automations.day_orchestrator import notify
            notify.post_alert(headline, details, tag=INCIDENT_KEY,
                              incident=INCIDENT_KEY,
                              label="*Indeed Source Report*")
    except Exception as e:  # noqa: BLE001 — Slack must not fail the run
        print("  (corrections post skipped: %s)" % e, flush=True)


YTD_LABEL = "YTD (all months)"

# Board mirrors: after every refresh, each target workbook's hidden
# 'Indeed Ad Data' gets that roster's slice of the freshly written data
# (values only — no IMPORTRANGE auth, no other managers' numbers leak onto
# an owner's board). These sheets are NOT shared with the service account,
# so the push authenticates with the personal OAuth token explicitly.
# Targets: Jamis's sales board + Carlos's Captainship Dashboard (2026-08-23).
BOARD_PUSH = [
    ("1wDWeiS0IuzwsYFGF-s6mA6by8CtBtI5eOEnNmahBd6s", ["Jamis Garay"]),
    ("14_T4fySyQhRPsyWZLGEs6Sarc0jyJ4oD-gV8E97WZU8", None),   # None = captainship
]


def push_boards(new_rows, periods):
    """Mirror manager slices into the captainship board workbooks. Best-effort:
    a board failure must never sink the main refresh."""
    from automations.funnel_board.roster import CAPTAINSHIP_NAMES
    creds = sheet._oauth()
    if creds is None:
        print("[indeed_source_report] board push skipped — no OAuth token here", flush=True)
        return
    from google.auth.transport.requests import AuthorizedSession
    bs = AuthorizedSession(creds)
    for ssid, managers in BOARD_PUSH:
        mgrs = managers or CAPTAINSHIP_NAMES
        rows = [r for r in new_rows if r and r[0] in mgrs]
        if not rows:
            print("  board %s: empty slice, left alone" % ssid[:10], flush=True)
            continue
        try:
            rng = lambda a1: urllib.parse.quote("'Indeed Ad Data'!%s" % a1, safe="")
            bs.post("%s/%s/values/%s:clear" % (sheet.API, ssid, rng("A2:U6000")), json={}).raise_for_status()
            bs.put("%s/%s/values/%s" % (sheet.API, ssid, rng("A2")),
                   params={"valueInputOption": "RAW"},
                   json={"majorDimension": "ROWS", "values": rows}).raise_for_status()
            n = max(len(mgrs), len(periods))
            bs.put("%s/%s/values/%s" % (sheet.API, ssid, rng("W2")),
                   params={"valueInputOption": "RAW"},
                   json={"majorDimension": "ROWS", "values":
                         [[mgrs[i] if i < len(mgrs) else "",
                           periods[i] if i < len(periods) else ""] for i in range(n)]}
                   ).raise_for_status()
            print("  board %s: %d rows" % (ssid[:10], len(rows)), flush=True)
        except Exception as e:  # noqa: BLE001
            print("  !! board %s push failed: %s" % (ssid[:10], str(e)[:120]), flush=True)


# Managers whose dashboard merges an ad across cities: same account + same
# role = one row, cities listed together in the City column (their own call —
# Carlos, 2026-08-22). Everyone else keeps the per-city split, which is what
# exposes a dead posting in one metro next to a producing one in another.
CITY_AGNOSTIC = {"Carlos Hidalgo"}
def rows_for(manager, period, ads):
    out, tot = [], parse.blank()
    for g in ads:
        for f in parse.FIELDS:
            tot[f] += g["rec"][f]
    for g in ads:
        out.append([manager, period] + parse.display(
            parse.account_name(g["inbox"]), g["inbox"], g["title"], g["city"],
            g["variants"], g["rec"]))
    out.append([manager, period] + parse.display(
        "TOTAL", "", "", "", sum(g["variants"] for g in ads), tot))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--month", help="YYYY-MM (default: current month)")
    ap.add_argument("--office", action="append", help="limit to office id(s)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args(argv)
    run_started = dt.datetime.now()

    period, rng, start, end = month_window(a.month)
    targets = [(o, n) for o, n in OFFICES if not a.office or o in a.office]
    print("[indeed_source_report] %s (%s) — %d offices" % (period, rng, len(targets)),
          flush=True)

    # PREFLIGHT. Pulling 28 offices takes ~12 minutes; discovering only then that
    # this machine's credential cannot write the workbook wastes the whole run and
    # reads as a mysterious failure. Prove the write BEFORE the browser opens.
    sess = sheet.session(verbose=True)
    if not a.dry_run:
        try:
            sheet.probe_write(sess)
        except Exception as e:  # noqa: BLE001 — the reason matters more than the trace
            print("[indeed_source_report] ABORT — cannot write the workbook as this "
                  "machine's identity: %s" % str(e)[:200], flush=True)
            print("  fix: install the applicant_tracker service-account key here "
                  "(preferred), or share the workbook with this machine's Google "
                  "account. Nothing was pulled and nothing was changed.", flush=True)
            _publish_outcome(
                "failed",
                "🗂️ *Indeed Source Report ABORTED — this machine can't write "
                "the workbook*",
                ["• Preflight write failed before anything was pulled: %s"
                 % str(e)[:200],
                 "• Fix: install the applicant_tracker service-account key on "
                 "this machine (`set_applicant_service_account` action), or "
                 "share the workbook with its Google account.",
                 "• Nothing was pulled and nothing was changed."],
                started_at=run_started, dry_run=a.dry_run)
            return 3

    from automations.shared.tableau_patchright import appstream_direct_session
    fresh, failures, flags = {}, [], []
    with appstream_direct_session(headless=not a.headed, verbose=False,
                                  allow_form_login=True) as page:
        tok = fetch.token(page)
        for oid, name in targets:
            try:
                fetch.select_office(page, tok, oid)
                html, owner, nrows = fetch.source_report(page, tok, start, end)
                ads, fl = parse.ads_for_month(html)
                if name in CITY_AGNOSTIC:
                    ads, fl = parse.merge_across_cities(ads), []
                fresh[name] = ads
                for f in fl:
                    flags.append((name, period) + f)
                print("  OK   %-38s owner=%-22s raw=%-4d ads=%d"
                      % (name, owner[:22], nrows, len(ads)), flush=True)
            except Exception as e:  # noqa: BLE001 — one office must not kill the run
                failures.append((oid, name, str(e)[:120]))
                print("  FAIL %-38s %s" % (name, str(e)[:70]), flush=True)

    if not fresh:
        print("nothing pulled — leaving the sheet alone", flush=True)
        return 1

    existing = sheet.get_values(sess, sheet.data_range("A2:U20000"))
    # Drop the current month ONLY for managers this run actually pulled, so a
    # --office run (or an office that failed above) leaves everyone else's month
    # standing instead of silently deleting it. YTD always goes: it is rebuilt
    # below for every manager, pulled or not.
    pulled = set(fresh)
    keep = [r for r in existing
            if len(r) > 1 and r[0]
            and r[1] != YTD_LABEL
            and not (r[1] == period and r[0] in pulled)]
    print("[indeed_source_report] refreshed %d managers; kept %d existing rows"
          % (len(pulled), len(keep)), flush=True)

    new = list(keep)
    for name, ads in fresh.items():
        new.extend(rows_for(name, period, ads))

    # YTD depends on the month we just replaced, so rebuild it for every manager
    # that has any month present — including managers not pulled in this run.
    per_mgr = {}
    for r in new:
        if r[1] == YTD_LABEL:
            continue
        per_mgr.setdefault(r[0], []).append(r)
    for mgr, mrows in per_mgr.items():
        ads = [dict(inbox=r[3] or "", title=r[4], city=r[5] or "",
                    base=parse.base_role(r[4]), variants=int(r[6] or 1),
                    titles=[r[4]],
                    rec=dict(zip(parse.FIELDS,
                                 [int(r[7] or 0), 0, int(r[9] or 0), int(r[10] or 0),
                                  int(r[11] or 0), int(r[13] or 0), int(r[14] or 0),
                                  int(r[16] or 0), int(r[17] or 0), int(r[18] or 0),
                                  int(r[19] or 0)])))
               for r in mrows if r[2] != "TOTAL"]
        # removed% is stored, not the count — recover it so YTD's Removed % is right
        for r, ad in zip([r for r in mrows if r[2] != "TOTAL"], ads):
            pct = r[8]
            ad["rec"]["removed"] = int(round(float(pct) * ad["rec"]["apps"])) if pct else 0
        y = parse.ytd_from(ads)
        new.extend(rows_for(mgr, YTD_LABEL, y))

    order = {n: i for i, (_, n) in enumerate(OFFICES)}
    porder = {}
    for r in new:
        porder.setdefault(r[1], len(porder))
    new.sort(key=lambda r: (order.get(r[0], 999), r[1] == YTD_LABEL, porder.get(r[1], 0)))

    managers = sorted({r[0] for r in new}, key=lambda m: order.get(m, 999))
    periods = sorted({r[1] for r in new if r[1] != YTD_LABEL}) + [YTD_LABEL]

    if a.dry_run:
        print("\nDRY RUN — would write %d rows (%d managers, periods: %s)"
              % (len(new), len(managers), ", ".join(periods)), flush=True)
    else:
        sheet.clear(sess, sheet.data_range("A2:U20000"))
        sheet.put_values(sess, sheet.data_range("A2"), new)
        sheet.put_values(sess, sheet.data_range("W2"), [[managers[i] if i < len(managers) else "",
                                            periods[i] if i < len(periods) else ""]
                                           for i in range(max(len(managers), len(periods)))])
        print("[indeed_source_report] wrote %d rows" % len(new), flush=True)
        push_boards(new, periods)

    if flags:
        print("\nCity-less pieces left unmerged (wording could not pick a city):", flush=True)
        for name, per, inbox, base, cities, apps in flags:
            print("   %-30s %-14s %-32s apps=%-5d runs in: %s"
                  % (name[:30], per, base[:32], apps, ", ".join(cities)), flush=True)
    if failures:
        print("\nFAILED OFFICES (%d) — their rows were left untouched:" % len(failures),
              flush=True)
        for oid, name, err in failures:
            print("   %-8s %-30s %s" % (oid, name[:30], err), flush=True)
        _publish_outcome(
            "partial",
            "🗂️ *Indeed Source Report — %d of %d office(s) did not refresh*"
            % (len(failures), len(targets)),
            ["• %s (%s): %s" % (name, oid, str(err)[:160])
             for oid, name, err in failures]
            + ["• Their rows were left untouched; every other office wrote."],
            started_at=run_started, dry_run=a.dry_run)
        return 2
    _publish_outcome("success", "", [], started_at=run_started,
                     dry_run=a.dry_run)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        # A crash outside main's own handling (session died, parse blew up)
        # must still reach the Hub + corrections channel — an unhandled
        # traceback in a launchd log is the definition of failing silently.
        _tail = traceback.format_exc().strip().splitlines()[-1][:200]
        _publish_outcome(
            "failed",
            "🗂️ *Indeed Source Report CRASHED before finishing*",
            ["• %s" % _tail,
             "• Full traceback in output/logs/indeed_source_report_*.log on "
             "the machine that ran it."],
            dry_run=("--dry-run" in sys.argv))
        sys.exit(1)
