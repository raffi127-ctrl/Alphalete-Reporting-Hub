"""Frontier OPT Data Pull — upload-based PDF fill for the Alphalete Org sheet.

Unlike the Tableau-scraping OPT modules, this one reads the manually
downloaded Frontier PDFs. The reports come out on their own cadence; a user
drops whichever PDF(s) arrived into a folder and we decipher where each is
applicable and fill only those rows on the matching " - Frontier" tab —
everything else is left untouched (partial-upload safe).

Three independent PDF sources feed it:
  - "Daily Sales - Frontier - Events by Store" → per-store production + HC
  - "Daily Sales - Frontier - Events"          → GIG % / VAS % / ABP %
  - "Quality Scorecard - Frontier"             → Approval / Canceled / Pending

Per Megan 2026-05-24:
  - Per-store production = the 'Data' column on the by-store PDF, for each
    store whose Owner Name matches the tab's ICD. A listed store with no
    production that week is written 0.
  - Total Sales Frontier        = sum of all the ICD's stores' Data.
  - Total Store Count Frontier   = # stores with production > 0 that week.
  - AVG Sales per Store          = sheet FORMULA (Total Sales / Store Count),
                                   cells looked up by label (never hardcoded).
  - Active Headcount on Scorecard = sum of 'Scoring HC' across the ICD's
                                   stores that week.
  - New store with production but no row yet → inserted (like Costco/JE).

Week mapping: the PDF weeks end Saturday; the sheet columns end Sunday.
Frontier WE-Sat maps to the next day's sheet WE-Sun (5/16 -> 5/17,
5/23 -> 5/24). The "Current Sales Week" page is in-progress and is
skipped by default (include_current=True fills it too).

Multiple / duplicate uploads: every page of every PDF is read; for each
week-ending the most-recently-generated PDF wins (by the timestamp printed
inside the PDF), so re-uploading — or accidentally uploading the same file
twice — just refreshes that week to current numbers.

Source notes: resources/opt-section/alphalete-org-campaign-sources.md.
"""

import datetime as dt
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import gspread
import pdfplumber

from automations.recruiting_report import fill as rfill
from automations.alphalete_org_report.opt_nds import (
    ALPHALETE_ORG_SHEET_ID,
    _find_week_col,
    _find_row_by_label,
)

_CENTRAL = ZoneInfo("America/Chicago")


def _parse_week_label(lbl: str) -> dt.date:
    """Reverse of _week_label: '6/7/26' -> date(2026, 6, 7)."""
    return dt.datetime.strptime(lbl, "%m/%d/%y").date()


def _latest_week_only(d: Dict) -> Dict:
    """Keep only the most-recent week. The by-store / events PDFs carry the
    Current + Prior + 2nd-Prior weeks (one per page); we only want the latest
    COMPLETED weekending — the 'Prior Sales Week' page — never the older ones
    (Megan 2026-06-08)."""
    if len(d) <= 1:
        return d
    latest = max(d, key=_parse_week_label)
    return {latest: d[latest]}


def _run_week_label() -> str:
    """The week the report is being run for = the most-recent COMPLETED WE
    Sunday, anchored to Central. The Quality Scorecard arrives ~2 weeks late
    but must ALWAYS land on this column regardless of its internal date
    (Megan 2026-06-08)."""
    today = dt.datetime.now(_CENTRAL).date()
    sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return _week_label(sunday)


# Where the Hub drops the uploaded Frontier PDFs (mirrors the Financial Pull
# and First Sale/Last Sale upload reports). Workspace-relative so it works on
# macOS + Windows. Override with --dir for ad-hoc local testing (e.g.
# ~/Downloads). End-goal = pull straight from email (Gmail MCP).
WORKSPACE = Path(__file__).resolve().parent.parent.parent
DEFAULT_UPLOAD_DIR = WORKSPACE / "automations" / "uploaded" / "frontier"
# Two scorecards feed this report:
#   - "Events by Store" → per-store production (Data) + Scoring HC
#   - "Events"          → the ICD-level GIG % / VAS % / ABP % (Megan 5/24)
BY_STORE_GLOB = "Daily Sales - Frontier - Events by Store*.pdf"
EVENTS_GLOB = "Daily Sales - Frontier - Events - SCI*.pdf"
# Quality Scorecard → Approval / Canceled / Pending (Megan 5/24). One page,
# one row per owner, 3 side-by-side windows (Four Weeks Rolling | Current
# Comp Week | Next Comp Week). The sheet uses the FOUR WEEKS ROLLING window,
# mapped by its end-Saturday → sheet Sunday. Arrives on its own email, so a
# scorecard-only upload updates ONLY these 3 rows.
QUALITY_GLOB = "Quality Scorecard - Frontier*.pdf"

OPT_SECTION_LABEL = "OPT - Frontier Retail"

# Accept BOTH full ("June") and 3-letter ("Jun") month names — the Frontier
# PDFs use the abbreviation, and "May" only worked by coincidence (its
# abbreviation == full name). Caught 2026-06-08 when June pages ("Jun 06/13")
# stopped parsing and only "May 30" survived.
_MONTHS = {}
for _i, _m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1):
    _MONTHS[_m] = _i
    _MONTHS[_m[:3]] = _i

_PID_RE = re.compile(r"\b(\d{6})\b")
_PCT_RE = re.compile(r"%$")
_STORE_NUM_RE = re.compile(r"\b(\d{3,5})\b")
_WEEK_ENDING_RE = re.compile(r"Week Ending\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})")
_GENERATED_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}:\d{2})\s+([AP]M)")
# City sits between the store-number separator ('|' often OCRs to 'I') and
# the 2-letter state: "WM 2284 I Naugatuck, CT" -> "Naugatuck".
_CITY_RE = re.compile(r"[|I]\s*([A-Za-z .'\-]+?),\s*[A-Z]{2}\b")


def _week_label(d: dt.date) -> str:
    """Sheet-style week label, e.g. date(2026,5,24) -> '5/24/26'.
    Built by hand (no %-m / %-d — those are macOS-only strftime)."""
    return f"{d.month}/{d.day}/{d.year % 100}"


def _icd_from_tab(title: str) -> str:
    """'Abel Draper (Ben) - Frontier' -> 'Abel Draper' (drop the ' - Frontier'
    suffix and any trailing ' (manager)' parenthetical)."""
    name = title
    if name.endswith(" - Frontier"):
        name = name[: -len(" - Frontier")]
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    return name.strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _store_key(text: str) -> Optional[str]:
    """Reduce a store label (sheet or PDF) to its store number, e.g.
    'Torrington 2144 (46%)' -> '2144', 'WM 2284 I Naugatuck, CT' -> '2284'.
    Parentheticals are dropped first so target-% / date notes don't win."""
    if not text:
        return None
    cleaned = re.sub(r"\([^)]*\)", " ", text)
    m = _STORE_NUM_RE.search(cleaned)
    return m.group(1) if m else None


def _store_city(details: str) -> str:
    m = _CITY_RE.search(details or "")
    return m.group(1).strip() if m else ""


class _StoreRow:
    __slots__ = ("owner", "store_num", "city", "details", "data", "hc")

    def __init__(self, owner, store_num, city, details, data, hc):
        self.owner = owner
        self.store_num = store_num
        self.city = city
        self.details = details
        self.data = data
        self.hc = hc


class _PageWeek:
    """One week-page from a by-store PDF."""
    __slots__ = ("we_sat", "is_current", "generated", "rows")

    def __init__(self, we_sat, is_current, generated, rows):
        self.we_sat = we_sat              # Frontier Saturday week-ending
        self.is_current = is_current      # in-progress "Current Sales Week"
        self.generated = generated        # PDF print timestamp (dedupe key)
        self.rows = rows                  # List[_StoreRow]

    @property
    def sheet_week(self) -> str:
        return _week_label(self.we_sat + dt.timedelta(days=1))


def _parse_data_row(line: str) -> Optional[Tuple[str, _StoreRow]]:
    """Parse one store line -> (owner_name_prefix, _StoreRow) or None.

    Layout: <Owner> <Office> <PID:6d> <Store Details> <7 daily> <Data>
            <%Gig+> <VAS%> <ABP%> <Scoring HC>
    The trailing 12 tokens are the numbers; everything between the PID and
    those 12 tokens is the store-details string."""
    m = _PID_RE.search(line)
    if not m:
        return None
    pre = line[: m.start()].strip()       # "<Owner> <Office>"
    rest = line[m.end():].strip()
    toks = rest.split()
    if len(toks) < 13:                    # 1+ details token + 12 numbers
        return None
    nums = toks[-12:]
    details = " ".join(toks[:-12])
    # Validate the numeric tail: 3 percent tokens at positions 8,9,10.
    if not all(_PCT_RE.search(nums[i]) for i in (8, 9, 10)):
        return None
    try:
        daily = [int(x) for x in nums[0:7]]
        data = int(nums[7])
        hc = int(nums[11])
    except ValueError:
        return None
    if sum(daily) != data:
        # Data should equal the week's daily sum; if not, trust 'Data'
        # but keep the row (Frontier occasionally rounds) — no-op guard.
        pass
    store_num = _store_key(details)
    if store_num is None:
        return None
    return pre, _StoreRow(pre, store_num, _store_city(details), details, data, hc)


def parse_frontier_pdf(path: Path, icd_name: str) -> List[_PageWeek]:
    """Read a by-store PDF -> one _PageWeek per page, keeping only the rows
    whose Owner Name starts with `icd_name`."""
    icd_low = _norm(icd_name)
    out: List[_PageWeek] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = [l for l in text.splitlines() if l.strip()]
            we_sat = generated = None
            is_current = False
            rows: List[_StoreRow] = []
            for line in lines:
                low = line.lower()
                if we_sat is None:
                    wm = _WEEK_ENDING_RE.search(line)
                    if wm:
                        mon = _MONTHS.get(wm.group(1))
                        if mon:
                            we_sat = dt.date(int(wm.group(3)), mon, int(wm.group(2)))
                if "current sales week" in low:
                    is_current = True
                if generated is None:
                    gm = _GENERATED_RE.search(line)
                    if gm:
                        generated = dt.datetime.strptime(
                            f"{gm.group(1)} {gm.group(2)} {gm.group(3)}",
                            "%m/%d/%Y %I:%M:%S %p")
                parsed = _parse_data_row(line)
                if parsed and _norm(parsed[0]).startswith(icd_low):
                    rows.append(parsed[1])
            if we_sat is not None:
                out.append(_PageWeek(we_sat, is_current,
                                     generated or dt.datetime.min, rows))
    return out


def aggregate_weeks(pages: List[_PageWeek],
                    include_current: bool = False) -> Dict[str, Dict]:
    """Collapse page-weeks across all uploaded PDFs into one record per
    sheet week. For each Frontier week-ending the most-recently-generated
    PDF wins (handles duplicate / repeated uploads).

    Returns {sheet_week_label: {
        'stores': {store_num: {'data','hc','city','details'}},
        'active_hc': int, 'total_sales': int, 'store_count': int}}.
    """
    # Pick the freshest page per Frontier Saturday week-ending.
    best: Dict[dt.date, _PageWeek] = {}
    for pg in pages:
        if pg.is_current and not include_current:
            continue
        cur = best.get(pg.we_sat)
        if cur is None or pg.generated > cur.generated:
            best[pg.we_sat] = pg

    out: Dict[str, Dict] = {}
    for pg in best.values():
        stores: Dict[str, Dict] = {}
        for r in pg.rows:
            s = stores.setdefault(
                r.store_num,
                {"data": 0, "hc": 0, "city": r.city, "details": r.details})
            s["data"] += r.data
            s["hc"] += r.hc
        out[pg.sheet_week] = {
            "stores": stores,
            "active_hc": sum(s["hc"] for s in stores.values()),
            "total_sales": sum(s["data"] for s in stores.values()),
            "store_count": sum(1 for s in stores.values() if s["data"] > 0),
        }
    return out


# ----- ICD-level "Events" PDF → GIG % / VAS % / ABP % --------------------
# The quality columns can't be parsed by token position: a blank cell drops
# a token and the stacked header labels don't sit above their columns. So we
# locate the 6 percent columns geometrically — they sit on a fixed evenly
# spaced grid — and read columns 0 (% Gig+), 4 (VAS %), 5 (ABP %).

_DATA_PCT_RE = re.compile(r"^\d+(?:\.\d+)?%$")


def _pct_columns(words: List[dict]) -> Optional[List[float]]:
    """6 evenly spaced percent-column x-centers, derived from the leftmost
    (% Gig+) and rightmost (ABP %) percent words on the page."""
    centers = [(w["x0"] + w["x1"]) / 2 for w in words
               if _DATA_PCT_RE.match(w["text"])]
    if len(centers) < 2:
        return None
    lo, hi = min(centers), max(centers)
    if hi - lo < 50:                      # all in one column → can't map
        return None
    return [lo + i * (hi - lo) / 5 for i in range(6)]


def _group_lines(words: List[dict], tol: float = 3.0) -> List[List[dict]]:
    lines: List[List[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def parse_frontier_events_pdf(path: Path, icd_name: str
                              ) -> List[Tuple[dt.date, bool, dt.datetime, Dict[str, str]]]:
    """Read the ICD-level 'Events' PDF -> per page (we_sat, is_current,
    generated, {gig,vas,abp}) for the ICD's row. Quality values are the
    raw '##.#%' strings; a column missing on the page is omitted."""
    icd_low = _norm(icd_name)
    out = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            text = page.extract_text() or ""
            we_sat = generated = None
            is_current = False
            for line in text.splitlines():
                low = line.lower()
                if we_sat is None:
                    wm = _WEEK_ENDING_RE.search(line)
                    if wm and _MONTHS.get(wm.group(1)):
                        we_sat = dt.date(int(wm.group(3)),
                                         _MONTHS[wm.group(1)], int(wm.group(2)))
                if "current sales week" in low:
                    is_current = True
                if generated is None:
                    gm = _GENERATED_RE.search(line)
                    if gm:
                        generated = dt.datetime.strptime(
                            f"{gm.group(1)} {gm.group(2)} {gm.group(3)}",
                            "%m/%d/%Y %I:%M:%S %p")
            cols = _pct_columns(words)
            if we_sat is None or cols is None:
                continue
            qual: Dict[str, str] = {}
            for line in _group_lines(words):
                ordered = sorted(line, key=lambda w: w["x0"])
                row_text = _norm(" ".join(w["text"] for w in ordered))
                if not row_text.startswith(icd_low):
                    continue
                pcts = [w for w in line if _DATA_PCT_RE.match(w["text"])]
                if not pcts:
                    break
                slot: Dict[int, str] = {}
                for w in pcts:
                    c = (w["x0"] + w["x1"]) / 2
                    idx = min(range(6), key=lambda k: abs(cols[k] - c))
                    slot[idx] = w["text"]
                if 0 in slot:
                    qual["gig"] = slot[0]
                if 4 in slot:
                    qual["vas"] = slot[4]
                if 5 in slot:
                    qual["abp"] = slot[5]
                break
            if qual:
                out.append((we_sat, is_current,
                            generated or dt.datetime.min, qual))
    return out


def aggregate_quality(pages: List[Tuple[dt.date, bool, dt.datetime, Dict[str, str]]],
                      include_current: bool = False) -> Dict[str, Dict[str, str]]:
    """Collapse 'Events' quality pages to {sheet_week: {gig,vas,abp}},
    most-recently-generated PDF winning per Frontier week-ending."""
    best: Dict[dt.date, Tuple[dt.datetime, Dict[str, str]]] = {}
    for we_sat, is_current, generated, qual in pages:
        if is_current and not include_current:
            continue
        cur = best.get(we_sat)
        if cur is None or generated > cur[0]:
            best[we_sat] = (generated, qual)
    return {_week_label(we_sat + dt.timedelta(days=1)): qual
            for we_sat, (_g, qual) in best.items()}


# ----- "Quality Scorecard" PDF → Approval / Canceled / Pending -----------
# Single page; per-owner row; 9 percent columns (3 windows × appr/canc/pend).
# We read the leftmost window (Four Weeks Rolling = columns 0,1,2).
#
# Column: the Quality Scorecard arrives ~2 weeks behind reality (its internal
# rolling window ends well before the file is received). Megan's rule
# (2026-06-08): the latest scorecard ALWAYS fills the CURRENT RUN WEEK's column,
# regardless of the PDF's internal date — aggregate_scorecard maps it to
# _run_week_label() (the most-recent completed WE Sunday). This replaces the old
# fixed "rolling we_sat + 14 days" roll, which broke whenever the lag wasn't
# exactly 2 weeks.

_RANGE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{2})\s+to\s+(\d{1,2}/\d{1,2}/\d{2})")


def parse_frontier_quality_pdf(path: Path, icd_name: str
                               ) -> Optional[Tuple[dt.date, dt.datetime, Dict[str, str]]]:
    """Read the Quality Scorecard -> (rolling_we_sat, file_mtime,
    {approval,canceled,pending}) for the ICD, from the Four Weeks Rolling
    window. Returns None if the ICD isn't on the page."""
    icd_low = _norm(icd_name)
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
    with pdfplumber.open(path) as pdf:
        pg = pdf.pages[0]
        words = pg.extract_words()
        text = pg.extract_text() or ""
        # Section date ranges (in page order: rolling, current, next). The
        # rolling window is the widest span; use its end Saturday.
        ranges = []
        for s, e in _RANGE_RE.findall(text):
            try:
                ranges.append((dt.datetime.strptime(s, "%m/%d/%y").date(),
                               dt.datetime.strptime(e, "%m/%d/%y").date()))
            except ValueError:
                continue
        if not ranges:
            return None
        rolling = max(ranges, key=lambda r: (r[1] - r[0]).days)
        we_sat = rolling[1]
        cols = _pct_columns_n(words, 9)
        if cols is None:
            return None
        for line in _group_lines(words):
            ordered = sorted(line, key=lambda w: w["x0"])
            if not _norm(" ".join(w["text"] for w in ordered)).startswith(icd_low):
                continue
            slot: Dict[int, str] = {}
            for w in line:
                if not _DATA_PCT_RE.match(w["text"]):
                    continue
                c = (w["x0"] + w["x1"]) / 2
                idx = min(range(9), key=lambda k: abs(cols[k] - c))
                slot[idx] = w["text"]
            qual = {}
            if 0 in slot:
                qual["approval"] = slot[0]
            if 1 in slot:
                qual["canceled"] = slot[1]
            if 2 in slot:
                qual["pending"] = slot[2]
            if qual:
                return we_sat, mtime, qual
            break
    return None


def _pct_columns_n(words: List[dict], n: int) -> Optional[List[float]]:
    """Cluster percent-word x-centers into `n` columns (gap-based)."""
    centers = sorted((w["x0"] + w["x1"]) / 2 for w in words
                     if _DATA_PCT_RE.match(w["text"]))
    if len(centers) < n:
        return None
    groups = [[centers[0]]]
    for x in centers[1:]:
        if x - groups[-1][-1] <= 10:
            groups[-1].append(x)
        else:
            groups.append([x])
    cols = [sum(g) / len(g) for g in groups]
    return cols if len(cols) == n else None


def aggregate_scorecard(entries: List[Tuple[dt.date, dt.datetime, Dict[str, str]]],
                        target_week: str) -> Dict[str, Dict[str, str]]:
    """Collapse scorecard files to {target_week: {approval,canceled,pending}}.
    The scorecard arrives ~2 weeks late, but Megan's rule (2026-06-08) is it
    ALWAYS fills the current run week's column regardless of its internal date
    — so the most-recently-modified file's values map to `target_week`, NOT to a
    date derived from the PDF (the old +14-day roll)."""
    if not entries:
        return {}
    _we, _mtime, qual = max(entries, key=lambda e: e[1])
    return {target_week: qual}


def _opt_section_start(grid: List[List[str]]) -> int:
    for ri, row in enumerate(grid):
        if _norm(row[1] if len(row) > 1 else "") == _norm(OPT_SECTION_LABEL):
            return ri
    return 0


def fill_frontier_tab(ws: gspread.Worksheet, icd_name: str,
                      weeks: Dict[str, Dict], dry_run: bool = False,
                      logfn=print,
                      quality: Optional[Dict[str, Dict[str, str]]] = None,
                      scorecard: Optional[Dict[str, Dict[str, str]]] = None
                      ) -> List[str]:
    """Fill per-store production, Total Sales, Total Store Count, AVG Sales
    per Store (formula) and Active Headcount on Scorecard for every target
    week present in `weeks` that has a column on the sheet. When `quality`
    (from the 'Events' PDF) is supplied also fill GIG % / VAS % / ABP %; when
    `scorecard` (from the 'Quality Scorecard' PDF) is supplied also fill
    Approval / Canceled / Pending. Each source is independent — a single
    PDF upload only touches its own rows (partial-upload safe)."""
    quality = quality or {}
    scorecard = scorecard or {}
    log: List[str] = []
    grid = rfill._retry(ws.get_all_values)
    if not grid:
        return [f"[skip-fr] {ws.title}: empty tab"]
    opt_start = _opt_section_start(grid)

    # Existing store rows (within the OPT section only).
    def store_rows(g):
        rows = []
        for ri in range(opt_start, len(g)):
            label = (g[ri][1] if len(g[ri]) > 1 else "").strip()
            key = _store_key(label)
            if key is not None:
                rows.append((ri, key, label))
        return rows

    existing = store_rows(grid)
    existing_keys = {k for _, k, _ in existing}

    # New stores (any target week, production > 0) not yet on the sheet.
    new_keys: Dict[str, Dict] = {}
    for wk in weeks.values():
        for key, s in wk["stores"].items():
            if s["data"] > 0 and key not in existing_keys and key not in new_keys:
                new_keys[key] = s
    new_stores = sorted(new_keys.items(), key=lambda kv: kv[0])

    if new_stores and existing and not dry_run:
        insert_at_0 = max(r for r, _, _ in existing) + 1
        rfill._retry(ws.spreadsheet.batch_update, {"requests": [{
            "insertDimension": {
                "range": {"sheetId": ws.id, "dimension": "ROWS",
                          "startIndex": insert_at_0,
                          "endIndex": insert_at_0 + len(new_stores)},
                "inheritFromBefore": True,
            }}]})
        grid = rfill._retry(ws.get_all_values)
        label_updates = []
        for offset, (key, s) in enumerate(new_stores):
            city = s.get("city") or ""
            disp = f"{city} {key}".strip()
            label_updates.append({
                "range": gspread.utils.rowcol_to_a1(insert_at_0 + offset + 1, 2),
                "values": [[disp]]})
        rfill._retry(ws.batch_update, label_updates,
                     value_input_option="USER_ENTERED")
        grid = rfill._retry(ws.get_all_values)
        existing = store_rows(grid)
    elif new_stores and dry_run:
        for key, s in new_stores:
            city = s.get("city") or ""
            log.append(f"  [new-store] would add row {city} {key!r}")

    def _row_any(*labels):
        for lab in labels:
            r = _find_row_by_label(grid, lab)
            if r is not None:
                return r
        return None

    ts_row = _find_row_by_label(grid, "Total Sales Frontier")
    tsc_row = _find_row_by_label(grid, "Total Store Count Frontier")
    aps_row = _find_row_by_label(grid, "AVG Sales per Store")
    # The Frontier tabs label the headcount row "Active Headcount on Tableau"
    # (shared Org-sheet convention), even though the value is the Scoring HC
    # parsed from the Quality Scorecard PDF — not Tableau. Older tabs may use
    # "Active Headcount on Scorecard"; try both (mirrors opt_box._row_any).
    hc_row = _row_any("Active Headcount on Scorecard", "Active Headcount on Tableau")
    qual_rows = {"gig": _find_row_by_label(grid, "GIG %"),
                 "vas": _find_row_by_label(grid, "VAS %"),
                 "abp": _find_row_by_label(grid, "ABP %")}
    sc_rows = {"approval": _find_row_by_label(grid, "Approval"),
               "canceled": _find_row_by_label(grid, "Canceled"),
               "pending": _find_row_by_label(grid, "Pending")}

    updates: List[Dict] = []
    all_weeks = sorted(set(weeks) | set(quality) | set(scorecard))
    for week_label in all_weeks:
        week_col = _find_week_col(grid, week_label)
        if week_col is None:
            log.append(f"  [no-col] sheet has no column for week {week_label}")
            continue
        col_a1 = gspread.utils.rowcol_to_a1(1, week_col + 1).rstrip("1")
        log.append(f"  --- week {week_label} (col {col_a1}) ---")

        # --- by-store production + totals (only if that PDF was uploaded) ---
        wk = weeks.get(week_label)
        if wk is not None:
            for ri, key, label in existing:
                val = wk["stores"].get(key, {}).get("data", 0)
                a1 = gspread.utils.rowcol_to_a1(ri + 1, week_col + 1)
                updates.append({"range": a1, "values": [[str(val)]]})
                log.append(f"    {a1} {label!r} <- {val}")
            if ts_row is not None:
                a1 = gspread.utils.rowcol_to_a1(ts_row + 1, week_col + 1)
                updates.append({"range": a1, "values": [[str(wk["total_sales"])]]})
                log.append(f"    {a1} Total Sales Frontier <- {wk['total_sales']}")
            if tsc_row is not None:
                a1 = gspread.utils.rowcol_to_a1(tsc_row + 1, week_col + 1)
                updates.append({"range": a1, "values": [[str(wk["store_count"])]]})
                log.append(f"    {a1} Total Store Count Frontier <- {wk['store_count']}")
            if aps_row is not None and ts_row is not None and tsc_row is not None:
                ts_ref = f"{col_a1}{ts_row + 1}"
                tsc_ref = f"{col_a1}{tsc_row + 1}"
                formula = f"=IFERROR({ts_ref}/{tsc_ref},0)"
                a1 = gspread.utils.rowcol_to_a1(aps_row + 1, week_col + 1)
                updates.append({"range": a1, "values": [[formula]]})
                log.append(f"    {a1} AVG Sales per Store <- {formula}")
            if hc_row is not None:
                a1 = gspread.utils.rowcol_to_a1(hc_row + 1, week_col + 1)
                updates.append({"range": a1, "values": [[str(wk["active_hc"])]]})
                log.append(f"    {a1} Active Headcount <- {wk['active_hc']}")

        # --- GIG / VAS / ABP (Events PDF) ---
        wq = quality.get(week_label, {})
        for key, label in (("gig", "GIG %"), ("vas", "VAS %"), ("abp", "ABP %")):
            row = qual_rows.get(key)
            if row is None or key not in wq:
                continue
            a1 = gspread.utils.rowcol_to_a1(row + 1, week_col + 1)
            updates.append({"range": a1, "values": [[wq[key]]]})
            log.append(f"    {a1} {label} <- {wq[key]}")

        # --- Approval / Canceled / Pending (Quality Scorecard PDF) ---
        sc = scorecard.get(week_label, {})
        for key, label in (("approval", "Approval"), ("canceled", "Canceled"),
                           ("pending", "Pending")):
            row = sc_rows.get(key)
            if row is None or key not in sc:
                continue
            a1 = gspread.utils.rowcol_to_a1(row + 1, week_col + 1)
            updates.append({"range": a1, "values": [[sc[key]]]})
            log.append(f"    {a1} {label} <- {sc[key]}")

    if dry_run:
        return [f"[DRY-RUN fr] {ws.title}: would write {len(updates)} cells"] + log
    if updates:
        rfill._retry(ws.batch_update, updates, value_input_option="USER_ENTERED")
        return [f"[OK fr] {ws.title}: wrote {len(updates)} cells"] + log
    return [f"[skip-fr] {ws.title}: nothing to write"]


def find_uploaded_pdfs(upload_dir: Optional[Path] = None) -> List[Path]:
    d = upload_dir or DEFAULT_UPLOAD_DIR
    return sorted(d.glob(BY_STORE_GLOB))


def find_uploaded_events_pdfs(upload_dir: Optional[Path] = None) -> List[Path]:
    d = upload_dir or DEFAULT_UPLOAD_DIR
    return sorted(d.glob(EVENTS_GLOB))


def find_uploaded_quality_pdfs(upload_dir: Optional[Path] = None) -> List[Path]:
    d = upload_dir or DEFAULT_UPLOAD_DIR
    return sorted(d.glob(QUALITY_GLOB))


def run_frontier_opt(dry_run: bool = False, only_rep: Optional[str] = None,
                     upload_dir: Optional[Path] = None,
                     include_current: bool = False,
                     pdf_paths: Optional[List[Path]] = None,
                     logfn=print) -> dict:
    """Frontier OPT Data Pull — parse whichever of the three Frontier PDFs
    the user uploaded and fill each ' - Frontier' tab. Each PDF type is
    independent: uploading only one (e.g. the Quality Scorecard) updates
    only that PDF's rows and leaves every other cell untouched."""
    errors: List[str] = []
    pdfs = pdf_paths if pdf_paths else find_uploaded_pdfs(upload_dir)
    event_pdfs = find_uploaded_events_pdfs(upload_dir)
    quality_pdfs = find_uploaded_quality_pdfs(upload_dir)
    if not (pdfs or event_pdfs or quality_pdfs):
        logfn("Frontier OPT Data Pull: no Frontier PDF found in upload folder.")
        return {"filled": [], "skipped": [], "errors": ["no PDF uploaded"]}
    logfn(f"Frontier OPT Data Pull: reading {len(pdfs)} by-store + "
          f"{len(event_pdfs)} events + {len(quality_pdfs)} quality PDF(s):")
    for p in pdfs + event_pdfs + quality_pdfs:
        logfn(f"  - {p.name}")

    client = rfill._client()
    sh = rfill.open_by_key(ALPHALETE_ORG_SHEET_ID, client)
    resp = sh.client.request(
        "get", f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
        params={"fields": "sheets(properties(title,hidden))"})
    hidden = {s["properties"]["title"] for s in resp.json().get("sheets", [])
              if s["properties"].get("hidden")}

    filled, skipped = [], []
    for ws in rfill._retry(sh.worksheets):
        title = ws.title
        if not title.endswith(" - Frontier") or title in hidden or title.startswith("x"):
            continue
        icd_name = _icd_from_tab(title)
        if only_rep and only_rep.lower() not in icd_name.lower():
            continue
        try:
            pages: List[_PageWeek] = []
            for p in pdfs:
                pages.extend(parse_frontier_pdf(p, icd_name))
            weeks = _latest_week_only(
                aggregate_weeks(pages, include_current=include_current))
            qpages = []
            for p in event_pdfs:
                qpages.extend(parse_frontier_events_pdf(p, icd_name))
            quality = _latest_week_only(
                aggregate_quality(qpages, include_current=include_current))
            sc_entries = []
            for p in quality_pdfs:
                e = parse_frontier_quality_pdf(p, icd_name)
                if e:
                    sc_entries.append(e)
            scorecard = aggregate_scorecard(sc_entries, _run_week_label())
        except Exception as e:
            msg = f"{title}: {type(e).__name__}: {str(e)[:120]}"
            logfn(f"Frontier OPT Data Pull: ✗ {msg}")
            errors.append(msg)
            skipped.append(title)
            continue

        wk_summary = ", ".join(
            f"{w}: {weeks[w]['total_sales']} sales/{weeks[w]['store_count']} "
            f"stores/{weeks[w]['active_hc']} HC" for w in sorted(weeks))
        logfn(f"Frontier OPT Data Pull: {icd_name} → production [{wk_summary or 'none'}]")
        if quality:
            logfn(f"Frontier OPT Data Pull: {icd_name} GIG/VAS/ABP → " + ", ".join(
                f"{w}: {quality[w]}" for w in sorted(quality)))
        if scorecard:
            logfn(f"Frontier OPT Data Pull: {icd_name} Approval/Canc/Pend → " + ", ".join(
                f"{w}: {scorecard[w]}" for w in sorted(scorecard)))
        if not (weeks or quality or scorecard):
            skipped.append(title)
            continue
        for ln in fill_frontier_tab(ws, icd_name, weeks, dry_run, logfn,
                                    quality=quality, scorecard=scorecard):
            logfn(f"Frontier OPT Data Pull: {ln}")
            if ln.startswith(("[OK", "[DRY-RUN")):
                filled.append(title)

    return {"filled": filled, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="Only this ICD (substring match).")
    ap.add_argument("--dir", help=f"Folder of uploaded Frontier PDFs "
                    f"(default: {DEFAULT_UPLOAD_DIR}).")
    ap.add_argument("--include-current", action="store_true",
                    help="Also fill the in-progress current week.")
    args = ap.parse_args()
    result = run_frontier_opt(
        dry_run=args.dry_run, only_rep=args.only,
        upload_dir=Path(args.dir).expanduser() if args.dir else None,
        include_current=args.include_current)
    print(f"\nFilled: {len(result['filled'])}; Skipped: {len(result['skipped'])}; "
          f"Errors: {len(result['errors'])}")
    for e in result["errors"]:
        print(f"  ✗ {e}")
