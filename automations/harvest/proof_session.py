"""Prove that ONE shared Tableau login returns the same data as N logins.

Megan 2026-08-17, Lever A: cut the number of times we sign in to Tableau
without compromising correctness or speed. `TABLEAU_SHARED_SESSION=1` makes a
process log in once and open a fresh page per pull instead of a fresh LOGIN per
pull. This script is the gate before that flag is turned on for a report.

Why a gate is needed: fiber_activations documented a real Tableau bug
(2026-05-27) where reusing a session across pulls of the CaptainsBonus view made
the Weekending URL filter silently stop applying on the 3rd+ call — it returned
last-completed-week 3,072 instead of current-week 221. Wrong numbers, no error.
A fresh page per pull should avoid it, but "should" is not "does", so we measure.

METHOD — A / B / A', in that order, same process, same minute:
    A   legacy  (one login per pull)   <- today's behaviour
    B   shared  (one login total)      <- the candidate
    A'  legacy  again
Then:
    A == A' and B == A   -> PROVEN. The flag is safe for these pulls.
    A != A'              -> INCONCLUSIVE. The underlying data moved mid-test;
                            rerun when the extract is quiet.
    A == A' and B != A   -> FAILED. Sharing the login changes the data. Do not
                            flip this report.

Usage:
    python -m automations.harvest.proof_session --report raf_captainship_bonus
    python -m automations.harvest.proof_session --url "<view url>" --sheet "CB Activations (Raf)" \\
                                                --url "<view url>" --sheet "CB Appr + Churn (Raf)"

Downloads only. Writes no Sheet, posts no Slack.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "output" / "harvest-session-proof"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _pull_all(pairs: List[Tuple[str, str]], dest: Path, *, shared: bool,
              verbose: bool) -> List[Path]:
    """Run every (url, sheet) pull into dest. `shared` toggles the flag for the
    duration — set BEFORE importing the download helper's call, since the helper
    reads the env at call time."""
    from automations.shared import tableau_patchright as TP

    prev = os.environ.get("TABLEAU_SHARED_SESSION")
    os.environ["TABLEAU_SHARED_SESSION"] = "1" if shared else "0"
    dest.mkdir(parents=True, exist_ok=True)
    out: List[Path] = []
    try:
        for i, (url, sheet) in enumerate(pairs):
            p = dest / f"{i:02d}_{sheet.replace('/', '_')[:40]}.csv"
            TP.download_crosstab_patchright(url, sheet, p, verbose=verbose)
            out.append(p)
    finally:
        # Always tear the shared context down between phases, so phase B's login
        # can't leak into A'. Without this, A' would be measuring B.
        try:
            TP.close_shared_session()
        except Exception:
            pass
        if prev is None:
            os.environ.pop("TABLEAU_SHARED_SESSION", None)
        else:
            os.environ["TABLEAU_SHARED_SESSION"] = prev
    return out


def _pairs_for_report(report_id: str) -> List[Tuple[str, str]]:
    from automations.harvest.needs import needs_for_report
    needs = needs_for_report(report_id)
    if not needs:
        raise SystemExit(
            f"No declared needs for {report_id!r}. Either pass --url/--sheet "
            f"explicitly, or generate the registry first:\n"
            f"  python -m automations.harvest.from_ledger --days 7 --write")
    return [(n.view_url, n.crosstab_sheet) for n in needs]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harvest-proof-session")
    ap.add_argument("--report", help="report_id whose declared needs to test")
    ap.add_argument("--url", action="append", default=[],
                    help="view url (repeatable; pair with --sheet in order)")
    ap.add_argument("--sheet", action="append", default=[],
                    help="crosstab sheet (repeatable)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.url or a.sheet:
        if len(a.url) != len(a.sheet):
            ap.error(f"--url given {len(a.url)}x but --sheet {len(a.sheet)}x — "
                     f"they pair up in order")
        pairs = list(zip(a.url, a.sheet))
    elif a.report:
        pairs = _pairs_for_report(a.report)
    else:
        ap.error("pass --report or --url/--sheet")

    verbose = not a.quiet
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    root = OUT_ROOT / stamp
    label = a.report or f"{len(pairs)} pull(s)"

    print(f"=== session proof: {label} — {len(pairs)} pull(s), 3 phases ===")
    for u, s in pairs:
        print(f"  · {s}  ←  {u[:80]}")
    print()

    print("--- phase A: legacy (one login per pull) ---")
    A = _pull_all(pairs, root / "A_legacy", shared=False, verbose=verbose)
    print("--- phase B: shared (one login total) ---")
    B = _pull_all(pairs, root / "B_shared", shared=True, verbose=verbose)
    print("--- phase A': legacy again (drift control) ---")
    A2 = _pull_all(pairs, root / "A2_legacy", shared=False, verbose=verbose)

    print()
    print(f"{'sheet':44s} {'A':>17s} {'B':>17s} {'A2':>17s}")
    print("-" * 100)
    drift = mismatch = 0
    for (url, sheet), pa, pb, pa2 in zip(pairs, A, B, A2):
        ha, hb, ha2 = _sha(pa), _sha(pb), _sha(pa2)
        flag = ""
        if ha != ha2:
            drift += 1
            flag = "  <- DATA MOVED (inconclusive)"
        elif hb != ha:
            mismatch += 1
            flag = "  <- SHARED SESSION DIFFERS"
        print(f"{sheet[:43]:44s} {ha:>17s} {hb:>17s} {ha2:>17s}{flag}")

    print()
    if drift:
        verdict = (f"INCONCLUSIVE — {drift} pull(s) changed between the two "
                   f"legacy runs. The extract moved mid-test; rerun when quiet.")
        rc = 2
    elif mismatch:
        verdict = (f"FAILED — {mismatch} pull(s) differ under a shared login. "
                   f"Do NOT set TABLEAU_SHARED_SESSION for {label}.")
        rc = 1
    else:
        verdict = (f"PROVEN — every pull is byte-identical under one shared "
                   f"login. TABLEAU_SHARED_SESSION=1 is safe for {label}, and "
                   f"drops it from {len(pairs)} logins to 1.")
        rc = 0
    print(verdict)
    print(f"artifacts: {root}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
