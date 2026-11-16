"""Sales away from Fiber tier bonus — BUILD PROBE (Raf Loom, 2026-11-16).

Raf wants, for every Fiber office on Lucy Eco, a separate "Tier Bonus
Breakdown" post next to the metrics thread: an image of where each rep sits on
the New Fiber Internet rep volume tier ladder this week, and each rep tagged
"you're X away" from the next tier.

Source he showed: Tableau -> ATTTRACKER2_1-D2D -> view 'New Fiber Internet Rep
Breakdown' -> filters Owner Name / Rep (All) / Time Frame (order date, mon-sun)
'This Week' -> rows Owner Name | Rep Volume Bonus Tiers | Rep, columns Mon..Sun
+ Grand Total. Highlighted reps = 1 sale from the next tier.

This probe only READS: HTTP .csv + every Crosstab sheet + a screenshot into
output/fiber_tier_bonus/, and prints the shape (tier captions especially), so
the board is built on real columns. Writes no Sheet, posts nothing.

  python -m automations.fiber_tier_bonus.probe
"""
from __future__ import annotations

import csv
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "fiber_tier_bonus"
WORKBOOK = "ATTTRACKER2_1-D2D"
VIEW = "NewFiberInternetRepBreakdown"
VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            f"{WORKBOOK}/{VIEW}")
SAMPLE_OWNER = "rafael hidalgo"


def _rows(path: Path):
    raw = path.read_bytes()
    text = ""
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    delim = "\t" if text.count("\t") > text.count(",") else ","
    return list(csv.reader(text.splitlines(), delimiter=delim)), len(raw)


def _show(path: Path, label: str) -> None:
    rows, n = _rows(path)
    print(f"\n=== {label}: {path.name} — {len(rows)} rows, {n} bytes", flush=True)
    if not rows:
        return
    print("HEADER:", rows[0])
    for r in rows[1:16]:
        print("  ", r)
    for i, h in enumerate(rows[0][:6]):
        vals = sorted({r[i] for r in rows[1:] if i < len(r)})
        print(f"  col{i} {h!r}: {len(vals)} distinct -> {vals[:40]}")
    mine = [r for r in rows[1:] if any(SAMPLE_OWNER in c.lower() for c in r[:4])]
    print(f"  rows naming {SAMPLE_OWNER!r}: {len(mine)}")
    for r in mine[:80]:
        print("    ", r)


def main() -> int:
    from automations.shared.tableau_patchright import (
        tableau_session, requests_session_from_page, download_crosstab_patchright)
    from automations.alphalete_org_report import tableau_http
    from automations.recruiting_report.opt_phase import list_crosstab_sheets

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(TZ).strftime("%Y%m%d_%H%M")
    ok = False
    with tableau_session(verbose=True) as page:
        try:
            s = requests_session_from_page(page)
            p = tableau_http.download_view_csv(
                WORKBOOK, VIEW, OUT_DIR / f"probe_http_{stamp}.csv", session=s)
            _show(p, "HTTP .csv export")
            ok = True
        except Exception as e:  # noqa: BLE001 — probe: report and keep going
            print(f"HTTP export failed: {type(e).__name__}: {e}")
        try:
            sheets = list_crosstab_sheets(VIEW_URL, page=page, verbose=True)
        except Exception as e:  # noqa: BLE001
            print(f"listing crosstab sheets failed: {type(e).__name__}: {e}")
            sheets = []
        print(f"\nCrosstab sheets ({len(sheets)}): {sheets}")
        for i, sh in enumerate(sheets):
            try:
                p = download_crosstab_patchright(
                    VIEW_URL, sh, OUT_DIR / f"probe_xtab{i}_{stamp}.csv",
                    verbose=False, page=page)
                _show(p, f"Crosstab '{sh}'")
                ok = True
            except Exception as e:  # noqa: BLE001
                print(f"crosstab '{sh}' failed: {type(e).__name__}: {e}")
        try:
            shot = OUT_DIR / f"probe_view_{stamp}.png"
            page.goto(VIEW_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(15_000)
            page.screenshot(path=str(shot), full_page=True)
            print(f"\nscreenshot: {shot}")
        except Exception as e:  # noqa: BLE001
            print(f"screenshot failed: {type(e).__name__}: {e}")
    print("\nPROBE", "OK" if ok else "GOT NO DATA")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
