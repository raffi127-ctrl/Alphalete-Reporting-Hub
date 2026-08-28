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

3. WHAT COUNTS AS A SALE is not "Complete Sales > 0" — see JUNK_STATUSES,
   DEAD_LEVELS and SALE_LEVELS. Draft rows (incl. "signed contract") are
   tablet quotes and never count; a sale whose final state is Verification/TPV
   Failed doesn't count either. A deal only becomes a sale once it has REACHED
   TPV or beyond (Carlos, 2026-07-22: "TPV completed and forward is a sale...
   but it could go to cancelled at any point") — so a cancel/reject that never
   passed TPV is dropped, while one that passed TPV and later cancelled stays.
   Incomplete is exempt and always counts (Megan).
"""
from __future__ import annotations

import codecs
import collections
import csv
import datetime as dt
import io
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

from automations.shared.name_case import titlecase_name

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
# a sale." So Incomplete stays (colored bright red — chase it).
#
# REJECTED QC added 2026-07-22 from the Smart Circle analyst's follow-up
# (Alice Cao, acao@thesmartcircle.com): "some orders falling under Verification
# are NOT counted as a complete sale if their sub-status is Rejected QC or TPV
# Failed." Her first mail listed Verification wholesale as complete; this
# carves out the two failure sub-states. Rejected QC does not appear in the
# 2026-07-18 pull at all — the only Verification sub-statuses present are TPV
# Passed (48), TPV Failed (20) and Requires TPV Review (2) — so nothing changes
# today. It is here so the first one that DOES arrive isn't silently counted.

# En-dash, matching the separator already in his sheet. Defined up here because
# DEAD_LEVELS builds level strings with it.
_LEVEL_SEP = " – "

DEAD_VERIFICATION_SUBS = ("TPV Failed", "Rejected QC")

DEAD_LEVELS = tuple("Verification" + _LEVEL_SEP + sub
                    for sub in DEAD_VERIFICATION_SUBS)

# THE TPV GATE — a deal is only a sale once it has REACHED TPV or beyond.
#
# Carlos, 2026-07-22, giving his own definition: "TPV completed and forward is
# a sale. But it could go to 'cancelled by broker' at any point in time." And
# what is NOT a sale: "signed contract" and "draft" — both of which turn out to
# be sub-states of Draft in the data (`Draft / Signed`, `Draft / PDF
# Generated`, ...), so they're already dropped by JUNK_STATUSES above.
#
# The gate is on the sale's HISTORY, not its surfaced status, precisely because
# of his "cancel at any point" clause: a deal that reached TPV Passed and was
# LATER cancelled is a (dead) sale and still counts; a deal cancelled or
# rejected while it was still a signed contract — i.e. that never passed TPV —
# was never a sale. In the 2026-07-18 pull every cancel/reject fell in the
# second group (history was just the cancel itself), so this drops 14 of them
# and keeps 104. It keeps every TPV-Passed / Submitted / Accepted / Ready deal,
# including the ones reading Complete Sales = 0 because the supplier hasn't
# accepted them yet — which is why this is the RIGHT gate and "Complete Sales =
# 0" is the wrong one (see JUNK_STATUSES).
# Confirmed by the Smart Circle analyst (Alice Cao, acao@thesmartcircle.com,
# fwd 2026-07-22): "Any orders with the following statuses will show up as
# complete: Accepted by Supplier, Ready for Booking, Submitted to Supplier,
# Verification." So ALL non-failed Verification counts — including
# "Requires TPV Review", not just "TPV Passed". (TPV Failed still drops via
# DEAD_LEVELS; the supplier's Complete Sales column marks it 0 too.) Her list
# leaves out Cancelled by Broker/DocuSign, Dropped, Rejected, Draft and
# Reinstated — all of which we already drop. Incomplete she also leaves out,
# but Megan keeps it (SALE_EXEMPT_STATUSES).
SALE_LEVELS = (
    "Ready For Booking",
    "Accepted by Supplier",
    "Verification – TPV Passed",
    "Verification – Requires TPV Review",
    "Submitted to Supplier",
)

# Incomplete / Missing Contract Data reads 0 and may never have reached TPV,
# but Megan keeps it a sale regardless (2026-07-18, reaffirmed 2026-07-22).
SALE_EXEMPT_STATUSES = ("Incomplete",)

# Sub-statuses that prove a deal REACHED THE SUPPLIER even though no other
# status survived on it. Carlos, 2026-08-27, on deals whose only row is
# Rejected / Rejected By Supplier: "I'm not sure why they don't have the other
# statuses, but if they got all the way to 'rejected by supplier', that means
# it was a sale at some point."
#
# The TPV gate reads the levels a deal passed through, and these rows have
# exactly one — "Rejected" — so the gate dropped them as never-a-sale. The
# SUB-status is the only evidence left that the supplier ever saw it.
#
# Deliberately just this one. The other rejected-only sub-statuses in the
# 2026-08-17 pull — Customer Rescinded (12), Residential Rejection (8), Needs
# Contract Data (4), Rejected by Utility (1), Clean Bill Copy Needed (1) —
# don't say the supplier ever got it, and Carlos named this one. Add a line
# here if he rules on the others.
SUPPLIER_SAW_IT_SUBS = ("rejected by supplier",)


# THE TPV MEMORY — a sale stays a sale once we've seen it pass TPV.
#
# Found 2026-08-28 chasing "El Meson Doña Tere" (ctr 278285). The sheet
# recorded it as Verification / TPV Passed on 8/14. Two weeks later the export
# carries only two rows for it — `Draft / Awaiting Signature` and `Cancelled by
# Broker` — and the TPV row is simply GONE. The gate above reads history, so
# with the TPV row missing the deal reads as "cancelled before it ever reached
# TPV" and is dropped: it vanishes from the workbook and the payout tables.
#
# It is not one deal. On the 8/28 pull, 21 sales sitting on the sheet as live
# were being gated out of the workbook the same way.
#
# The two artifacts then disagree, and each is wrong in its own direction. The
# SHEET merges, so a sale missing from today's pull is carried — it kept
# showing the stale "TPV Passed" forever. The WORKBOOK is rebuilt from the pull
# every morning with no memory, so it lost the sale entirely.
#
# Carlos's rule doesn't change: "TPV completed and forward is a sale, but it
# could go to cancelled by broker at any point." A deal that passed TPV and
# later cancelled IS a sale, and Tableau forgetting the TPV row is not the deal
# un-happening. So the gate now also accepts EXTERNAL evidence: a set of sale
# keys already recorded as having reached TPV, read off the sheet (the durable
# record we already keep). Rescued deals surface at their CURRENT status —
# El Meson comes back as Cancelled by Broker, not as a phantom TPV Passed —
# which fixes the sheet's over-reporting in the same move, because the merge
# now has a fresh row to replace the stale one with.
#
# Scope note: the memory is the sheet's six-week window, which is about the
# same span as the source view's rolling ~44 days. A deal older than that is
# beyond both, so nothing is resurrected from the distant past.


def norm_key(key) -> Tuple[str, str]:
    """Digits-only sale key, so the pull and the sheet agree.

    Sheets renders an ID column as a number the moment the format drifts, so
    "267770" comes back as "267,770" (the bug that duplicated every row on
    2026-07-18). Both sides go through this.
    """
    def digits(v):
        return "".join(ch for ch in str(v or "") if ch.isdigit())
    a, b = (tuple(key) + ("", ""))[:2]
    return (digits(a), digits(b))


def _norm_sub(sub: str) -> str:
    return " ".join((sub or "").split()).lower()

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
# REVISED 2026-08-21 from Carlos's own examples, which beat the hand-cleaned
# tab wherever the two disagree (see the CAVEAT note below — Megan flagged that
# tab as thin evidence for exactly these two lines).
#
#   1. "Accepted by Supplier" now beats "Ready For Booking". Rojero boots
#      (contract 276666) reads Accepted by Supplier on 8/18 in Tableau and we
#      were still showing Ready For Booking: "on tableau its already accepted
#      by supplier so it should be green". 13 sales in the 8/17 pull.
#   2. A sale that DIED beats anything still in flight. NS 35 barber shop
#      (271728) and Alsadi group #5 (269644) are both Rejected + Verification –
#      TPV Passed, and we surfaced the Verification: "it shows that the sale is
#      rejected by supplier, but then on the Lucy report it shows that it's
#      still pending". 105 sales in the 8/17 pull.
#
# Cancelled/Rejected/Dropped stay BELOW "Accepted by Supplier" on purpose. That
# pairing (64 sales) is a different question — an accepted deal that later died
# — Carlos has not ruled on it, and moving it would change what the payout
# tables count as paid. Left alone until he says otherwise.
LEVEL_PRIORITY = (
    "Accepted by Supplier",
    "Cancelled by Broker",
    "Rejected",
    "Dropped",
    "Ready For Booking",
    "Verification – TPV Passed",
    "Verification – Requires TPV Review",
    "Submitted to Supplier",
    "Verification – TPV Failed",
    "Verification – Rejected QC",
    "Incomplete",
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
GREEN_BRIGHT = "92D050"   # was Ready For Booking until 2026-08-20 (see below)
GREEN = "57BB8A"          # Accepted by Supplier — done
YELLOW = "FFFB00"         # macOS "Lemon" — Megan picked it 2026-07-18
ORANGE = "F4B183"         # we owe something (bill / ETF doc)
RED = "E67C73"            # dead: cancelled, rejected, dropped
RED_BRIGHT = "EA4335"     # Incomplete — dead-ish but fixable, chase it

SUBMITTED = "Submitted to Supplier"

# Ready For Booking is YELLOW, not green (Carlos, 2026-08-20, looking at the
# new pending tab: "ready for booking should be yellow ... outside of that it's
# good"). It used to be GREEN_BRIGHT; that constant is kept above so flipping
# back is one edit here. Read this off STATUS_COLORS rather than copying a
# color constant elsewhere — sheet.py's rules went stale exactly that way when
# Ready For Booking moved from red to green.
#
# Kept for the legend and for anything that only knows a bare status.
STATUS_COLORS = {
    "Ready For Booking":     YELLOW,
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

    Ready For Booking joined the yellow group on 2026-08-20 at Carlos's ask —
    which also moves it into the yellow SECTION of the pending tab, since that
    split reads this function (xlsx._pending_section).
    """
    status = (status or "").strip()
    if status == "Ready For Booking":
        return STATUS_COLORS["Ready For Booking"]
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
    "Ready For Booking":     "9A6A00",     # yellow's ink twin, since 2026-08-20
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
    # Every sub-status seen on the group's rows. level() only folds the
    # sub-status into Verification levels, so for a Rejected row it is the ONLY
    # place "Rejected By Supplier" survives — which is what the TPV gate needs
    # (SUPPLIER_SAW_IT_SUBS). Defaulted so older callers keep working.
    sub_statuses: Tuple[str, ...] = ()


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
        row = dict(zip(header, r))
        # Fix the rep's capitalization HERE, at the read, so every surface gets
        # it: the workbook (summary, rep tabs and their tab titles, pending),
        # the Sales Board push, the payout image, the per-office runs. Carlos's
        # reps type their own names into the contract, so the view hands us
        # "Cinthya reyes" and "CARLOS HIDALGO" next to properly-cased names.
        # Doing it at the source also merges what used to be two rep groups
        # when the same person appeared under two spellings of the same name.
        # The Sheet merge key is the contract/account id (sheet._norm_id), not
        # the name, so recasing can't duplicate a row that's already up there.
        rep = row.get("Rep Name")
        if rep:
            row["Rep Name"] = titlecase_name(rep)
        out.append(row)
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


def _reached_tpv(sale: "Sale", tpv_seen=frozenset()) -> bool:
    """True if the sale ever reached TPV Passed or beyond — Carlos's bar for a
    real sale. Incomplete is exempt (Megan keeps it regardless). Checks the
    whole history so a deal that passed TPV and was later cancelled still
    counts, while a cancel/reject that never got past a signed contract does
    not.

    "Rejected By Supplier" counts too, on the sub-status alone: the supplier
    can only reject what it received, so the deal got at least that far even
    though every other status is missing from the export (Carlos 2026-08-27).
    """
    if sale.status in SALE_EXEMPT_STATUSES:
        return True
    if any(_norm_sub(x) in SUPPLIER_SAW_IT_SUBS for x in sale.sub_statuses):
        return True
    if any(h in SALE_LEVELS for h in sale.history):
        return True
    # Nothing in TODAY's export says it reached TPV — but we may have seen it
    # do so on an earlier pull. See THE TPV MEMORY above.
    return norm_key(sale.key) in tpv_seen


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


def collapse(rows: Iterable[Dict[str, str]], *,
             tpv_seen=frozenset()) -> Tuple[List[Sale], Dict[str, int]]:
    """Collapse status-transition rows into one Sale per real sale.

    Returns (sales, stats). `stats` records what was dropped so the caller can
    surface it — a silent filter on a report Carlos is going to trust with
    commission questions is worse than no report.
    """
    rows = list(rows)
    tpv_seen = frozenset(norm_key(k) for k in (tpv_seen or ()))
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
            sub_statuses=tuple(sorted({
                (m.get("Contr. Sub-status") or "").strip()
                for m in members if (m.get("Contr. Sub-status") or "").strip()})),
        ))
        stats["collapsed_rows"] += len(members) - 1
        if not sale_date:
            stats["missing_sale_date"] += 1

    # Drop the ones that ended dead. Post-collapse so their history survives
    # on any sale that recovered — see DEAD_LEVELS.
    before = len(sales)
    sales = [s for s in sales if s.level not in DEAD_LEVELS]
    stats["dropped_dead"] = before - len(sales)

    # THE TPV GATE — drop deals that never reached TPV (Carlos, 2026-07-22).
    # A cancel/reject that never passed TPV was never a sale; Incomplete is
    # exempt. Post-collapse so a recovered deal's full history is available.
    before = len(sales)
    # Split the gate in two so the run log can distinguish "this export proves
    # it's a sale" from "only our own memory does" — a rescue is exactly the
    # case a human may want to eyeball.
    by_export = [s for s in sales if _reached_tpv(s)]
    kept_keys = {s.key for s in by_export}
    rescued = [s for s in sales
               if s.key not in kept_keys and norm_key(s.key) in tpv_seen]
    sales = by_export + rescued
    stats["rescued_by_tpv_memory"] = len(rescued)
    stats["dropped_never_reached_tpv"] = before - len(sales)

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


# The team ALLEXP export carries every office; this column slices it to one office
# (same "Owner & Office" field the churn/activation views filter on). Carlos's
# legacy CarlosOrderLog view is already single-office and has no such column, so
# the filter is applied ONLY when an owner_office is passed (per-office runs).
OWNER_OFFICE_COL = "Owner & Office"


def _norm_owner(s: str) -> str:
    """Whitespace-collapsed, case-folded — tolerant of stray \\r / casing so an
    onboarded office's stored value matches the export without being fragile."""
    return " ".join((s or "").split()).casefold()


def filter_to_owner(rows: List[Dict[str, str]], owner_office: str) -> List[Dict[str, str]]:
    """Keep only the rows for `owner_office`. Raises if the export lacks the
    Owner & Office column (wrong view) rather than silently returning nothing."""
    rows = list(rows)
    if not rows:
        return rows
    if OWNER_OFFICE_COL not in rows[0]:
        raise KeyError(
            "crosstab has no {!r} column — a per-office run needs the team "
            "ALLEXP order-log view, not a single-office view".format(OWNER_OFFICE_COL))
    want = _norm_owner(owner_office)
    return [r for r in rows if _norm_owner(r.get(OWNER_OFFICE_COL, "")) == want]


def load(path: Path, owner_office: str = "",
         tpv_seen=frozenset()) -> Tuple[List[Sale], Dict[str, int]]:
    """Read the crosstab into Sales. When `owner_office` is given, first slice the
    (team) export to that office — the SAME isolation the B2B metric views use.

    `tpv_seen`: sale keys already known to have reached TPV on an earlier pull
    (see THE TPV MEMORY). Empty by default, which is exactly the old behaviour.
    """
    rows = read_rows(Path(path))
    if owner_office:
        rows = filter_to_owner(rows, owner_office)
    return collapse(rows, tpv_seen=tpv_seen)
