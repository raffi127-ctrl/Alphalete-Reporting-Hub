"""READ-ONLY probe for the owner PNL (Jairo Ruiz first, 2026-10-27).

Downloads Tableau DirectDepositICDVIEWVersion2_0 > DDDETAILORG > 'ORG DD Detail'
(the same crosstab dd_no_captain uses) and prints, per owner asked for, the
newest DD weeks with Total $ to ICD summed per rep — what the PNL's
"Brought In" column will be. Writes no Sheet, sends nothing.

  python -m automations.owner_pnl.probe_dd                     # Jairo Ruiz
  python -m automations.owner_pnl.probe_dd --owner "Carlos Hidalgo"
  python -m automations.owner_pnl.probe_dd --csv FILE          # saved crosstab
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from automations.override_bulletin import pulls  # noqa: E402

OUT_DIR = REPO / "output" / "owner_pnl"
REP_COLS = ("REP.Name", "Rep Name", "REP Name", "Rep")


def _week(s):
    try:
        return dt.datetime.strptime(str(s).strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--owner", action="append",
                    help="owner name as Tableau writes it (default Jairo Ruiz)")
    ap.add_argument("--csv", help="parse this saved crosstab instead of downloading")
    ap.add_argument("--weeks", type=int, default=2, help="newest N DD weeks to print")
    a = ap.parse_args(argv)
    owners = a.owner or ["Jairo Ruiz"]

    if a.csv:
        path = Path(a.csv)
    else:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / "org_dd_detail.csv"
        download_crosstab_patchright(pulls.DD_DETAIL_VIEW, pulls.DD_DETAIL_SHEET, path)
    rows = pulls.read_crosstab(path)
    hdr = rows[0]
    print("source: Tableau > DirectDepositICDVIEWVersion2_0 > DDDETAILORG > '%s' "
          "(%d rows, %s)" % (pulls.DD_DETAIL_SHEET, len(rows) - 1, path))
    print("columns:", " | ".join(str(h) for h in hdr))

    oc = pulls._hdr_col(hdr, "cl.ICD Owner Name")
    wc = pulls._hdr_col(hdr, "cl.DD Week")
    tc = pulls._hdr_col(hdr, "Total $ to ICD")
    rc = next((c for c in (pulls._hdr_col(hdr, n) for n in REP_COLS) if c is not None), None)
    if None in (oc, wc, tc):
        raise SystemExit("missing owner/week/total column")
    print("rep column:", hdr[rc] if rc is not None else "NOT FOUND")

    all_owners = sorted({str(r[oc]).strip() for r in rows[1:] if len(r) > oc})
    for owner in owners:
        want = pulls._norm_name(owner)
        near = [o for o in all_owners if want.split()[0] in pulls._norm_name(o)]
        print("\n=== %s  (owner names that look like it: %s)" % (owner, near or "NONE"))
        weeks = {}
        for r in rows[1:]:
            if len(r) <= max(oc, wc, tc) or pulls._norm_name(r[oc]) != want:
                continue
            wk = _week(r[wc])
            if wk is None:
                continue
            rep = (str(r[rc]).strip() if rc is not None and len(r) > rc else "") or "(no rep)"
            amt = pulls._num_locale(r[tc]) or 0.0
            weeks.setdefault(wk, {}).setdefault(rep, 0.0)
            weeks[wk][rep] += amt
        if not weeks:
            print("  no DD rows for this owner")
            continue
        print("  DD weeks found:", ", ".join(str(w) for w in sorted(weeks, reverse=True)))
        for wk in sorted(weeks, reverse=True)[:a.weeks]:
            reps = weeks[wk]
            print("  -- DD week %s: %d reps, total $%s" % (wk, len(reps), format(sum(reps.values()), ",.2f")))
            for rep, amt in sorted(reps.items(), key=lambda x: -x[1]):
                print("     %-32s $%s" % (rep, format(amt, ",.2f")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
