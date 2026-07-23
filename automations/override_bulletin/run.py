"""Override Bulletin — end-to-end weekly run (roll → pull → assemble → write →
render). DRY-RUN + SANDBOX by default; posting/emailing is a separate, explicit
step (never auto-send — standing rule). Tableau pulls need Lucy 1 (Raf's login).

    python -m automations.override_bulletin.run --week 7.12.26           # dry, sandbox
    python -m automations.override_bulletin.run --week 7.12.26 --write   # sandbox write

Flow:
  1. read the roster (Active-ICD=YES) + captain rows from the target tab
  2. pull each source for the week (regular / raf-special / dd-captains / ledger)
  3. flatten the DD per-week dict to the sheet week (see _dd_week_for)
  4. assemble section-1 + section-2, collect unmatched (reported, never zeroed)
  5. write into the newest week column (dry-run prints; --write refuses live tab)
  6. print the reconcile summary + unmatched + pending markers
"""
from __future__ import annotations

import argparse
import sys

from automations.override_bulletin import fill as F
from automations.override_bulletin import pulls as P
from automations.override_bulletin.pulls import _norm_name

# The five captains whose captain override comes from DD (Raf's is from the PNL).
DD_CAPTAINS = ["Carlos Hidalgo", "Colten Wright", "Khalil Mansour",
               "Jairo Ruiz", "Eveliz Wright"]
LEDGER_SPECIAL = "Special Override"   # needle refined to period at call time
LEDGER_CREDICO = "Credico"


def _dd_week_for(dd_weeks, sheet_week):
    """Amount for the sheet's Sunday week from a captain's DD per-week dict.

    The DD Detail default download carries only the just-closed week, labelled a
    day behind the sheet (sheet Sunday 7.19 ↔ DD 7.18). So: exact label, then the
    day-behind neighbour, then — since the download holds a single week — that one
    week as the fallback. Returns the amount, or None if the captain has no row."""
    if sheet_week in dd_weeks:
        return dd_weeks[sheet_week]
    from datetime import datetime, timedelta
    m, d, y = (int(x) for x in sheet_week.split("."))
    try:                                              # DD runs a day behind
        prev = datetime(2000 + y, m, d) - timedelta(days=1)
    except ValueError:
        return None
    # NO single-week fallback: if the download doesn't hold this week, the captain
    # is reported as unmatched rather than filled with another week's number.
    return dd_weeks.get(f"{prev.month}.{prev.day}.{prev.year % 100}")


def pull_all(week_mdy, week_header, period_num, period_year, *, page=None, verbose=True):
    """Run every Lucy-1 pull for the week; return the flat dicts assemble() wants.
    `page` is a live tableau_session page (shared holder). Returns
    (regular, captain, special)."""
    out_dir = P.__dict__.get("_OUT")  # optional override
    from pathlib import Path
    d = Path("output/override_bulletin/run")
    d.mkdir(parents=True, exist_ok=True)

    regular = P.regular_overrides(week_header, d / "org.csv",
                                  period=f"Period {period_year}-{period_num}",
                                  page=page, verbose=verbose)
    raf_special = P.raf_special_override(week_header, d / "raf.csv",
                                         period=f"Period {period_num}",
                                         page=page, verbose=verbose)
    dd = P.dd_captain_overrides(DD_CAPTAINS, d / "dd.csv", page=page, verbose=verbose)
    captain = {k: _dd_week_for(v, week_mdy) for k, v in dd.items()}
    captain = {k: v for k, v in captain.items() if v is not None}

    # Ledger special/credico — period-scoped needle (special) + month label (credico)
    special_led = P.ledger_amounts(f"P{period_num}-{period_year} {LEDGER_SPECIAL}",
                                   d / "led_special.csv", page=page, verbose=verbose)
    special = dict(special_led)
    special[_norm_name("Rafael Hidalgo")] = raf_special or special.get(
        _norm_name("Rafael Hidalgo"))
    # credico folds into the regular component (per FILL_SOURCES)
    return regular, captain, special


def run(week_mdy, *, tab=F.SANDBOX_TAB, write=False, verbose=True):
    from automations.recruiting_report import fill as _fill
    from automations.shared.tableau_patchright import tableau_session
    wb = _fill._client().open_by_key(F.WORKBOOK_ID)
    ws = wb.worksheet(tab)
    roster = F.read_roster(ws)
    captains = F.read_captains(ws)
    active = sum(1 for _, a, _ in roster.values() if a)
    print(f"tab={tab!r}  roster={len(roster)} ({active} active)  captains={len(captains)}")

    m, d, y = week_mdy.split(".")
    week_header = f"{int(m)}/{int(d)}/20{y[-2:]}"
    with tableau_session(headless=True, verbose=verbose) as page:
        regular, captain, special = pull_all(week_mdy, week_header,
                                             period_num=int(m), period_year=f"20{y[-2:]}",
                                             page=page, verbose=verbose)
    print(f"pulls: regular={len(regular)}  captain={len(captain)}  special={len(special)}")

    section1, section2, unmatched = F.assemble(
        week_mdy, roster, captains,
        regular=regular, captain=captain, special=special, ws=ws)
    col = F.write_week(ws, section1, section2, dry_run=not write)
    print(f"\nwrote {len(section1)} ALL-ORG + {len(section2)} CAPTAIN cells to col {col}")
    if unmatched:
        print(f"\n⚠ UNMATCHED (active, not found — REPORT on email, do not zero):")
        for n in unmatched:
            print(f"    • {n}")
    return section1, section2, unmatched


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", required=True, help="sheet week label, e.g. 7.12.26")
    ap.add_argument("--tab", default=F.SANDBOX_TAB)
    ap.add_argument("--write", action="store_true", help="write (sandbox tab only)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    run(a.week, tab=a.tab, write=a.write, verbose=not a.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
