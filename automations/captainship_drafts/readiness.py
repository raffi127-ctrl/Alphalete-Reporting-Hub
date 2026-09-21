"""Hold the build until the tabs it reads carry TODAY's numbers.

WHY (Eve 2026-09-21). The build runs on Lucy 3 and the eight fills it reads
(churn, cancel, activation, ABP/6-days, Raf's metrics) run on Lucy 1, so the
orchestrator cannot order them — day state is per machine. What stood in for
that ordering was a clock, cadence.not_before (06:15, raised to 06:45 on
2026-09-08). A clock is a floor, not a guarantee: on 2026-09-21 the drafts went
up at 07:15 with activation, ABP and 6+ days still showing 9/20 as the newest
day on every fiber draft, while some fills had landed in time (Wayne's cancel
already had 9/21). Nothing failed, so nothing said a word; Eve found it reading
the reports — the same miss as 2026-09-03 and 2026-09-08.

The tabs are shared Google Sheets, though, and Lucy 3 CAN see those. So instead
of guessing a later clock, the build looks at the data itself: every date
header on every tab this run reads must be today AND have numbers under it
(the fills insert the dated column before they write it, so a header alone
proves nothing — see [[project_captainship-drafts-built-before-metrics-land]]).

  • All fresh → returns at once. A normal morning costs one read pass.
  • Something stale → re-checks every POLL_SECONDS until DEADLINE (Central).
  • Still stale at DEADLINE → builds anyway (a late fill must never strand
    twelve reports) and raises a 🚨 in #claudecorrections naming the tabs, so
    it is heard before anyone approves the link.

While this waits the build process is alive, so the 07:15 review-post slot
skips (its pgrep guard) and the link goes up on the next slot after the build
— later, but with the right numbers.

Cheap on purpose: the worksheets are opened once, then each pass is ONE
values_batch_get per workbook (5 of them), not one read per tab — the Sheets
read quota is per minute and a 429 here would also block the build behind it.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Callable, Dict, List, Tuple

# Latest time (machine-local = Central on Lucy 3) the build keeps waiting.
# 07:45 so a fill that is 30-60 min late still makes the 08:15 / 09:15 review
# slots with the right numbers; past it, a draft with a stale box plus an alert
# beats no draft.
DEADLINE = dt.time(7, 45)
POLL_SECONDS = 300

REPORT_ID = "captainship-drafts"

# 'Mon 9/21/26' — the label every fill writes in the header row's B cell.
_DATE_RE = re.compile(r"^\s*[A-Za-z]{3}\s+(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$")
# A data cell carries a digit ('23.4%', '0.00%', '12'); the '%' / 'units'
# labels the fill stamps under 'Rep' do not.
_HAS_DIGIT = re.compile(r"\d")


def _parse_label(s: str):
    m = _DATE_RE.match(s or "")
    if not m:
        return None
    mo, d, y = (int(g) for g in m.groups())
    y = y + 2000 if y < 100 else y
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def stale_blocks(col_ab: List[List[str]], today: dt.date) -> List[str]:
    """Why a tab is NOT ready for `today`, one string per problem; [] = ready.

    `col_ab` is the tab's A:B grid. Every row whose B cell is a date label is
    a box/section header; B is always the NEWEST day on these tabs. A header
    must be today, and the rows under it (up to the next header) must hold at
    least one number in B. A tab with no date header at all says nothing
    about today and is not held on."""
    heads = []
    for i, row in enumerate(col_ab):
        b = row[1] if len(row) > 1 else ""
        d = _parse_label(b)
        if d is not None:
            heads.append((i, d, (row[0] if row else "").strip()))
    problems = []
    for n, (i, d, label) in enumerate(heads):
        name = " ".join(label.split())[:40] or f"row {i + 1}"
        if d != today:
            problems.append(f"{name}: newest day {d.month}/{d.day}")
            continue
        end = heads[n + 1][0] if n + 1 < len(heads) else len(col_ab)
        if not any(_HAS_DIGIT.search(r[1] if len(r) > 1 else "")
                   for r in col_ab[i + 1:end]):
            problems.append(f"{name}: {d.month}/{d.day} column is empty")
    return problems


def _sources(captains) -> List[Callable]:
    """Every open_ws the build will call for these captains, one per tab."""
    seen, out = set(), []
    for c in captains:
        for src in list(c.boxes or []) + list(c.churn or []):
            # BoxSource.cache_key is per TAB within a captain ('cancel' for both
            # cancel boxes); a ChurnSource is one tab on its own.
            key = (c.key, getattr(src, "cache_key", None) or src.label)
            if key in seen:
                continue
            seen.add(key)
            out.append(src.open_ws)
    return out


def _open_all(captains, logfn) -> Dict[str, Tuple[object, List[str]]]:
    """{spreadsheet_id: (spreadsheet, [tab titles])}, opened once."""
    books: Dict[str, Tuple[object, List[str]]] = {}
    for open_ws in _sources(captains):
        try:
            ws = open_ws()
        except Exception as e:  # noqa: BLE001 — the build reports its own
            logfn(f"  ⚠ readiness: could not open a source tab "
                  f"({type(e).__name__}: {e}) — not waiting on it")
            continue
        sh = ws.spreadsheet
        titles = books.setdefault(sh.id, (sh, []))[1]
        if ws.title not in titles:
            titles.append(ws.title)
    return books


def check(books, today: dt.date, logfn=print) -> Dict[str, List[str]]:
    """{'<tab>': [problems]} for every tab not ready yet ({} = all fresh)."""
    out: Dict[str, List[str]] = {}
    for sh, titles in books.values():
        ranges = [f"'{t}'!A1:B400" for t in titles]
        try:
            res = sh.values_batch_get(ranges)
        except Exception as e:  # noqa: BLE001
            logfn(f"  ⚠ readiness: read failed on {sh.title!r} "
                  f"({type(e).__name__}: {e}) — treating it as not ready")
            for t in titles:
                out[t] = ["could not be read"]
            continue
        for t, vr in zip(titles, res.get("valueRanges", [])):
            probs = stale_blocks(vr.get("values", []), today)
            if probs:
                out[t] = probs
    return out


def wait_for_fills(captains, today: dt.date, *, logfn=print,
                   deadline: dt.time = DEADLINE, poll: int = POLL_SECONDS,
                   now: Callable[[], dt.datetime] = dt.datetime.now,
                   sleep: Callable[[float], None] = time.sleep,
                   alert: bool = True) -> Dict[str, List[str]]:
    """Block until every tab these captains read is filled for `today`, or
    until `deadline`. Returns what was still stale ({} = everything fresh).
    Never raises: a readiness problem must not cost the build."""
    try:
        books = _open_all(captains, logfn)
        if not books:
            return {}
        n_tabs = sum(len(t) for _, t in books.values())
        stale = check(books, today, logfn)
        while stale:
            left = dt.datetime.combine(today, deadline) - now()
            if left.total_seconds() <= 0:
                break
            logfn(f"  ⏳ {len(stale)}/{n_tabs} source tab(s) not filled for "
                  f"{today:%m/%d} yet ({', '.join(sorted(stale)[:4])}"
                  f"{'…' if len(stale) > 4 else ''}) — re-checking in "
                  f"{poll // 60} min (building anyway at {deadline:%H:%M})")
            sleep(min(poll, max(left.total_seconds(), 1)))
            stale = check(books, today, logfn)
    except Exception as e:  # noqa: BLE001
        logfn(f"  ⚠ readiness check skipped ({type(e).__name__}: {e})")
        return {}

    if not stale:
        logfn(f"  ✓ all {n_tabs} source tab(s) carry {today:%m/%d} — building")
        return {}

    items = [f"{t} — {'; '.join(p)}" for t, p in sorted(stale.items())]
    logfn(f"  ⚠ still not filled for {today:%m/%d} at {deadline:%H:%M}, "
          f"building anyway:")
    for it in items:
        logfn(f"      {it}")
    if alert:
        try:
            from automations.shared import section_drop_alert
            section_drop_alert.alert(
                report_id=REPORT_ID, failed=items, kind="tab", day=today,
                note=(f"The captainship drafts were built at {deadline:%H:%M} "
                      f"with these tabs still missing {today:%m/%d}; those "
                      f"boxes show the previous day. Once the fill lands, "
                      f"rebuild the affected blocks on Lucy 3 "
                      f"(`captainship_drafts --block <key> --dry-run`) — the "
                      f"rebuild re-seals the review PDFs under the same links."))
        except Exception as e:  # noqa: BLE001
            logfn(f"  ⚠ stale-tab alert not sent ({type(e).__name__}: {e})")
    return stale
