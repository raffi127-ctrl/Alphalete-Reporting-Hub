"""Fill history weeks for NDS + B2B from tracker screenshots Eve sends.

Those two weeks-back columns cannot be pulled: the NDS dashboard ignores a date
filter entirely and the B2B pager only exposes this week and last. So the only
route to an older week is the tracker image, and Eve sends them one week at a
time (`output/_hc_trackers/`).

WHERE THE NUMBERS COME FROM. Each tracker prints a `Rep Count` column per ICD -
Eve, 2026-09-07: "no hace falta hacer cuentas, hay una columna 'Rep count' en
ambos". That column is copied verbatim; nothing here is derived or computed.

THE ONE RISK, and the guard against it. Both trackers lay their two tables side
by side with NO shared key: the name is on the left, the Rep Count on the right,
and they are joined BY POSITION. Slip one row and somebody else's headcount
lands under a name, with nothing anywhere looking wrong. So every week is
checked against the cells the sheet ALREADY has for it (filled earlier from the
focus reports, a different source): a single disagreement aborts the whole run,
writing nothing. A week with fewer than MIN_CHECKS overlapping cells is written
but called out as UNVERIFIED, because "no check ran" and "the check passed" must
never look the same in the output.

Eve's rule for anyone missing from a tracker is "si no estan = 0" — but no zero
has been needed yet: every ICD has appeared on every tracker so far. A 0 written
because someone was hard to find in an image would be a claim, not a copy.

    python -m automations.org_active_headcount.tracker_fill
    python -m automations.org_active_headcount.tracker_fill --apply
"""
from __future__ import annotations

import argparse
import sys

from automations.recruiting_report.fill import open_by_key, _retry   # noqa: E402
from automations.org_active_headcount import structure as st         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:                                                    # noqa: BLE001
    pass

MIN_CHECKS = 4      # overlapping cells a week needs before it counts as verified

# {week header: {campaign box: {ICD: Rep Count off that week's tracker}}}
TRACKERS = {
    "WE 07.19": {                       # NDS + B2B trackers, 07/13-07/19
        "ATT NDS Team": {
            "Jairo Ruiz": 45, "Colten Wright": 36, "Drew Tepper": 26,
            "Frank Matos": 1, "Khalil Mansour": 21, "Joseph Delgado": 20,
            "Isaiah Revelle": 13, "George Delgado": 18, "Maxamad Aden": 9,
            "Jose Velasquez": 3,
        },
        "B2B": {
            "Atef Choudhury": 22, "Eveliz Wright": 26,
            "Carlos Hidalgo": 9, "Valeria Tristan": 4,
        },
    },
    "WE 07.26": {                       # NDS tracker, 07/20-07/26
        "ATT NDS Team": {
            "Jairo Ruiz": 34, "Colten Wright": 36, "Drew Tepper": 24,
            "Frank Matos": 17, "Khalil Mansour": 20, "Joseph Delgado": 19,
            "Isaiah Revelle": 12, "George Delgado": 16, "Maxamad Aden": 11,
            "Jose Velasquez": 4,
        },
    },
    "WE 08.23": {                       # NDS tracker, 08/17-08/23
        "ATT NDS Team": {
            "Jairo Ruiz": 34, "Colten Wright": 42, "Drew Tepper": 25,
            "Frank Matos": 22, "Khalil Mansour": 16, "Joseph Delgado": 22,
            "Isaiah Revelle": 16, "George Delgado": 13, "Maxamad Aden": 9,
            "Jose Velasquez": 7,
        },
    },
    "WE 08.16": {                       # NDS tracker, 08/10-08/16
        "ATT NDS Team": {
            "Jairo Ruiz": 29, "Colten Wright": 39, "Drew Tepper": 26,
            "Frank Matos": 22, "Khalil Mansour": 16, "Joseph Delgado": 24,
            "Isaiah Revelle": 19, "George Delgado": 14, "Maxamad Aden": 12,
            "Jose Velasquez": 7,
        },
    },
    "WE 08.09": {                       # NDS tracker, 08/03-08/09
        "ATT NDS Team": {
            "Jairo Ruiz": 34, "Colten Wright": 31, "Drew Tepper": 26,
            "Frank Matos": 19, "Khalil Mansour": 15, "Joseph Delgado": 21,
            "Isaiah Revelle": 16, "George Delgado": 18, "Maxamad Aden": 8,
            "Jose Velasquez": 7,
        },
    },
    "WE 08.02": {                       # NDS + B2B trackers, 07/27-08/02
        "ATT NDS Team": {
            "Jairo Ruiz": 39, "Colten Wright": 36, "Drew Tepper": 30,
            "Frank Matos": 23, "Khalil Mansour": 14, "Joseph Delgado": 25,
            "Isaiah Revelle": 15, "George Delgado": 19, "Maxamad Aden": 11,
            "Jose Velasquez": 7,
        },
        "B2B": {
            "Atef Choudhury": 24, "Eveliz Wright": 19,
            "Carlos Hidalgo": 11, "Valeria Tristan": 5,
        },
    },
}


def _col_for(box, week):
    return next((c for c, lbl in box["week_cols"] if lbl == week), None)


def _rows_for(per_box, campaign):
    """The tracker rows for this box, matching the label LOOSELY.

    Eve renames these boxes on the tab as the report settles - on 2026-09-07
    they went from 'ATT NDS Team' to 'ATT NDS Team Headcount' and the two Retail
    boxes merged into 'Retail NL / Internet Headcount'. An exact-match join
    silently found nothing and the script cheerfully reported '0 cells to write',
    which is the worst possible way to fail. Match on the tracker key being a
    prefix of the box label instead, so her wording wins and the join survives.
    """
    for key, rows in per_box.items():
        if campaign == key or campaign.lower().startswith(key.lower()):
            return rows
    return None


def run(apply_changes: bool = False) -> None:
    sh = open_by_key(st.SHEET_ID)
    ws = next(w for w in sh.worksheets() if w.title.strip() == st.BOARD_TAB)
    grid = ws.get_all_values()

    updates, bad, checks, unverified = [], [], {}, []
    for week, per_box in TRACKERS.items():
        for box in st.find_boxes(grid):
            rows = _rows_for(per_box, box["campaign"])
            if not rows:
                continue
            col = _col_for(box, week)
            if col is None:
                raise SystemExit(f"{box['campaign']}: no {week} column on the tab")
            key = f"{box['campaign']} {week}"
            checks.setdefault(key, 0)
            for row, icd in box["rows"]:
                if icd not in rows:
                    continue
                want, have = rows[icd], st.cell(grid, row, col)
                if have:
                    checks[key] += 1
                    if have != str(want):
                        bad.append(f"{key} {icd}: sheet={have} tracker={want}")
                    continue
                updates.append((f"{st.a1col(col)}{row}", want, key, icd))

    if bad:
        raise SystemExit(
            "tracker reading DISAGREES with the sheet - writing NOTHING:\n  "
            + "\n  ".join(bad))
    print("cross-check against what the sheet already had:")
    for key, n in sorted(checks.items()):
        mark = "ok" if n >= MIN_CHECKS else "UNVERIFIED - no cell to check against"
        print(f"  {key:24s} {n} agreement(s)  {mark}")
        if n < MIN_CHECKS:
            unverified.append(key)

    print(f"\ncells to write ({len(updates)}):")
    for a1, v, key, icd in updates:
        print(f"  {a1:>5s}  {key:24s} {icd:<20} <- {v}")
    if apply_changes and updates:
        _retry(ws.batch_update,
               [{"range": a1, "values": [[v]]} for a1, v, _k, _i in updates],
               value_input_option="USER_ENTERED")
    if unverified:
        print(f"\nWARNING: no independent check was possible for "
              f"{', '.join(unverified)} - those values rest on the image alone.")
    print(f"\n{len(updates)} cell(s) planned, "
          f"{len(updates) if apply_changes else 0} written.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    run(ap.parse_args().apply)
