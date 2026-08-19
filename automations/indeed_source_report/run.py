"""Refresh the CURRENT month of the Indeed Ad Performance dashboard.

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

from . import fetch, parse, sheet
from .offices import OFFICES, month_window

YTD_LABEL = "YTD (all months)"
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

    period, rng, start, end = month_window(a.month)
    targets = [(o, n) for o, n in OFFICES if not a.office or o in a.office]
    print("[indeed_source_report] %s (%s) — %d offices" % (period, rng, len(targets)),
          flush=True)

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

    sess = sheet.session(verbose=True)
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
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
