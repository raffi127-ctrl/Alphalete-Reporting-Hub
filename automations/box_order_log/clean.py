"""Parse + collapse the BOX Order Log crosstab into one row per sale.

The raw Tableau export gives one row per STATUS TRANSITION, not one row per
sale — a single sale shows up 3-4 times as it walks the pipeline. Carlos
cleans this by hand today (Loom 2026-07-18). This module does the same thing
in code.

Three things the raw export gets confusing, and what we do about them:

1. UNMERGING. In the Tableau UI the Business Name / Contract ID cells are
   merged down a status block, so a hand-export leaves blanks. The CROSSTAB
   export does not — it repeats the identifying columns on every row. So
   there is nothing to unmerge; Carlos's manual "drop the name down" step
   is free.

2. THE SALE KEY IS NOT THE CONTRACT ID. Contract 261766 (Center Street LLC)
   is FIVE separate sales — five accounts, five meters, five kWh figures —
   all filed under one contract. Carlos flags this in the Loom ("this one's
   two different sales"). Grouping on Contract ID alone silently merged 15
   groups in the 2026-07-18 pull. `Contract ID + Account Id` groups cleanly:
   250 groups, zero repeated statuses. That pair is the sale key.

3. WHAT COUNTS AS A SALE is not "Complete Sales > 0" — see JUNK_STATUSES and
   DEAD_LEVELS. Draft rows are tablet quotes and never count; a sale whose
   final state is Verification/TPV Failed doesn't count either; everything
   else does, including cancels and Incomplete.
"""
from __future__ import annotations

import codecs
import collections
import csv
import datetime as dt
import io
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

# THE JUNK FILTER IS `Draft`, NOT `Complete Sales = 0`.
#
# The Loom says "anything that's a zero can get filtered out", and that was the
# original rule here. It is wrong, and it was hiding real deals (found when
# Megan asked why week ending 6/27 looked short, 2026-07-18):
#
#   * `Complete Sales = 0` is true of Draft quotes AND of live deals sitting in
#     Verification/TPV Failed, Incomplete, or Cancelled by Broker. Filtering on
#     it dropped 16 real deals across six weeks — 3 of them with no other
#     contract for that business, so they vanished from the log entirely.
#   * Carlos's own hand-cleaned tab settles it: it carries rows whose PRIMARY
#     status is `Verification – TPV Failed`, and it lists TPV Failed and
#     Incomplete in Secondary Status. `Draft` appears nowhere in it — not as a
#     primary, not once in any secondary.
#
# So: Draft (PDF Generated / Awaiting Signature) is the tablet-quote noise and
# is dropped. Everything else is a real deal and stays, which also means the
# cancels question answers itself — a cancel is simply not a Draft.
# `Complete Sales` becomes what it looks like: an informational column.
JUNK_STATUSES = ("Draft",)

# Sales whose FINAL state is one of these are not sales. Applied after the
# collapse, not to raw rows, so a TPV failure that a deal later recovered from
# still shows in its Secondary Status — it's only fatal when nothing better
# ever happened.
#
# Carlos, 2026-07-18: "those that say verification TPV failed — those aren't
# actual sales." In the same breath he went the other way on the neighbouring
# one: "this incomplete, missing contract data, that one SHOULD be considered
# a sale." So Incomplete stays (colored bright red — chase it);
# only TPV Failed is dropped.
DEAD_LEVELS = ("Verification – TPV Failed",)

# ---------------------------------------------------------------------------
# Priority — DERIVED FROM CARLOS'S OWN HAND-CLEANED TAB, not from the Loom.
#
# His "Box Order Log" tab splits each sale into a primary Status plus a
# "Secondary Status" list of everything else it passed through. That gives 69
# worked examples of "which status wins", i.e. ~60 pairwise constraints. They
# contain ZERO contradictions, and the total order below satisfies all of them
# and reproduces 69/69 of his primary picks exactly (verified 2026-07-18).
#
# Two of those constraints are the OPPOSITE of what the Loom implies, which is
# why this is derived rather than guessed:
#   * Ready For Booking BEATS Accepted by Supplier. It's the outstanding
#     action — "we need to submit a copy of the bill" — so it must not be
#     hidden behind an acceptance. (Carlos later confirmed it should still
#     read GREEN: the deal is healthy, the document is routine.)
#   * Accepted by Supplier BEATS Cancelled by Broker. A later acceptance
#     supersedes an earlier cancel, so cancels only surface when nothing
#     better exists.
#
# Verification is ranked by its SUB-status, because he ranks TPV Passed above
# "Submitted to Supplier" but TPV Failed below it.
LEVEL_PRIORITY = (
    "Ready For Booking",
    "Accepted by Supplier",
    "Verification – TPV Passed",
    "Verification – Requires TPV Review",
    "Submitted to Supplier",
    "Verification – TPV Failed",
    "Cancelled by Broker",
    "Rejected",
    "Incomplete",
    "Dropped",
    "Draft",
)

# Coarse statuses, for the summary counts and the color rules. Verification
# collapses back to one bucket here — Carlos counts it as one column.
STATUS_PRIORITY = (
    "Ready For Booking",
    "Accepted by Supplier",
    "Submitted to Supplier",
    "Verification",
    "Cancelled by Broker",
    "Rejected",
    "Incomplete",
    "Dropped",
    "Draft",
)

# En-dash, matching the separator already in his sheet.
_LEVEL_SEP = " – "


def level(status: str, sub_status: str) -> str:
    """The fine-grained rank key: 'Verification – TPV Passed' vs plain status.

    Mirrors how Carlos writes the Secondary Status column, so a level we emit
    round-trips against the ones already in his tab.
    """
    status = (status or "").strip()
    sub_status = (sub_status or "").strip()
    if status == "Verification" and sub_status:
        return status + _LEVEL_SEP + sub_status
    return status

# What each surfaced status means for Carlos, in his words. Shown in the PDF
# legend so a rep reading the log knows whether the ball is in their court.
STATUS_MEANING = {
    "Accepted by Supplier":  "Done — will activate.",
    "Ready For Booking":     "Good; a document still to send.",
    "Submitted to Supplier": "Waiting on the supplier — nothing for us to do.",
    "Verification":          "In TPV. Orange = we still owe a bill or ETF "
                             "document. Yellow = already submitted, waiting.",
    "Incomplete":            "ACTION NEEDED — missing contract data.",
    "Cancelled by Broker":   "Cancelled by broker.",
    "Rejected":              "Rejected by the supplier.",
    "Dropped":               "Dropped.",
}

# Color says WHO HAS THE BALL, which is not the same as what the status is.
# Carlos, Loom on the live sheet (2026-07-18): the ones already submitted are
# "just waiting for them to be accepted"; the ones still in verification are
# where "we have to do something — we need a bill or an early termination fee
# thing". He asked for those two to be distinguishable, and they are.
#
# The subtle part: that split depends on the sale's HISTORY, not its current
# status. A sale showing "Verification – TPV Passed" is only waiting if it was
# already submitted. Hence color_for() rather than a plain status->color dict.
# Megan's palette (2026-07-18). Two greens and two reds, deliberately: the
# brighter shade of each is the one that wants attention.
GREEN_BRIGHT = "92D050"   # Ready For Booking — good, one doc still to send
GREEN = "57BB8A"          # Accepted by Supplier — done
YELLOW = "FFFB00"         # macOS "Lemon" — Megan picked it 2026-07-18
ORANGE = "F4B183"         # we owe something (bill / ETF doc)
RED = "E67C73"            # dead: cancelled, rejected, dropped
RED_BRIGHT = "EA4335"     # Incomplete — dead-ish but fixable, chase it

SUBMITTED = "Submitted to Supplier"

# Kept for the legend and for anything that only knows a bare status.
STATUS_COLORS = {
    "Ready For Booking":     GREEN_BRIGHT,
    "Accepted by Supplier":  GREEN,
    "Submitted to Supplier": YELLOW,
    "Verification":          ORANGE,
    "Incomplete":            RED_BRIGHT,
    "Cancelled by Broker":   RED,
    "Rejected":              RED,
    "Dropped":               RED,
}


def color_for(status: str, history: Sequence[str] = ()) -> str:
    """The fill for one sale, given its status AND everything it passed through.

    Carlos's distinction survives the repaint: "we're just waiting for them to
    be accepted" and "we have to do something" must stay separable. In this
    palette that's yellow vs orange, so a Verification sale that has already
    been submitted reads as waiting (yellow), and one that hasn't reads as
    ours to chase (orange).
    """
    status = (status or "").strip()
    if status == "Ready For Booking":
        return GREEN_BRIGHT
    if status == "Accepted by Supplier":
        return GREEN
    if status in ("Cancelled by Broker", "Rejected", "Dropped"):
        return RED
    if status == "Incomplete":
        return RED_BRIGHT
    if status == SUBMITTED:
        return YELLOW
    if status == "Verification":
        return (YELLOW if any(h.startswith(SUBMITTED) for h in history)
                else ORANGE)
    return ""

# Darker twins of STATUS_COLORS for use as TEXT on a white background — the
# fill colors are tuned to sit behind black text and wash out when used as
# ink (pale-yellow "Verification" counts were unreadable on the summary).
STATUS_INK = {
    "Ready For Booking":     "4E7A1E",
    "Accepted by Supplier":  "1E7A4C",
    "Submitted to Supplier": "9A6A00",
    "Verification":          "B25A1E",
    "Incomplete":            "CC0000",
    "Cancelled by Broker":   "CC0000",
    "Rejected":              "CC0000",
    "Dropped":               "CC0000",
}

# Column order for the rendered log. Labels on the left are the crosstab's
# own header text; we look columns up BY LABEL, never by index, because the
# view's column order is Carlos's to change.
COLUMNS = (
    ("Sale Date",                 "Sale Date"),
    ("Rep Name",                  "Rep"),
    ("Business Name",             "Business"),
    ("Contract ID",               "Contract"),
    ("Status",                    "Status"),
    ("Contr. Sub-status",         "Sub-status"),
    ("Accepted Date",             "Accepted"),
    ("Term",                      "Term"),
    ("Sales (All) kWH+Therms",    "kWh+Therms"),
)

SALE_KEY_COLUMNS = ("Contract ID", "Account Id")


class Sale(NamedTuple):
    """One real sale, collapsed from its status-transition rows."""
    key: Tuple[str, str]
    fields: Dict[str, str]       # the surfaced row's values
    status: str                  # coarse status, e.g. "Verification"
    sub_status: str
    level: str                   # fine-grained, e.g. "Verification – TPV Passed"
    sale_date: Optional[dt.date]
    accepted_date: Optional[dt.date]
    week_ending: Optional[dt.date]   # from accepted date, else sale date
    history: Tuple[str, ...]     # every level this sale passed through
    secondary: str               # history minus the surfaced level, his format
    is_cancel: bool


def _decode(path: Path) -> str:
    """Tableau writes UTF-16 TSV. Fall back for hand-saved files."""
    raw = Path(path).read_bytes()
    for enc in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_rows(path: Path) -> List[Dict[str, str]]:
    """Read the crosstab into dicts keyed by the header labels."""
    text = _decode(path)
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not rows:
        return []
    # Tableau sometimes leaves a BOM glued to a mid-row header label
    # (the 2026-07-18 pull had it on "Contract ID", not on column 0).
    header = [h.replace(codecs.BOM_UTF8.decode("utf-8"), "").lstrip("﻿").strip()
              for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not any(v.strip() for v in r):
            continue
        out.append(dict(zip(header, r)))
    return out


def _parse_date(value: str) -> Optional[dt.date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def week_ending(d: dt.date) -> dt.date:
    """Saturday of the Sun-Sat week containing `d`.

    Same convention as Raf's Fiber Order Log (`order_log._week_bounds`), so
    the two reports line up week-for-week.
    """
    sunday = d - dt.timedelta(days=(d.weekday() + 1) % 7)
    return sunday + dt.timedelta(days=6)


# TWO DATES, TWO PURPOSES — do not merge them again.
#
#   Sale.week_ending  = the week the deal was SOLD.      -> the LOG
#   Sale.accepted_date = when the supplier accepted it.  -> the PAYOUT tables
#
# The log groups by SALE date. Carlos counts his week that way: "it's showing
# 41 total sales when there's only 29 for this week" (2026-07-18).
#
# An earlier version bucketed the log by accepted-date-else-sale-date, and
# that number (41) was meaningless — it mixed 19 deals ACCEPTED that week
# (11 of which were sold in earlier weeks) with 22 unaccepted deals falling
# back to their SALE week. Two different questions answered in one column.
#
# Accepted Date still decides the PAYOUT week, exactly as Carlos said in Slack
# ("based off of the date it was accepted by the supplier"), but that lives in
# payout.py where it belongs and never touches the log's week.


def _is_complete(row: Dict[str, str]) -> bool:
    raw = (row.get("Complete Sales") or "").strip().replace(",", "")
    try:
        return float(raw) > 0
    except ValueError:
        return False


def _priority(lvl: str) -> int:
    """Rank of a fine-grained level. Unknown levels sort last rather than
    raising — a new Tableau status should demote itself, not break the run."""
    lvl = (lvl or "").strip()
    if lvl in LEVEL_PRIORITY:
        return LEVEL_PRIORITY.index(lvl)
    # An unseen Verification sub-status still ranks as Verification-ish.
    base = lvl.split(_LEVEL_SEP)[0]
    if base in LEVEL_PRIORITY:
        return LEVEL_PRIORITY.index(base)
    return len(LEVEL_PRIORITY)


def _row_level(row: Dict[str, str]) -> str:
    return level(row.get("Status", ""), row.get("Contr. Sub-status", ""))


def _status_rank(status: str) -> int:
    status = (status or "").strip()
    return (STATUS_PRIORITY.index(status)
            if status in STATUS_PRIORITY else len(STATUS_PRIORITY))


def collapse(rows: Iterable[Dict[str, str]]) -> Tuple[List[Sale], Dict[str, int]]:
    """Collapse status-transition rows into one Sale per real sale.

    Returns (sales, stats). `stats` records what was dropped so the caller can
    surface it — a silent filter on a report Carlos is going to trust with
    commission questions is worse than no report.
    """
    rows = list(rows)
    stats = collections.Counter()
    stats["raw_rows"] = len(rows)

    kept: List[Dict[str, str]] = []
    for row in rows:
        status = (row.get("Status") or "").strip()
        if status in JUNK_STATUSES:
            stats["dropped_never_a_sale"] += 1
            continue
        kept.append(row)
        if not _is_complete(row):
            # Real deal, just not a completed sale yet (TPV failed, incomplete,
            # cancelled). Counted so the run log can show we KEPT these rather
            # than silently swallowing them, which is what the old rule did.
            stats["kept_incomplete"] += 1

    groups: "collections.OrderedDict[Tuple[str, str], List[Dict[str, str]]]"
    groups = collections.OrderedDict()
    for row in kept:
        key = tuple((row.get(c) or "").strip() for c in SALE_KEY_COLUMNS)
        groups.setdefault(key, []).append(row)

    sales: List[Sale] = []
    for key, members in groups.items():
        surfaced = min(members, key=lambda r: _priority(_row_level(r)))
        status = (surfaced.get("Status") or "").strip()
        sub_status = (surfaced.get("Contr. Sub-status") or "").strip()
        lvl = _row_level(surfaced)
        sale_date = _parse_date(surfaced.get("Sale Date", ""))
        # Take the acceptance from ANY row in the group, not just the surfaced
        # one: a sale showing "Ready For Booking" can still carry an Accepted
        # Date on its acceptance row, and that date is what decides its week.
        accepted_dates = [d for d in
                          (_parse_date(m.get("Accepted Date", "")) for m in members)
                          if d]
        accepted_date = max(accepted_dates) if accepted_dates else None
        history = tuple(sorted({_row_level(m) for m in members}, key=_priority))
        # Everything the sale passed through EXCEPT what we surfaced — this is
        # Carlos's "Secondary Status" column, same order and separator he uses.
        secondary = ", ".join(h for h in history if h != lvl)
        sales.append(Sale(
            key=key,
            fields=surfaced,
            status=status,
            sub_status=sub_status,
            level=lvl,
            sale_date=sale_date,
            accepted_date=accepted_date,
            week_ending=week_ending(sale_date) if sale_date else None,
            history=history,
            secondary=secondary,
            is_cancel=status == "Cancelled by Broker",
        ))
        stats["collapsed_rows"] += len(members) - 1
        if not sale_date:
            stats["missing_sale_date"] += 1

    # Drop the ones that ended dead. Post-collapse so their history survives
    # on any sale that recovered — see DEAD_LEVELS.
    before = len(sales)
    sales = [s for s in sales if s.level not in DEAD_LEVELS]
    stats["dropped_dead"] = before - len(sales)

    stats["sales"] = len(sales)
    sales.sort(key=lambda s: (s.week_ending or dt.date.min,
                              _priority(s.level),
                              (s.fields.get("Rep Name") or "")))
    return sales, dict(stats)


def last_n_weeks(sales: Iterable[Sale], n: int = 6,
                 today: Optional[dt.date] = None) -> List[Sale]:
    """Keep only sales in the most recent `n` week-endings.

    Carlos wants a rolling six-week window — "every new week, the oldest log
    would delete". Anchoring on the CURRENT week rather than on whatever the
    data happens to contain means a quiet week can't extend the window
    backwards, and a stray future-dated sale can't push six real weeks out.
    """
    sales = list(sales)
    today = today or dt.date.today()
    current = week_ending(today)
    oldest = current - dt.timedelta(weeks=n - 1)
    return [s for s in sales
            if s.week_ending and oldest <= s.week_ending <= current]


def by_week(sales: Iterable[Sale]) -> "collections.OrderedDict":
    """Group collapsed sales by week ending, newest week first."""
    buckets: Dict[Optional[dt.date], List[Sale]] = collections.defaultdict(list)
    for s in sales:
        buckets[s.week_ending].append(s)
    ordered = collections.OrderedDict()
    for wk in sorted((w for w in buckets if w), reverse=True):
        ordered[wk] = buckets[wk]
    if None in buckets:                       # undated sales land at the end
        ordered[None] = buckets[None]
    return ordered


def week_counts(sales: Iterable[Sale]) -> Tuple[List[Optional[dt.date]],
                                                List[str],
                                                Dict[Tuple, int]]:
    """Count of sales per (week ending, surfaced status) for the summary table.

    This is the "count of everything by the week ending, like AT&T has"
    Carlos asks for at the end of the Loom.
    """
    sales = list(sales)
    counts = collections.Counter((s.week_ending, s.status) for s in sales)
    weeks = sorted({s.week_ending for s in sales if s.week_ending}, reverse=True)
    if any(s.week_ending is None for s in sales):
        weeks.append(None)
    seen = {s.status for s in sales}
    statuses = [s for s in STATUS_PRIORITY if s in seen]
    return weeks, statuses, dict(counts)


def reps(sales: Iterable[Sale]) -> List[str]:
    """Rep names present, for the dropdown."""
    return sorted({(s.fields.get("Rep Name") or "").strip()
                   for s in sales if (s.fields.get("Rep Name") or "").strip()})


def load(path: Path) -> Tuple[List[Sale], Dict[str, int]]:
    return collapse(read_rows(Path(path)))
