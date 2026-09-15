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
            out.append([key_day, key_office]
                       + [str(rec.get(c, "") or "") for c in cols[2:]])
        _retry(ws.append_rows, out, value_input_option="USER_ENTERED")
        if verbose:
            print(f"   knocks log: +{len(out)} rows for {key_office} {key_day}")
        return len(out)
    except Exception as e:                      # never fail the post
        if verbose:
            print(f"   knocks log: SKIPPED ({type(e).__name__}: {e})")
        return 0


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
