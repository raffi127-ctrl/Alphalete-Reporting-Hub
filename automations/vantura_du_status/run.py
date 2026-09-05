"""Daily Update status reconcile — Sundays (Carlos 2026-09-04).

Nothing has ever maintained the Daily Update's Status column: Lucy's 8:45pm fill
APPENDS rows with their initial status, the VA used to fix the rest by hand,
and terminations on the board/Roll Call never flowed back (Jayden read
"Not Active" for months while actively selling — the reverse rot). This is
the missing half of the VA's runbook, as Carlos specced it:

  Every Sunday, for each Daily Update row whose Status (col A) is "Active" or
  "Orientation Scheduled": find the person on the Roll Call. If their most
  recent Roll Call row says they're gone — Status "Terminated", or a T in
  the attendance columns (terminations stamp T through Saturday, so col L
  always carries one) — flip the DU row to "Not Active".

  * A person NOT on the Roll Call is LEFT ALONE (Orientation Scheduled
    people usually haven't started; absence is not evidence).
  * Only the person's MOST RECENT week's row counts — an old Terminated row
    must never beat a current Active one (the Jayden lesson).
  * Names bridge through the master's own "Name Aliases" tab both ways.

DRY-RUN by default; --write flips statuses. Runs on LUCY 2 Sundays 7pm via
com.alphalete.vantura-du-status (install_vantura_du_status_agent).

  python -m automations.vantura_du_status.run            # dry preview
  python -m automations.vantura_du_status.run --write    # apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import unicodedata

SHEET_ID = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"   # Vantura Master
DU_TAB, ROLL_TAB, ALIAS_TAB = "Daily Update", "Roll Call", "Name Aliases"
FLIP_FROM = ("active", "orientation scheduled")
R_WEEK, R_STATUS, R_NAME = 0, 1, 3          # Roll Call A/B/D (0-based)
R_ATT0, R_ATT1 = 6, 12                      # attendance G:L


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _we_date(we: str):
    """'m.d' week label -> date, same nearest-year rule as the bound script."""
    p = str(we or "").split(".")
    if len(p) != 2:
        return None
    try:
        mo, da = int(p[0]), int(p[1])
    except ValueError:
        return None
    now = dt.date.today()
    best, best_diff = None, None
    for y in (now.year - 1, now.year, now.year + 1):
        try:
            d = dt.date(y, mo, da)
        except ValueError:
            continue
        if (d - now).days <= 31:
            diff = abs((d - now).days)
            if best is None or diff < best_diff:
                best, best_diff = d, diff
    return best


def latest_roll_rows(roll_vals, aliases):
    """{normalized name: (week_date, status, has_T)} using the newest row."""
    out = {}
    for r in roll_vals[2:]:
        if len(r) <= R_NAME:
            continue
        nm = _norm(r[R_NAME])
        if not nm:
            continue
        wed = _we_date(r[R_WEEK] if len(r) > R_WEEK else "") or dt.date.min
        status = str(r[R_STATUS]).strip() if len(r) > R_STATUS else ""
        att = [str(x).strip().upper() for x in r[R_ATT0:R_ATT1]]
        has_t = "T" in att
        for key in {nm} | aliases.get(nm, set()):
            cur = out.get(key)
            if cur is None or wed > cur[0]:
                out[key] = (wed, status, has_t)
    return out


def load_aliases(sh):
    """Both-ways bridges from the master's Name Aliases tab."""
    out = {}
    try:
        for r in sh.worksheet(ALIAS_TAB).get_all_values()[1:]:
            if len(r) > 1 and r[0].strip() and r[1].strip():
                a, b = _norm(r[0]), _norm(r[1])
                out.setdefault(a, set()).add(b)
                out.setdefault(b, set()).add(a)
    except Exception as e:  # noqa: BLE001 — aliases are a bonus, not a gate
        _log(f"Name Aliases unreadable ({e}) — continuing without bridges")
    return out


def du_columns(du_vals):
    """(header_row_idx, status_col, name_col), located by header like the
    bound script does — the DU layout is the VA's and drifts."""
    for i, row in enumerate(du_vals[:6]):
        for j, c in enumerate(row):
            if str(c).strip().lower() == "name":
                return i, 0, j
    return 0, 0, 8      # the VA's classic layout: A status, I name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="apply the flips")
    a = ap.parse_args(argv)

    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(SHEET_ID)
    du_ws = sh.worksheet(DU_TAB)
    du_vals = du_ws.get_all_values()
    roll_vals = sh.worksheet(ROLL_TAB).get_all_values()
    aliases = load_aliases(sh)
    roll = latest_roll_rows(roll_vals, aliases)

    hdr, c_status, c_name = du_columns(du_vals)
    _log(f"Daily Update: {len(du_vals)} rows; status col {c_status + 1}, "
         f"name col {c_name + 1}; roll people: {len(roll)}")

    plan, unmatched = [], 0
    for i, r in enumerate(du_vals):
        if i <= hdr or len(r) <= max(c_status, c_name):
            continue
        status = str(r[c_status]).strip()
        if status.lower() not in FLIP_FROM:
            continue
        nm = _norm(r[c_name])
        if not nm:
            continue
        hit = roll.get(nm)
        if hit is None:
            unmatched += 1          # not on the roll -> leave alone, by design
            continue
        _wed, rstatus, has_t = hit
        if rstatus.lower() == "terminated" or has_t:
            why = ("roll status Terminated" if rstatus.lower() == "terminated"
                   else f"T in attendance (roll status {rstatus or '?'})")
            plan.append((i + 1, r[c_name].strip(), status, why))

    _log(f"{len(plan)} row(s) to flip to Not Active; "
         f"{unmatched} Active/Scheduled row(s) not on the roll (left alone)")
    for row, name, was, why in plan:
        _log(f"  r{row:<5} {name:<30} {was} -> Not Active   ({why})")

    if not a.write:
        _log("DRY RUN — re-run with --write to apply")
        return 0
    if plan:
        from gspread.utils import rowcol_to_a1
        _retry(du_ws.batch_update,
               [{"range": rowcol_to_a1(row, c_status + 1),
                 "values": [["Not Active"]]} for row, _n, _w, _y in plan],
               value_input_option="RAW")
        _log(f"wrote {len(plan)} status flip(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
