"""Append each day's knocks rows to the AUTOMATION MASTER 'Knocks Daily' tab.

The knocks run is stateless by design — it renders two PNGs from rows held in
memory, posts them to Slack, and writes no sheet. That is fine for a daily
post and impossible for a site: yesterday's numbers exist only as an image in
a channel, so there is nothing to show day over day.

This writes the rows the run ALREADY HAS. No second pull, no extra ownerville
session, nothing added to the load on the session the 4am batch shares.

Two rules it must not break:

  * IDEMPOTENT. Reruns of a metric re-post with no dedup anywhere else in this
    codebase, so a rerun would otherwise double every rep's day. A day already
    logged for an office is skipped.
  * NEVER FATAL. A logging hiccup must not take down a post that would
    otherwise have gone out. Every failure returns 0 and says why.
"""
from __future__ import annotations

import datetime as dt

SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"   # AUTOMATION MASTER
TAB = "Knocks Daily"


def _columns():
    from automations.total_knocks.pull import SHEET_COLUMNS
    return ["Date", "Office"] + list(SHEET_COLUMNS)


def already_logged(day: dt.date, office: str, sheet_id: str = SHEET_ID) -> bool:
    """Has this office's day already been written?"""
    from automations.recruiting_report.fill import open_by_key, _retry
    sh = open_by_key(sheet_id)
    ws = sh.worksheet(TAB)
    rows = _retry(ws.get_all_values)
    key = (day.isoformat(), (office or "").strip().lower())
    for r in rows[1:]:
        if len(r) > 1 and (r[0] or "").strip()[:10] == key[0] \
                and (r[1] or "").strip().lower() == key[1]:
            return True
    return False


def append_day(day: dt.date, office: str, records: list,
               sheet_id: str = SHEET_ID, verbose: bool = True) -> int:
    """Append one office's day. Returns the number of rows written (0 = none).

    Rows are written in the pull's own column order, so this is a passthrough
    and nothing has to be re-mapped when a column is added upstream."""
    if not records:
        return 0
    try:
        from automations.recruiting_report.fill import open_by_key, _retry
        cols = _columns()
        sh = open_by_key(sheet_id)
        ws = sh.worksheet(TAB)
        existing = _retry(ws.get_all_values)

        key_day, key_office = day.isoformat(), (office or "").strip()
        for r in existing[1:]:
            if len(r) > 1 and (r[0] or "").strip()[:10] == key_day \
                    and (r[1] or "").strip().lower() == key_office.lower():
                if verbose:
                    print(f"   knocks log: {key_office} {key_day} already "
                          f"logged - skipped")
                return 0

        out = []
        for rec in records:
            out.append([key_day, key_office] + [_cell(rec, c) for c in cols[2:]])
        _retry(ws.append_rows, out, value_input_option="USER_ENTERED")
        if verbose:
            print(f"   knocks log: +{len(out)} rows for {key_office} {key_day}")
        return len(out)
    except Exception as e:                      # never fail the post
        if verbose:
            print(f"   knocks log: SKIPPED ({type(e).__name__}: {e})")
        return 0


def _cell(rec: dict, col: str) -> str:
    """One cell's text, with a real zero kept AS a zero.

    THIS USED TO BE `str(rec.get(col, "") or "")`, and the `or ""` turned
    every falsy value into a blank -- so an integer 0 was written as an empty
    cell. Across 2540 logged rows the string "0" appeared exactly nowhere,
    while blanks were everywhere: Do Not Knock 2027, Sale 1370, Come Back
    1133, Gaps 147, even Total Knocks 10.

    WHY THAT MATTERS: the pull's own convention is that COUNT_COLUMNS are ints
    where blank means 0, while the Time Tracker pair (Gaps, Total Gaps) stay
    BLANK when a rep has no tracker row at all -- deliberately, per Eve, since
    "did not clock in" and "stood still for zero minutes" are different facts
    the board draws differently. Blanking every zero collapsed exactly that
    distinction: a rep with a tracker row showing 0 gaps became
    indistinguishable from one who never clocked in.

    It also produced a false mismatch when relayed and scraped rows were
    diffed on 2026-09-17 -- kash's Ameer Almutairy read Gaps=0 from the relay
    and Gaps=blank from this log, purely because of this.

    ABSENT STILL MEANS BLANK. Only the value that is genuinely not in the
    record produces an empty cell now.

    ROWS WRITTEN BEFORE 2026-09-17 CANNOT BE REPAIRED -- the information is
    gone, and a day already logged is skipped rather than rewritten. Readers
    here already coerce a blank to 0 (`activity_from._n`), so both
    conventions read alike; anything new that cares about the difference must
    only trust rows from this date on.
    """
    value = rec.get(col)
    return "" if value is None else str(value)

def roster_for(office: str, start=None, end=None,
               sheet_id: str = SHEET_ID) -> set:
    """Every rep who KNOCKED for this office in the window.

    THIS IS THE ROSTER THE BOARD SHOULD USE (Megan 2026-09-13). A sales feed
    only knows who sold, so a rep who worked all week and rolled a zero is
    simply absent from it — and the zeros are what an owner opens a board to
    find. Knocking is the proof somebody was out there.

    Matched on the office's OWNER NAME, which is how the knocks run writes it
    ('Cyrus Wade'), with the ICD alias table as the fallback: this tab also
    holds spellings like 'Akashdeep Rai' and 'Muhammad UI Haque' that no other
    report uses.

    Never raises — an office with no knocks logged returns an empty set, and
    the board falls back to whoever sold."""
    try:
        from automations.recruiting_report.fill import open_by_key, _retry

        wanted = {(office or "").strip().lower()}
        try:
            from automations.focus_office_att import aliases as _al
            wanted |= {n.strip().lower() for n in
                       _al.get_search_candidates(office, _al.load_aliases())
                       if n}
        except Exception:  # noqa: BLE001 — aliases are a nicety here
            pass

        grid = _retry(open_by_key(sheet_id).worksheet(TAB).get_all_values)
        if not grid:
            return set()
        header = [str(h).strip() for h in grid[0]]
        i_date, i_office, i_rep = (header.index("Date"), header.index("Office"),
                                   header.index("Rep"))
        out = set()
        for row in grid[1:]:
            if len(row) <= i_rep:
                continue
            name = str(row[i_office]).strip().lower()
            # An office cell like 'Next Horizon Group, Inc. Nii Tagoe' carries
            # the company AND the owner, so a substring match is what works.
            if not any(w and (w == name or w in name) for w in wanted):
                continue
            if start or end:
                try:
                    d = dt.date.fromisoformat(str(row[i_date]).strip()[:10])
                except ValueError:
                    continue
                if (start and d < start) or (end and d > end):
                    continue
            rep = str(row[i_rep]).strip()
            if rep:
                out.add(rep)
        return out
    except Exception:  # noqa: BLE001 — a board must not die over a roster
        return set()


def _wanted(office: str) -> set:
    """Every spelling this office goes by on the tab, lower case.

    Shared by every reader here: this tab spells owners its own way
    ('Akashdeep Rai', 'Muhammad UI Haque'), and an office cell can carry the
    company AND the owner ('Next Horizon Group, Inc. Nii Tagoe'), which is why
    callers substring-match rather than compare."""
    out = {(office or "").strip().lower()}
    try:
        from automations.focus_office_att import aliases as _al
        out |= {n.strip().lower() for n in
                _al.get_search_candidates(office, _al.load_aliases()) if n}
    except Exception:  # noqa: BLE001 — aliases are a nicety here
        pass
    return {w for w in out if w}


# Columns that are not a per-day measure: the row's identity, and the two
# clock times, which are read as a first/last rather than added up.
_IDENTITY = ("Date", "Office", "ID", "Rep")
_TIMES = ("First Knock", "Last Knock")


def _clock(text: str) -> tuple:
    """'8:20 PM' as something that sorts. COMPARING THE STRINGS IS WRONG —
    '8:20 PM' sorts before '12:53 PM' because '8' > '1', so the earliest knock
    of a two-row day came out as the latest. Anything unparseable sorts last,
    which keeps a stray value from winning 'first'."""
    raw = (text or "").strip().upper()
    for fmt in ("%I:%M %p", "%I:%M:%S %p", "%H:%M", "%H:%M:%S"):
        try:
            t = dt.datetime.strptime(raw, fmt).time()
            return (t.hour, t.minute, t.second)
        except ValueError:
            continue
    return (99, 99, 99)


def detail_from(grid: list, office: str, start=None, end=None) -> dict:
    """{rep lowered: {date: {column: value}}} — EVERY column the tab carries.

    activity_from keeps Total Knocks and Total Talk to, because that is all
    the sales board draws. The knocks page is about the rest of the row: the
    dispositions each knock turned into, and the time-tracker gaps. Rather
    than name those columns here they are taken FROM THE HEADER, so a new
    disposition on the tab shows up on the page without an edit
    (`feedback_no_hardcoded_columns`).

    BLANK IS KEPT BLANK. The tab's own convention is that a count is an int
    where blank means 0, but the Time Tracker pair (Gaps, Total Gaps) stays
    blank when a rep has no tracker row at all — 'did not clock in' and 'stood
    still for zero minutes' are different facts, and the page draws them
    differently. A column that is blank in every row for a rep's day stays
    blank; one that has a number anywhere is summed.

    The clock columns are not summed: First Knock is the earliest and Last
    Knock the latest, which is what they mean across two rows of one day.

    Never raises — the knocks page says so itself rather than dying."""
    try:
        if not grid:
            return {}
        header = [str(h).strip() for h in grid[0]]
        need = ("Date", "Office", "Rep")
        if any(n not in header for n in need):
            return {}
        idx = {n: header.index(n) for n in header}
        measures = [h for h in header
                    if h and h not in _IDENTITY and h not in _TIMES]
        wanted = _wanted(office)

        def _n(v):
            try:
                return int(float(str(v).replace(",", "").strip() or 0))
            except ValueError:
                return 0

        out: dict = {}
        for row in grid[1:]:
            if len(row) <= max(idx[n] for n in need):
                continue
            name = str(row[idx["Office"]]).strip().lower()
            if not any(w == name or w in name for w in wanted):
                continue
            try:
                d = dt.date.fromisoformat(str(row[idx["Date"]]).strip()[:10])
            except ValueError:
                continue
            if (start and d < start) or (end and d > end):
                continue
            rep = str(row[idx["Rep"]]).strip()
            if not rep:
                continue
            cell = out.setdefault(rep.lower(), {}).setdefault(d, {})
            for m in measures:
                i = idx[m]
                raw = str(row[i]).strip() if len(row) > i else ""
                if raw == "":
                    cell.setdefault(m, "")     # blank until a number appears
                    continue
                cell[m] = _n(cell.get(m) or 0) + _n(raw)
            for t in _TIMES:
                if t not in idx or len(row) <= idx[t]:
                    continue
                raw = str(row[idx[t]]).strip()
                if not raw:
                    continue
                have = cell.get(t)
                if not have:
                    cell[t] = raw
                elif (t == "First Knock") == (_clock(raw) < _clock(have)):
                    cell[t] = raw
        return out
    except Exception:   # noqa: BLE001 — the page reports an empty read itself
        return {}


def detail_for(office: str, start=None, end=None,
               sheet_id: str = SHEET_ID) -> dict:
    """detail_from over a freshly read tab. Prefer detail_from on a page,
    which reads the tab once for every office it shows."""
    from automations.recruiting_report.fill import open_by_key, _retry
    try:
        grid = _retry(open_by_key(sheet_id).worksheet(TAB).get_all_values)
    except Exception:   # noqa: BLE001
        return {}
    return detail_from(grid, office, start, end)


def activity_for(office: str, start=None, end=None,
                 sheet_id: str = SHEET_ID) -> dict:
    """{rep lowered: {date: {"TK": knocks, "TT": talk-tos}}} for one office.

    Raf's board carries TK and Total Talk-To's beside the sales, per day AND
    for the week, and every ratio on it (knocks per day, talk-tos per knock,
    talk-tos per app) is derived from those two numbers — so this is what lets
    the site show his columns rather than a subset (Megan 2026-09-13).

    Same office matching as roster_for, for the same reason: this tab spells
    owners its own way. Never raises — no knocks logged is an empty dict, and
    the board leaves those columns blank rather than printing zeros nobody
    measured."""
    from automations.recruiting_report.fill import open_by_key, _retry
    try:
        grid = _retry(open_by_key(sheet_id).worksheet(TAB).get_all_values)
    except Exception:   # noqa: BLE001
        return {}
    return activity_from(grid, office, start, end)


def activity_from(grid: list, office: str, start=None, end=None) -> dict:
    """activity_for, but over a grid somebody ALREADY read.

    The page shows several offices in a session and the tab is one shared
    sheet, so re-reading it per office was most of a render's cost. The read
    moves to the caller; the matching stays here."""
    try:
        wanted = {(office or "").strip().lower()}
        try:
            from automations.focus_office_att import aliases as _al
            wanted |= {n.strip().lower() for n in
                       _al.get_search_candidates(office, _al.load_aliases())
                       if n}
        except Exception:  # noqa: BLE001 — aliases are a nicety here
            pass

        if not grid:
            return {}
        header = [str(h).strip() for h in grid[0]]
        idx = {n: header.index(n) for n in
               ("Date", "Office", "Rep", "Total Knocks", "Total Talk to")
               if n in header}
        if len(idx) < 5:
            return {}

        def _n(v):
            try:
                return int(float(str(v).replace(",", "").strip() or 0))
            except ValueError:
                return 0

        out: dict = {}
        for row in grid[1:]:
            if len(row) <= max(idx.values()):
                continue
            name = str(row[idx["Office"]]).strip().lower()
            if not any(w and (w == name or w in name) for w in wanted):
                continue
            try:
                d = dt.date.fromisoformat(str(row[idx["Date"]]).strip()[:10])
            except ValueError:
                continue
            if (start and d < start) or (end and d > end):
                continue
            rep = str(row[idx["Rep"]]).strip()
            if not rep:
                continue
            cell = out.setdefault(rep.lower(), {}).setdefault(
                d, {"TK": 0, "TT": 0})
            cell["TK"] += _n(row[idx["Total Knocks"]])
            cell["TT"] += _n(row[idx["Total Talk to"]])
        return out
    except Exception:   # noqa: BLE001 — knocks are a decoration on the board
        return {}
