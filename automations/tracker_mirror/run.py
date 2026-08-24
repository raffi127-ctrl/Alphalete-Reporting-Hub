"""Sync the per-manager ad tracker tabs in Alphalete Recruiting Dashboard.

WHY THIS EXISTS. The manager tabs used to be live IMPORTRANGE mirrors of each
manager's personal tracker. IMPORTRANGE authorization is scoped to the
DESTINATION workbook, so moving the tabs to Alphalete Recruiting Dashboard
(2026-08-22) silently disconnected all 21 — and no credential we hold can read
the managers' personal spreadsheets directly (403 for every one; the original
Allow-access grants were made by someone else entirely).

THE CHAIN. The OLD workbook's grants survived: a freshly planted IMPORTRANGE
there connects with no human click. So hidden "MIRROR <name>" tabs in the old
org tracker stay live via Google's own refresh, and this job copies their
VALUES into the manager tabs of the boards workbook, which Manager View
INDIRECTs into. Managers' sheet -> old workbook (grant) -> here (values).

NEVER BLANK ON FAILURE: a mirror that reads empty or #REF keeps the previous
values in place and is reported loudly — a temporarily broken IMPORTRANGE must
not erase a tab that had data (the Daily Log wipe was exactly this shape).

  python -m automations.tracker_mirror.run [--only "Name|Name"] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

OLD = "1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo"     # org tracker: grants live here
NEW = "111Bmxx1JvT1UFXaLin7gPH53149WBZhMe0r7CHirHbA"     # boards: where views read
API = "https://sheets.googleapis.com/v4/spreadsheets"
SOURCES = json.loads((Path(__file__).parent / "sources.json").read_text())


def q(rng):
    return urllib.parse.quote(rng, safe="")


def main(argv=None):
    marker = Path(__file__).parent / "DISABLED"
    if marker.exists():
        print("[tracker_mirror] DISABLED — manager tabs are live IMPORTRANGE "
              "(2026-08-24); a ferry run would overwrite the formulas. Exiting.",
              flush=True)
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="pipe-separated manager names")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    from automations.funnel_board.auth import session
    S = session(verbose=True)

    names = list(SOURCES)
    if a.only:
        keep = set(a.only.split("|"))
        names = [n for n in names if n in keep]

    synced, skipped = [], []
    for name in names:
        # UNFORMATTED_VALUE is load-bearing: the default FORMATTED_VALUE turns
        # date serials and numbers into display strings, and the boards' AD
        # BUDGET box does MAX() over Report Date — text dates make it $0.
        r = S.get("%s/%s/values/%s" % (API, OLD, q("'MIRROR %s'!A1:Z1000" % name)),
                  params={"valueRenderOption": "UNFORMATTED_VALUE"})
        if r.status_code != 200:
            skipped.append((name, "mirror read HTTP %d" % r.status_code))
            continue
        rows = r.json().get("values", [])
        first = str(rows[0][0]) if rows and rows[0] else ""
        if not rows or first.startswith(("#REF", "#ERROR", "Loading")):
            skipped.append((name, "mirror empty/errored (%r)" % first[:20]))
            continue
        if a.dry_run:
            synced.append((name, len(rows)))
            continue
        # header row 1 in the dest tab is static and kept; data lands at A2,
        # replacing whatever was there (including the old broken IMPORTRANGE).
        S.post("%s/%s/values/%s:clear" % (API, NEW, q("'%s'!A2:Z1000" % name)), json={})
        w = S.put("%s/%s/values/%s" % (API, NEW, q("'%s'!A2" % name)),
                  params={"valueInputOption": "RAW"},
                  json={"majorDimension": "ROWS", "values": rows})
        if w.status_code != 200:
            skipped.append((name, "dest write HTTP %d" % w.status_code))
            continue
        synced.append((name, len(rows)))
        print("  %-24s %4d rows" % (name, len(rows)), flush=True)

    print("[tracker_mirror] synced %d/%d%s" % (len(synced), len(names),
          " (dry run)" if a.dry_run else ""), flush=True)
    if skipped:
        print("[tracker_mirror] kept previous values for %d:" % len(skipped), flush=True)
        for n, why in skipped:
            print("  !! %-24s %s" % (n, why), flush=True)
    return 0 if not skipped else 2


if __name__ == "__main__":
    sys.exit(main())
