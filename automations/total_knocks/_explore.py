"""Discovery throwaway: dump the FULL Ownerville 'Disposition by Rep' (p=89)
table — header row + a sample data row with column indices — so pull.py maps
all 14 Sheet columns against real source columns (no hardcoded guesses).

Run:  .venv/Scripts/python.exe -m automations.total_knocks._explore 2026-05-28
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys

from automations.shared.tableau_patchright import ownerville_session


def main() -> int:
    target = (sys.argv[1] if len(sys.argv) > 1
              else (dt.date.today() - dt.timedelta(days=1)).isoformat())
    d = dt.datetime.strptime(target, "%Y-%m-%d").date()
    mdy = d.strftime("%m/%d/%Y")
    print(f"Target date: {mdy}", flush=True)

    with ownerville_session(verbose=True) as page:
        # Capture master rqst from current URL.
        m = re.search(r"rqst=([A-Za-z0-9_\-]+)", page.url)
        rqst = m.group(1) if m else None
        print("rqst:", rqst, flush=True)

        url = (f"https://v2.ownerville.com/index.cfm?p=89&rqst={rqst}"
               f"&startDate={mdy}&endDate={mdy}")
        print("GET", url, flush=True)
        page.goto(url, wait_until="networkidle", timeout=25000)
        try:
            page.locator("select[name='table-dispositions_length']").select_option("100")
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # Header row (with index per cell).
        headers = page.evaluate(
            """() => {
                const t = document.querySelector('#table-dispositions');
                if (!t) return null;
                const ths = t.querySelectorAll('thead th, thead td');
                return Array.from(ths).map((th,i) => [i, (th.innerText||'').trim()]);
            }"""
        )
        print("\n=== HEADER (#table-dispositions) ===", flush=True)
        if headers is None:
            print("  table#table-dispositions NOT FOUND", flush=True)
        for i, txt in (headers or []):
            print(f"  [{i:>2}] {txt!r}", flush=True)

        # First N data rows, full cell text per index.
        rows = page.evaluate(
            """() => {
                const t = document.querySelector('#table-dispositions');
                if (!t) return [];
                const trs = t.querySelectorAll('tbody tr');
                return Array.from(trs).slice(0,3).map(tr =>
                    Array.from(tr.querySelectorAll('td')).map(td => (td.innerText||'').trim()));
            }"""
        )
        print(f"\n=== FIRST {len(rows)} DATA ROW(S) ===", flush=True)
        for r in rows:
            print("  " + " | ".join(f"[{i}]{v}" for i, v in enumerate(r)), flush=True)

        import pathlib
        p = pathlib.Path("output/total_knocks_disp_probe.json")
        p.parent.mkdir(exist_ok=True, parents=True)
        p.write_text(json.dumps({"date": mdy, "url": url,
                                 "headers": headers, "rows": rows},
                                indent=2), encoding="utf-8")
        print(f"\nProbe dump -> {p}", flush=True)
        page.wait_for_timeout(1000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
