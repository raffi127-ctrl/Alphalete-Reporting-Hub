"""NDS Activation Rate by rep — BUILD STAGE (Eve, 2026-11-10).

Ask (Raf + Dylan Twaddle, Slack 2026-11-09 21:55): an ongoing report, like
the cancel-rate one, of each NDS rep's trailing activation rate at 10-19,
20-29 and 30-60 days.

SOURCE
  Tableau -> NDS-SN (RES-ATT-OOF) Workbook -> view ChurnActivationRateRep
  ("Activation & Churn Metrics (Rep)"; filters NDS Captain Teams / ICD Owner /
  ICD Rep Name / Non-BYOD or BYOD)
  https://us-east-1.online.tableau.com/#/site/sci/views/NDS-SNRES-ATT-OOFWorkbook/ChurnActivationRateRep

Right now this module only PROBES: it writes nothing to any Sheet and posts
nothing. It saves what Tableau hands back to output/nds_activation_rate/ and
prints the shape, so the fill can be built against real column names.

  python -m automations.nds_activation_rate.run --probe
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

WORKBOOK = "NDS-SNRES-ATT-OOFWorkbook"
VIEW = "ChurnActivationRateRep"
VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            f"{WORKBOOK}/{VIEW}?:iid=1")
TZ = ZoneInfo("America/Chicago")
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "nds_activation_rate"


def _show_csv(path: Path, label: str, max_rows: int = 25) -> None:
    raw = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    delim = "\t" if text.count("\t") > text.count(",") else ","
    rows = list(csv.reader(text.splitlines(), delimiter=delim))
    print(f"\n=== {label}: {path.name} — {len(rows)} rows, {len(raw)} bytes")
    if not rows:
        return
    print("HEADER:", rows[0])
    for r in rows[1:max_rows + 1]:
        print("  ", r)
    # Distinct values per column (first 8 columns) — tells us which column is
    # captain / owner / rep / window without guessing.
    for i, h in enumerate(rows[0][:8]):
        vals = sorted({r[i] for r in rows[1:] if i < len(r)})
        print(f"  col {i} {h!r}: {len(vals)} distinct -> {vals[:15]}")


def probe() -> int:
    from automations.shared.tableau_patchright import (
        tableau_session, requests_session_from_page, download_crosstab_patchright)
    from automations.alphalete_org_report import tableau_http
    from automations.recruiting_report.opt_phase import list_crosstab_sheets

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(TZ).strftime("%Y%m%d_%H%M")
    ok = False
    with tableau_session(verbose=True) as page:
        # 1) the HTTP .csv export (no dialog) — whatever sheet Tableau picks
        try:
            s = requests_session_from_page(page)
            p = tableau_http.download_view_csv(
                WORKBOOK, VIEW, OUT_DIR / f"probe_http_{stamp}.csv", session=s)
            _show_csv(p, "HTTP .csv export")
            ok = True
        except Exception as e:  # noqa: BLE001 — probe: report and keep going
            print(f"HTTP export failed: {type(e).__name__}: {e}")

        # 2) every worksheet the Crosstab dialog offers
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
                _show_csv(p, f"Crosstab '{sh}'")
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", action="store_true",
                    help="download the view + print its shape; writes nothing")
    args = ap.parse_args(argv)
    if not args.probe:
        print("Only --probe exists yet (build stage). Nothing to fill.")
        return 2
    return probe()


if __name__ == "__main__":
    sys.exit(main())
