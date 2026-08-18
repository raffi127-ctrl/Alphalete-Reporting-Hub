"""A capped or stale Tableau pull is ALWAYS heard — every report, every day.

WHY (Megan, 2026-08-17, "daily loud on EVERYTHING"): the BOX Order Log spent
2026-08-14, 8/15 and 8/16 sending real emails and posting a real Slack thread
built on an export frozen at 8/13. Nothing was broken in a way anything could
see: the pull succeeded, the rows parsed, the numbers rendered — they were just
three days short, because the view's `Contract ID` filter had re-pinned to a
stale ID list. The one guard that existed (box_order_log.window.should_block_send)
only refuses to DELIVER at 4+ days behind, so 1-3 days behind shipped silently.
On 8/17 it finally crossed the threshold and everyone noticed — three days late.

That guard was per-report and delivery-time. This one is neither: it hangs off
the SHARED crosstab download, so all ~120 Tableau-pulling modules inherit it
without a line of their own, and it fires whether the report then sends,
suppresses, writes a Sheet, or does nothing at all. Being heard is not
conditional on the report deciding to stop.

WHAT COUNTS AS STALE
Default: the newest date anywhere in the export is 2+ days behind today. A
healthy daily feed pulled in the morning has yesterday's data (1 day behind) and
stays quiet. A feed that freezes is 2 days behind by the next morning and alerts
then — which on the 8/13 incident means the first alert lands the morning of
8/15, before that day's bad send, instead of on 8/17 after three of them.

One day of slack is deliberate. Sunday-quiet campaigns, a supplier that posts
overnight, a report that runs at 4am against a feed refreshed at 7am — all sit
exactly one day back on a good day, and a gate that shouts about those would be
muted within a week. `max_days_behind` raises it per source for feeds that are
legitimately laggier; `needs` sets an explicit date the export must reach.

WHAT IS NOT JUDGED
An export with no parseable date column is returned as "unknown" and never
alerts — rosters, mappings and reference lists have no data date, and inventing
staleness for them would be noise. Silence here means "cannot judge", which is
why it is logged rather than swallowed.

NOISE CONTROL
One alert per (view, sheet) per day, tracked by a dated marker, so a source
pulled 50 times by 50 offices produces ONE line. The alert carries every report
that hit it that day, appended as it learns them — the second report to hit a
stale source updates the existing thread rather than opening another. Alerts ride
section_drop_alert into #claudecorrections-and-requests, keyed by source, so a
source stuck for a week is one thread with a reply a day, not seven posts.

NEVER BREAKS A RUN. Every entry point is wrapped: a bug in the freshness check
must not take down a report that pulled its data perfectly well.
"""
from __future__ import annotations

import codecs
import csv
import datetime as dt
import io
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "output" / "tableau_freshness"

# Newest data date may sit this many days behind today before it's "stale".
# 1 = yesterday is fine, the day before is not. See the module docstring.
DEFAULT_MAX_DAYS_BEHIND = 1

# A column carries a row's own event date if the word "date" appears in its
# header. Surveyed against every crosstab this repo has on disk (279 exports,
# 2026-08-17): that one rule catches "Sale Date", "Order Date", "Accepted Date",
# "Status Date", "cl.Activation Date", "spe.Install Date", "sp.Order Date (copy)",
# "Date / Blank", "Date of Last Sale in Zip" — and, because it needs no
# enumeration, the misspelled "Activatoin Date (order log)" that a hand-written
# list would have missed and quietly under-covered.
#
# WORD boundary, not substring: "0-30 Day Churn", "Days Since Last Sale",
# "Days to Appointment" and the weekday columns ("Monday"…"Sunday") are metric
# names, not dates, and matching them would feed junk to the parser.
_DATE_WORD = re.compile(r"\bdates?\b")
# Headers that ARE dates but describe the PULL, never the data. These carry
# TODAY every single time, so treating one as the data date would certify any
# frozen feed as perfectly fresh — the exact failure this module exists to catch.
DATE_COLUMN_EXCLUDE = (
    "date pulled", "pull date", "report date", "run date", "as of",
    "last refresh", "refreshed", "generated", "export date", "today",
    "week ending", "week of",   # rollup labels, not row events
)

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y",
                 "%B %d, %Y", "%b %d, %Y")
# A bare date at the start of a cell, e.g. "8/13/2026 4:21:07 PM".
_LEADING_DATE = re.compile(r"^\s*(\d{1,4}[/-]\d{1,2}[/-]\d{2,4})")
# YEARLESS day labels, the shape the by-day boards use: "Mon (07-13)", "(8/16)",
# "07-13". The org / country / box sales boards are all pivoted this way — the
# day is the COLUMN, so its label is the only date in the file. Without this they
# read as "no parseable dates" and the daily boards, which are exactly the ones
# a frozen feed would embarrass us on, would carry no freshness cover at all.
_YEARLESS = re.compile(r"^\s*(?:[A-Za-z]{3,9}\s*)?\(?\s*(\d{1,2})[/-](\d{1,2})\s*\)?\s*$")


# --------------------------------------------------------------------------
# reading an export
# --------------------------------------------------------------------------

def _decode(path) -> str:
    """Tableau crosstabs come back UTF-16 tab-separated more often than not, but
    the HTTP-direct pulls are UTF-8 comma-separated. Try the encodings in the
    order they actually occur and keep whichever decodes."""
    raw = Path(path).read_bytes()
    for enc in ("utf-16", "utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if text.strip():
            return text
    return raw.decode("latin-1", errors="replace")


def _rows(path, limit: int = 200_000) -> Tuple[List[str], List[List[str]]]:
    """(header, rows). Sniffs tab vs comma on the header line — a crosstab is
    tab-separated, an HTTP CSV pull is not, and both reach this module."""
    text = _decode(path)
    if not text.strip():
        return [], []
    first = text.splitlines()[0]
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    # newline="" so a cell containing a bare CR (Tableau emits them inside
    # free-text fields like rep notes) doesn't raise "new-line character seen in
    # unquoted field" and cost us the whole export's freshness cover.
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delim)
    try:
        header = next(reader)
    except StopIteration:
        return [], []
    bom = codecs.BOM_UTF8.decode("utf-8")
    header = [h.replace(bom, "").lstrip("﻿").strip() for h in header]
    out = []
    for i, r in enumerate(reader):
        if i >= limit:
            break
        out.append(r)
    return header, out


def parse_date(value: str, today: Optional[dt.date] = None) -> Optional[dt.date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    m = _LEADING_DATE.match(value)
    if m:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
            try:
                return dt.datetime.strptime(m.group(1), fmt).date()
            except ValueError:
                continue
    m = _YEARLESS.match(value)
    if m:
        today = today or dt.date.today()
        mo, day = int(m.group(1)), int(m.group(2))
        # Pick the year that puts the label nearest to today WITHOUT going into
        # the future: a "12-28" column read on Jan 3rd is last December, not next.
        for year in (today.year, today.year - 1):
            try:
                cand = dt.date(year, mo, day)
            except ValueError:
                continue
            if cand <= today + dt.timedelta(days=1):
                return cand
    return None


def _date_columns(header: Sequence[str]) -> List[int]:
    idx = []
    for i, h in enumerate(header):
        low = (h or "").strip().lower()
        if not low or any(x in low for x in DATE_COLUMN_EXCLUDE):
            continue
        if _DATE_WORD.search(low):
            idx.append(i)
    return idx


def newest_date(path,
                today: Optional[dt.date] = None) -> Tuple[Optional[dt.date], str]:
    """(newest event date in the export, which column it came from).

    (None, reason) when the export carries no judgeable date. Dates in the
    FUTURE are ignored — scheduled-install and appointment columns are full of
    them, and one appointment booked for next month would otherwise certify a
    frozen feed as perfectly fresh."""
    today = today or dt.date.today()
    header, rows = _rows(path)
    if not header:
        return None, "empty export"
    cols = _date_columns(header)
    if not cols:
        return None, "no event-date column"
    best, best_col = None, ""
    for r in rows:
        for i in cols:
            if i >= len(r):
                continue
            d = parse_date(r[i], today=today)
            if d is None or d > today:
                continue
            if best is None or d > best:
                best, best_col = d, header[i]
    if best is None:
        return None, "no parseable dates in {}".format(
            ", ".join(header[i] for i in cols)[:80])
    return best, best_col


# --------------------------------------------------------------------------
# the daily alert (one per source per day, reports appended as they arrive)
# --------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


def _state_path(source_key: str, day: dt.date) -> Path:
    return STATE_DIR / "{}-{}.json".format(_slug(source_key), day.isoformat())


def _load_state(source_key: str, day: dt.date) -> dict:
    try:
        return json.loads(_state_path(source_key, day).read_text("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(source_key: str, day: dt.date, state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _state_path(source_key, day).write_text(
            json.dumps(state, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _view_label(view_url: str, sheet: str = "") -> str:
    """'B2BBOXEnergyTracker/BoxOrderLog → Order Log' — the workbook/view path a
    person can actually open, not the 200-char URL with its uuid and :iid."""
    m = re.search(r"/views/([^?#]+)", view_url or "")
    path = m.group(1) if m else (view_url or "unknown view")
    parts = [p for p in path.split("/") if p and not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", p)]
    label = "/".join(parts[:3]) if parts else path
    return "{} → {}".format(label, sheet) if sheet else label


def alert_stale(source_key: str, view_label: str, newest: Optional[dt.date],
                needs: dt.date, today: dt.date, report: str,
                detail: str = "") -> bool:
    """Fire (or extend) today's ONE alert for this stale source.

    Returns True if a message went out, False if today's alert already exists
    and this report was already on it. Never raises."""
    try:
        state = _load_state(source_key, today)
        reports = list(state.get("reports") or [])
        first_time = not state.get("alerted")
        if report and report not in reports:
            reports.append(report)
        if not first_time:
            # ONE message per stale source per day. Every later report that hits
            # the same frozen view is recorded in the state file but stays quiet:
            # the org-wide feeds are pulled by ~20 offices apiece, and appending
            # a thread reply per office would bury the one line that matters
            # under twenty that say the same thing. The source is the
            # actionable fact; who tripped over it is forensics, and it's on
            # disk in output/tableau_freshness/ when someone wants it.
            _save_state(source_key, today, dict(state, reports=reports))
            return False

        behind = (today - newest).days if newest else None
        if newest:
            how = "newest data is {} — {} day(s) behind {}, needs {}".format(
                newest, behind, today, needs)
        else:
            how = "no usable dates in the export at all (needs {})".format(needs)
        line = "{} — {}".format(view_label, how)
        if detail:
            line += " · {}".format(detail)
        if reports:
            line += " · hit by: {}".format(", ".join(sorted(reports)))

        from automations.shared import section_drop_alert as sda
        # report_id is the SOURCE, not the report: fifty offices pulling one
        # frozen view is one problem with one thread, and the reports that hit
        # it ride inside the line. A different stale view gets its own thread.
        sda.alert(report_id="tableau-stale-{}".format(_slug(source_key)),
                  failed=[line], kind="capped", day=today)
        state.update({"alerted": True, "reports": reports,
                      "newest": newest.isoformat() if newest else None,
                      "view": view_label})
        _save_state(source_key, today, state)
        return True
    except Exception:  # noqa: BLE001 — an alert must never sink a run
        return False


def alert_unconfirmed_filter(source_key: str, view_label: str,
                             problems: Sequence[str], today: dt.date,
                             report: str = "") -> bool:
    """One daily alert when a view's pinning filters can't be CONFIRMED released.

    Sibling of alert_stale, sharing its dedupe and its thread: a pinned filter is
    the usual CAUSE of a stale export, so the two belong in one conversation
    rather than as two unrelated posts about the same morning. Called by
    box_order_log.window.confirm_release; any other view that learns to release
    its own pins can call this the same way."""
    try:
        state = _load_state(source_key, today)
        reports = list(state.get("reports") or [])
        if report and report not in reports:
            reports.append(report)
        if state.get("alerted"):
            _save_state(source_key, today, dict(state, reports=reports))
            return False
        line = ("{} — could not confirm the view is unpinned: {}. Any export "
                "taken now may be silently capped.".format(
                    view_label, " · ".join(problems)))
        if reports:
            line += " · hit by: {}".format(", ".join(sorted(reports)))
        from automations.shared import section_drop_alert as sda
        sda.alert(report_id="tableau-stale-{}".format(_slug(source_key)),
                  failed=[line], kind="capped", day=today)
        _save_state(source_key, today,
                    {"alerted": True, "reports": reports, "view": view_label,
                     "kind": "unconfirmed-filter"})
        return True
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------
# the gate every pull goes through
# --------------------------------------------------------------------------

def check_export(path,
                 view_url: str = "",
                 sheet: str = "",
                 report: str = "",
                 needs: Optional[dt.date] = None,
                 max_days_behind: int = DEFAULT_MAX_DAYS_BEHIND,
                 today: Optional[dt.date] = None,
                 verbose: bool = False) -> Dict[str, object]:
    """Judge a freshly-downloaded export and alert loudly if it's stale.

    Returns {'verdict', 'newest', 'needs', 'column', 'behind', 'alerted'} where
    verdict is 'fresh' | 'stale' | 'unknown'. 'unknown' means the export has no
    event-date column to judge — reported, never alerted.

    Wrapped end to end: a report whose data is fine must never fail because the
    freshness check tripped over something."""
    out = {"verdict": "unknown", "newest": None, "needs": None,
           "column": "", "behind": None, "alerted": False}
    try:
        today = today or dt.date.today()
        needs = needs or (today - dt.timedelta(days=max_days_behind))
        out["needs"] = needs
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            out["column"] = "missing or empty export"
            return out
        newest, col = newest_date(p, today=today)
        out["newest"], out["column"] = newest, col
        if newest is None:
            if verbose:
                print("  [freshness] {} — not judged ({})".format(
                    _view_label(view_url, sheet), col), flush=True)
            return out
        out["behind"] = (today - newest).days
        if newest >= needs:
            out["verdict"] = "fresh"
            if verbose:
                print("  [freshness] {} — newest {} (ok)".format(
                    _view_label(view_url, sheet), newest), flush=True)
            return out
        out["verdict"] = "stale"
        label = _view_label(view_url, sheet)
        print("  ⚠ STALE PULL: {} — newest data {}, needs {} ({} day(s) "
              "behind). Numbers built on this UNDERSTATE reality.".format(
                  label, newest, needs, out["behind"]), flush=True)
        # Key on the LABEL, not the URL: the workbook/view/sheet path is stable
        # and readable, so the incident thread reads
        # `tableau-stale-b2bboxenergytracker-boxorderlog-order-log` instead of
        # 60 chars of truncated hostname. Two URLs for the same view (differing
        # :iid, a uuid segment) also collapse to one source, which is right.
        out["alerted"] = alert_stale(
            source_key=label, view_label=label, newest=newest,
            needs=needs, today=today, report=report or _current_report())
        return out
    except Exception:  # noqa: BLE001
        return out


def _current_report() -> str:
    """Best-effort name of the report doing the pulling, for the alert line.

    The orchestrator exports ALPHALETE_REPORT_ID around each run; outside it we
    fall back to the module python was invoked with (`python -m
    automations.box_order_log.run` → box_order_log), which covers `lucy rerun`
    and hand-runs."""
    import os
    import sys
    rid = (os.environ.get("ALPHALETE_REPORT_ID") or "").strip()
    if rid:
        return rid
    for a in sys.argv:
        m = re.match(r"automations\.([a-z0-9_]+)", a or "")
        if m:
            return m.group(1)
    try:
        main = sys.modules.get("__main__")
        name = getattr(main, "__package__", "") or ""
        if name.startswith("automations."):
            return name.split(".")[1]
    except Exception:  # noqa: BLE001
        pass
    return "unknown-report"
