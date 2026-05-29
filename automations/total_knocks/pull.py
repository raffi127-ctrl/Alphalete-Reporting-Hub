"""Pull — scrape Ownerville 'TeleMapper Leads → Disposition by Rep' (p=89)
for a single day and return one record per rep, keyed by the canonical
Total Knocks Sheet headers.

Source of truth for columns is the LIVE table header row, matched by
normalized header text — never fixed cell indices (the repo rule:
templates change, label/header lookup survives, indices don't).

Run standalone to preview yesterday's scrape WITHOUT touching the Sheet:
    .venv/Scripts/python.exe -m automations.total_knocks.pull            # yesterday
    .venv/Scripts/python.exe -m automations.total_knocks.pull 2026-05-28 # a date
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from typing import Optional

from automations.shared.tableau_patchright import ownerville_session

# ---------------------------------------------------------------------------
# Canonical Sheet columns (exactly as they appear in 'Rep Total Knocks
# Template' row 1, left→right). 'Total Talk to' is CALCULATED here, not
# scraped — every other column is pulled straight from Disposition by Rep.
# ---------------------------------------------------------------------------
COL_ID                  = "ID"
COL_REP                 = "Rep"
COL_TOTAL_LEADS_KNOCKED = "Total Leads Knocked"
COL_TOTAL_KNOCKS        = "Total Knocks"
COL_TOTAL_TALK_TO       = "Total Talk to"     # calculated
COL_FIRST_KNOCK         = "First Knock"
COL_LAST_KNOCK          = "Last Knock"
COL_NO_ANSWER           = "No answer"
COL_TALK_TO_NI          = "Talk To - Not Interested"
COL_PRES_NI             = "Presentation – Not Interested"
COL_COME_BACK           = "Come Back"
COL_SALE                = "Sale"
COL_INACCESSIBLE        = "Inaccessible"
COL_DO_NOT_KNOCK        = "Do Not Knock"

# Left→right order the Sheet expects.
SHEET_COLUMNS = [
    COL_ID, COL_REP, COL_TOTAL_LEADS_KNOCKED, COL_TOTAL_KNOCKS,
    COL_TOTAL_TALK_TO, COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_NO_ANSWER,
    COL_TALK_TO_NI, COL_PRES_NI, COL_COME_BACK, COL_SALE,
    COL_INACCESSIBLE, COL_DO_NOT_KNOCK,
]

# 'Total Talk to' = sum of these five disposition counts (per Eve):
# Talk To-Not Interested + Presentation-Not Interested + Come Back + Sale
# + Do Not Knock. Excludes 'No answer' and 'Inaccessible' (no one talked to).
TALK_TO_PARTS = [
    COL_TALK_TO_NI, COL_PRES_NI, COL_COME_BACK, COL_SALE, COL_DO_NOT_KNOCK,
]

# Count columns parsed as ints (blank → 0). First/Last Knock stay as the
# source time strings; ID + Rep stay as-is.
COUNT_COLUMNS = {
    COL_TOTAL_LEADS_KNOCKED, COL_TOTAL_KNOCKS, COL_NO_ANSWER, COL_TALK_TO_NI,
    COL_PRES_NI, COL_COME_BACK, COL_SALE, COL_INACCESSIBLE, COL_DO_NOT_KNOCK,
}

DISP_TABLE = "table#table-dispositions"


def _norm(s: str) -> str:
    """Normalize a header for matching: lowercase, drop every non-alphanumeric
    (so an en-dash, the mojibake '�', or extra spaces all collapse), then
    squeeze whitespace. 'Presentation – Not Interested', 'Presentation �
    Not Interested', and 'presentation  not  interested' all map to the same key.
    """
    s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _to_int(s: str) -> int:
    s = (s or "").strip().replace(",", "")
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return 0


def _yesterday() -> dt.date:
    return dt.date.today() - dt.timedelta(days=1)


def _capture_rqst(page) -> Optional[str]:
    """Read the master rqst token. The post-login URL is sometimes the v1
    ownerville.com landing (no rqst); navigating to the v2 root reliably
    hands back a master Welcome URL carrying ?rqst=… (same trick the focus
    report uses)."""
    m = re.search(r"rqst=([A-Za-z0-9_\-]+)", page.url)
    if m:
        return m.group(1)
    page.goto("https://v2.ownerville.com/", wait_until="networkidle", timeout=25000)
    m = re.search(r"rqst=([A-Za-z0-9_\-]+)", page.url)
    return m.group(1) if m else None


def _navigate(page, rqst: str, target_mdy: str) -> None:
    """Disposition by Rep filters via URL ?startDate=&endDate= (server-side);
    the on-page picker only sets local JS vars. Single-day = same start/end."""
    url = (f"https://v2.ownerville.com/index.cfm?p=89&rqst={rqst}"
           f"&startDate={target_mdy}&endDate={target_mdy}")
    page.goto(url, wait_until="networkidle", timeout=25000)
    try:  # show all rows on one page where possible
        page.locator("select[name='table-dispositions_length']").select_option("100")
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass


def _header_index(page) -> dict:
    """Map normalized source-header text → 0-based column index, read live."""
    headers = page.evaluate(
        """() => {
            const t = document.querySelector('#table-dispositions');
            if (!t) return [];
            return Array.from(t.querySelectorAll('thead th, thead td'))
                .map(th => (th.innerText||'').trim());
        }"""
    )
    return {_norm(h): i for i, h in enumerate(headers)}


def _scrape_rows(page, idx: dict) -> list[dict]:
    """Walk every DataTables page, return one canonical-keyed dict per rep."""
    # Resolve the source column index for each Sheet column we scrape.
    want = {c: idx.get(_norm(c)) for c in SHEET_COLUMNS if c != COL_TOTAL_TALK_TO}
    missing = [c for c, i in want.items() if i is None]
    if missing:
        raise RuntimeError(
            "Disposition table is missing expected column(s): "
            + ", ".join(missing)
            + ". Live headers were: " + ", ".join(sorted(idx)) + "."
        )

    table = page.locator(DISP_TABLE)
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('#table-dispositions tbody tr').length >= 1",
            timeout=10000,
        )
    except Exception:
        return []

    out: list[dict] = []
    seen_ids: set[str] = set()
    for _ in range(20):  # safety cap on pagination
        for tr in table.locator("tbody tr").all():
            cells = [c.inner_text().strip() for c in tr.locator("td").all()]
            if not cells:
                continue
            if cells[0].lower().startswith("no data"):
                continue
            # Need every resolved index to be present in this row.
            if max(want.values()) >= len(cells):
                continue
            rec: dict = {}
            for col, i in want.items():
                raw = cells[i]
                rec[col] = _to_int(raw) if col in COUNT_COLUMNS else raw
            rec[COL_TOTAL_TALK_TO] = sum(int(rec[p] or 0) for p in TALK_TO_PARTS)
            # De-dupe by badge ID (a rep shouldn't appear twice in one day).
            rid = str(rec.get(COL_ID, "")).strip()
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            out.append(rec)

        nxt = page.locator("#table-dispositions_next").first
        if nxt.count() == 0 or "disabled" in (nxt.get_attribute("class") or ""):
            break
        nxt.click()
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
    return out


def pull_disposition_day(target: Optional[dt.date] = None,
                         verbose: bool = True) -> tuple[dt.date, list[dict]]:
    """Scrape Disposition by Rep for `target` (default: yesterday).
    Returns (date, [rep_record, ...]) with each record keyed by SHEET_COLUMNS."""
    target = target or _yesterday()
    mdy = target.strftime("%m/%d/%Y")
    with ownerville_session(verbose=verbose) as page:
        rqst = _capture_rqst(page)
        if not rqst:
            raise RuntimeError("Couldn't capture ownerville rqst token from "
                               f"{page.url!r} after login.")
        if verbose:
            print(f"-> Disposition by Rep for {mdy} (rqst {rqst[:12]}…)", flush=True)
        _navigate(page, rqst, mdy)
        idx = _header_index(page)
        rows = _scrape_rows(page, idx)
    return target, rows


def _print_preview(target: dt.date, rows: list[dict]) -> None:
    print(f"\n=== Disposition by Rep — {target.isoformat()} "
          f"({len(rows)} rep(s)) ===")
    show = [COL_ID, COL_REP, COL_TOTAL_KNOCKS, COL_TOTAL_TALK_TO,
            COL_FIRST_KNOCK, COL_LAST_KNOCK, COL_SALE]
    print("  " + " | ".join(f"{c}" for c in show))
    for r in rows[:25]:
        print("  " + " | ".join(str(r.get(c, "")) for c in show))
    if len(rows) > 25:
        print(f"  … +{len(rows) - 25} more")


def main() -> int:
    target = None
    if len(sys.argv) > 1:
        target = dt.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    target, rows = pull_disposition_day(target)
    _print_preview(target, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
