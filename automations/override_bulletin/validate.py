"""Lucy-1 discovery for the two remaining unknowns (ONE run):
  A. DD Detail — which Captain's-Bonus WEEKS are present in the default download?
     (validation showed only 7.18.26 — need to know if a DD-week filter is required
     and what value pulls the sheet's 7.12 week / Carlos $10,875.)
  B. ORG OVERRIDE SUMMARY — the real downloadable crosstab sheet name under a
     Period filter ('Consultant (+/-) Campaign' was wrong; dialog showed 1 thumb).
Writes to `_validate_out`. RUN ON LUCY 1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
OUT = Path("output/override_bulletin/validate")
TAB = "_validate_out"

_CAP_RE = re.compile(r"captain'?s?\s+bonus", re.I)
_WK = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def main(argv=None) -> int:
    from automations.shared.tableau_patchright import tableau_session
    from automations.override_bulletin import pulls as P
    from automations.recruiting_report import opt_phase as OP
    from automations.recruiting_report import fill as _fill
    OUT.mkdir(parents=True, exist_ok=True)
    dump = []

    def row(*c):
        dump.append([str(x) for x in c])

    with tableau_session(headless=True, verbose=True) as page:
        # A) DD Detail — distinct captain-bonus weeks + total per week
        row("=A: DD captain-bonus WEEKS present in default download=")
        try:
            from automations.shared.tableau_patchright import download_crosstab_patchright
            download_crosstab_patchright(P.DD_DETAIL_VIEW, P.DD_DETAIL_SHEET,
                                         OUT / "dd.csv", page=page, verbose=True)
            rows = P.read_crosstab(OUT / "dd.csv")
            weeks = {}
            for r in rows:
                cap = next((str(c) for c in r if _CAP_RE.search(str(c))), None)
                if not cap:
                    continue
                m = _WK.search(cap)
                if not m:
                    continue
                wk = f"{int(m.group(1))}.{int(m.group(2))}.{m.group(3)[-2:]}"
                amt = max((P._num_locale(c) or 0) for c in r)
                weeks[wk] = round(weeks.get(wk, 0) + amt, 2)
            row(f"{len(rows)} rows; captain-bonus weeks:")
            for wk in sorted(weeks):
                row(f"  week {wk}", f"total={weeks[wk]}")
        except Exception as e:  # noqa: BLE001
            row("DD FAILED", type(e).__name__, str(e)[:200])

        # A2) DD Detail WITH a DD-Week URL filter — try to pull 7/11 (sheet 7.12)
        for field, val in [("cl.DD Week", "7/11/2026"), ("cl.DD Week", "7/12/2026"),
                           ("DD Week", "7/11/2026")]:
            try:
                url = P._with_filter(P.DD_DETAIL_VIEW, field, val)
                download_crosstab_patchright(url, P.DD_DETAIL_SHEET,
                                             OUT / "ddf.csv", page=page, verbose=True)
                rows = P.read_crosstab(OUT / "ddf.csv")
                caro = P.parse_dd_captain(rows, {P._norm_name("Carlos Hidalgo")})
                row(f"DD filter {field}={val}", f"carlos={caro.get(P._norm_name('Carlos Hidalgo'))}")
            except Exception as e:  # noqa: BLE001
                row(f"DD filter {field}={val} FAILED", str(e)[:120])

        # B) ORG summary — real crosstab sheet name(s) under a Period filter
        row("=B: ORG OVERRIDE SUMMARY crosstab sheet names=")
        for period in ("Period 2026-7", "Period 7", None):
            url = P.ORG_SUMMARY_VIEW if period is None else P._with_filter(
                P.ORG_SUMMARY_VIEW, "Period", period)
            try:
                sheets = OP.list_crosstab_sheets(url, page=page, settle_s=8, max_s=45)
                row(f"period={period!r}", f"sheets={sheets}")
            except Exception as e:  # noqa: BLE001
                row(f"period={period!r} FAILED", type(e).__name__, str(e)[:140])

    try:
        wb = _fill._client().open_by_key(WORKBOOK_ID)
        try:
            ws = wb.worksheet(TAB)
            ws.clear()
        except Exception:  # noqa: BLE001
            ws = wb.add_worksheet(title=TAB, rows=200, cols=40)
        ws.update([[str(c)[:90] for c in r] for r in dump], "A1", value_input_option="RAW")
        print(f"wrote {len(dump)} rows to {TAB!r}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"couldn't write {TAB}: {type(e).__name__}: {e}", flush=True)
    print("discovery done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
