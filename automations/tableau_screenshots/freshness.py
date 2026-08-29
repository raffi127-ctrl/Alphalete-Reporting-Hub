"""Is the Tableau extract behind each country tracker actually refreshed today?

WHY THIS EXISTS (Megan 2026-07-29): "trackers were sent out today without being
updated and we ran them anyway — I thought we had a guard set up for that?" We
didn't. Only B2B Box had a real gate (`tableau:box_daily`, the ~7am catch-up).
The 4:31am run carried `data_sources: []`, and an EMPTY data_sources list makes
day_orchestrator.readiness.report_ready() check Tableau SESSION WARMTH and then
return "all sources ready" — so nothing whatsoever gated the boards on data
freshness. Whatever Tableau rendered at 4:31 got photographed and posted.

WHAT IT CHECKS. Not the picture — the DATA behind the picture. These boards are
captured as images (Download → Image), so there is no crosstab in the run to
inspect. We ask each board's own view how far its data reaches, and hold the
board when that is short of the latest COMPLETED reporting day. A board whose
data stops the day before that is showing yesterday's numbers.

Still a proxy in one respect, and worth knowing: this proves the DATA is current,
not that the rendered image displays it. A view that silently renders the wrong
week would still pass. Nothing here reads the PNG.

ASK THE WORKBOOK, DON'T INFER (rewritten 2026-08-26). Every one of these views
publishes its own refresh status on a crosstab sheet, and that is what we read:

  tableau:tracker_att      D2D1-PAGERV4          "Last Refresh (2)"
  tableau:tracker_nds      NDSDailyTracker       "zzz Last Refresh (5)"
  tableau:tracker_b2b      D2D1-PAGERV3          "Last Refresh (2)"
  tableau:tracker_quantum  LumenSalesTracker     "Last Update"

  Last Server Update: 2026-08-26 08:11 ETData Source Sales Date Range: 2024-06-17  -  2026-08-25
  Last SFDC Object Update: 8/25/2026 | Latest Activities Data Update: 8/24/2026

Gate on the DATA COVERAGE field, never the server-update stamp: a refresh can run
on schedule and load nothing, and then the stamp says today while the data still
stops yesterday. Which field that is differs per workbook and is named in the
config — quantum's two fields differed by exactly the day in question on 8/26,
and the wrong one would have passed the morning that failed.

WHY THIS REPLACED THE OLD DESIGN. Until 8/26 each extract probed a STAND-IN view
(FIBER_SPEC / NDS_SPEC / B2B_SPEC — crosstabs org_sales_board already pulled) and
asked "does any row carry yesterday's date?", on the reasoning that a refresh is
workbook-wide. Two holes, both real:
  - it never looked at the view it photographs, so a pager showing the wrong week
    was invisible to it; and
  - "yesterday exists" is not "yesterday is finished" — one row satisfies it, so
    a half-loaded day reads exactly like a complete one.
The crosstab path below is KEPT for a future board whose workbook publishes no
such sheet; nothing uses it today.

NOT GATED, on purpose:
  b2b_box        already gated — `tableau:box_daily` on the ~7am catch-up.
  vzftr          email-sourced (an .xlsx), gated by run.py's _gate_email_sources.

Run `--discover <board_id>` to list a view's real crosstab sheet names before
assuming a board can't be gated — that is how all four above were found.

FAIL-OPEN, ALWAYS. Megan's standing rule is that a gate must never silently skip
a report. Past `fallback_hhmm` (06:30 — about two hours of circle-back after the
4:31 run), or on any probe error, the verdict is READY and the run goes ahead.
The belt-and-braces half of the guard lives in run.py: a board whose extract is
still stale when the run proceeds is HELD OUT of the thread and flagged, rather
than posted as though it were fresh (Megan's "fill-but-flag" / "flag unfilled
cells" rules). A held board is listed in the header as still coming and the next
later pass picks it up — the exact treatment Box already gets. WHICH pass that is
depends on the hour, and run._held_handoff_note reads it off the schedule rather
than promising a fixed "~7am": the 21:03 alert below named a catch-up that had
finished fourteen hours earlier, which reads to a channel as "handled".

SAMPLES ARE THE DAY'S, NOT THE MACHINE'S (2026-08-26 evening). The stability
check below needs two readings ten minutes apart, and they are shared across
runners through `stability_store` (a tab on the Mini Control workbook) as well as
the local file. Keeping them local meant every run on a machine that hadn't
sampled today opened with amnesia: the 21:03 onboarding run for
#alisei-b2b-sales, on Lucy 1 while the morning batch had been on Lucy 3, held 5
of 9 boards as "first sample of the day" — at nine at night, over data that
settled at 10:30 that morning. An unreachable sheet just means fewer samples,
which is the strict side, so the sharing can never post a board it shouldn't.

Verdict cache: READY verdicts only, same-day, so the orchestrator's 4:31 probe
and run.py's own check moments later cost ONE Tableau pull, not two. NOT-ready is
never cached — the orchestrator has to be able to re-probe on each pass, and an
extract that was fresh does not become stale (monotonic, matching ReadinessCache).

CLI (read-only, no Slack, no writes to any Sheet):
  python -m automations.tableau_screenshots.freshness            # today's verdicts
  python -m automations.tableau_screenshots.freshness --date 2026-07-29
  python -m automations.tableau_screenshots.freshness --discover quantum_fiber
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "tableau_screenshots"

# Same-day READY verdicts, shared between the orchestrator probe and run.py.
VERDICT_FILE = OUT_DIR / "_freshness.json"

# Boards this morning's run HELD because their extract was stale. Persisted so
# the ~7am --late-only catch-up knows to pick them up alongside Box, without
# re-probing (and without the morning's verdict having to survive in memory).
HELD_FILE = OUT_DIR / "_held_today.json"

# Default fail-open floor. The morning run is 4:31; past this the boards post
# regardless of what the probe says. Never skip — that is the whole rule.
DEFAULT_FALLBACK_HHMM = "06:30"


# extract id -> how to probe it + which boards ride on it.
#   spec        (module, attribute) of the org_sales_board ScrapeSpec to reuse.
#               Resolved lazily so importing this module stays cheap.
#   min_owners  row floor: fewer owners than this = a partial/garbage pull, not a
#               refreshed extract.
#   boards      pages.py ids covered by this extract.
EXTRACTS = {
    # Probed against D2D1-PAGERV4 — the view we photograph — not a stand-in
    # crosstab elsewhere in the workbook. Its "Last Refresh (2)" sheet reads
    #   Last Server Update: 2026-08-26 08:11 ETData Source Sales Date Range: 2024-06-17  -  2026-08-25
    # att_country_internet_only (D2D1-PAGERV2InternetOnly) is a different VIEW on
    # the same data source, so this one probe still covers both boards — but it
    # is now a pager view's own refresh sheet rather than an unrelated summary.
    "tableau:tracker_att": {
        "label": "ATTTRACKER2_1-D2D extract (AT&T Country trackers)",
        "stable_total": {
            "view_url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                         "ATTTRACKER2_1-D2D/D2D1-PAGERV4?:iid=1"),
            "sheet": "Summary Product by Day",
            "min_total": 1,
        },
        "fallback_hhmm": DEFAULT_FALLBACK_HHMM,
        "boards": ["att_country", "att_country_internet_only"],
    },
    # Probed against the NDS Daily Tracker view ITSELF — the view we photograph —
    # rather than a stand-in crosstab off the same workbook. Its "zzz Last
    # Refresh (5)" sheet publishes the data's own coverage:
    #   Last Server Update: 2026-08-26 07:46 ET
    #   Data Source Sales Date Range: 2024-06-17  -  2026-08-25
    # Gate on the RANGE END, not the server-update stamp: a refresh can run on
    # schedule and load nothing, and then the stamp says today while the data
    # still stops yesterday. The range is what the board actually has.
    "tableau:tracker_nds": {
        "label": "NDS-SNRES-ATT-OOFWorkbook extract (NDS Tracker)",
        "stable_total": {
            "view_url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                         "NDS-SNRES-ATT-OOFWorkbook/NDSDailyTracker?:iid=1"),
            "sheet": "New/Port/Air",
            "min_total": 1,
        },
        "fallback_hhmm": DEFAULT_FALLBACK_HHMM,
        "boards": ["nds"],
    },
    # Same treatment, against the B2B pager we photograph.
    "tableau:tracker_b2b": {
        "label": "ATTTRACKER-B2B extract (B2B AT&T trackers)",
        "stable_total": {
            "view_url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                         "ATTTRACKER-B2B/D2D1-PAGERV3/"
                         "87ae0671-15de-4d80-bdc0-702d0946dd1d/"
                         "B2BLeaderRecognition?:iid=1"),
            "sheet": "Summary Product by Day",
            "min_total": 1,
        },
        "fallback_hhmm": DEFAULT_FALLBACK_HHMM,
        "boards": ["b2b_att_country", "b2b_att_country_cru",
                   "b2b_d2d_consolidated", "order_tiered_bonus"],
    },
    # The one board that DOESN'T need a sale-date proxy: this workbook publishes
    # its own refresh status on a "Last Update" sheet, e.g.
    #   Last SFDC Object Update: 8/25/2026 | Latest Activities Data Update: 8/24/2026
    # That is the workbook telling us, in words, which day its data actually
    # reaches — no owner floor, no max-date inference, no guessing which
    # worksheet stands in for the picture. On 2026-08-26 it read 8/24 while we
    # photographed it as Tuesday's board and sent it to 15 channels; Tuesday
    # rendered as 0 sales (-100% vs both baselines) because Tuesday genuinely
    # wasn't loaded. Nothing read that sheet, so nothing objected.
    "tableau:tracker_quantum": {
        "label": "RES-LumenSalesTrackervMZ extract (ATT Quantum Fiber tracker)",
        "last_update": {
            "view_url": ("https://us-east-1.online.tableau.com/#/site/sci/views/"
                         "RES-LumenSalesTrackervMZ/LumenSalesTracker?:iid=2"),
            "sheet": "Last Update",
            # Gate on the ACTIVITIES date, not the SFDC one. The board's numbers
            # are activities; on 8/26 SFDC read 8/25 while activities read 8/24,
            # so gating on SFDC would have passed the exact morning that failed.
            "field": "Latest Activities Data Update",
        },
        # Still the WEAKER check: coverage, not stability. It caught 8/26 (the
        # workbook said 8/24 outright), but a partially-loaded quantum day would
        # pass it the way NDS/AT&T passed theirs. Upgrading needs a per-day sheet
        # off this view — `--discover quantum_fiber` lists the candidates.
        "fallback_hhmm": DEFAULT_FALLBACK_HHMM,
        "boards": ["quantum_fiber"],
    },
}

# Boards with no freshness gate, and why — surfaced by the CLI and the run summary
# so "ungated" is never mistaken for "checked and fine".
UNGATED = {
    "b2b_box": "already gated by tableau:box_daily on the ~7am catch-up",
    "vzftr": "email-sourced .xlsx — gated by run.py's _gate_email_sources",
}


def extract_for_board(board_id: str) -> Optional[str]:
    """The extract id gating `board_id`, or None when it has no gate."""
    for eid, e in EXTRACTS.items():
        if board_id in e["boards"]:
            return eid
    return None


def extracts_for_boards(board_ids) -> List[str]:
    """The extract ids needed to cover `board_ids`, in EXTRACTS order (stable, so
    the probe order — and the log — reads the same every morning)."""
    want = set(board_ids or ())
    return [eid for eid, e in EXTRACTS.items()
            if any(b in want for b in e["boards"])]


def _resolve_spec(extract_id: str):
    """The ScrapeSpec a crosstab-probed extract reuses. Not every extract has one
    — a `last_update` extract reads the workbook's own published date instead."""
    mod_name, attr = EXTRACTS[extract_id]["spec"]
    import importlib
    return getattr(importlib.import_module(mod_name), attr)


def target_day(today: dt.date) -> Optional[dt.date]:
    """The latest COMPLETED reporting day the extract must reach. Reuses the ORG
    Sales Board's own week logic (rollover-safe: Tue -> Mon, Mon -> last Sun,
    Sat -> Fri) so this gate and every other daily pull agree on what "yesterday"
    means. None when there is no completed day to gate on."""
    from automations.org_sales_board import week as _wk
    completed = _wk.completed_days(today)
    return max(completed) if completed else None


# ---------------- verdict cache (READY only, same day) ----------------

def _read_verdicts(today: dt.date) -> Dict[str, str]:
    try:
        data = json.loads(VERDICT_FILE.read_text())
    except Exception:                       # noqa: BLE001 — no cache yet is normal
        return {}
    if data.get("date") != today.isoformat():
        return {}
    return dict(data.get("ready") or {})


def _record_ready(today: dt.date, extract_id: str, reason: str) -> None:
    ready = _read_verdicts(today)
    ready[extract_id] = reason
    try:
        VERDICT_FILE.parent.mkdir(parents=True, exist_ok=True)
        VERDICT_FILE.write_text(json.dumps(
            {"date": today.isoformat(), "ready": ready}, indent=2))
    except Exception:                       # noqa: BLE001 — cache is an optimisation
        pass


# ---------------- the probe ----------------

# A date in either shape these sheets use: 8/25/2026 or 2026-08-25.
_DATE_TOKEN = r"(\d{1,2}/\d{1,2}/\d{4})|(\d{4}-\d{2}-\d{2})"
# Where one field's value ends: a separator, or the next "Some Label:". NDS runs
# two fields together with no separator at all ("...07:46 ETData Source Sales
# Date Range: ..."), so the label pattern is what actually bounds it.
_NEXT_FIELD = r"\||[A-Z][A-Za-z/ ]{3,40}\s*:"


def _read_crosstab_text(path: Path) -> str:
    """A Tableau crosstab as text, whatever encoding it came down in.

    These exports are UTF-16 with a BOM ('L\x00a\x00s\x00t\x00...'), which
    read as mojibake through utf-8. Decode by BOM, fall back to utf-8."""
    raw = Path(path).read_bytes()
    for enc in ("utf-16", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "\x00" not in text:
            return text
    return raw.decode("utf-8", errors="replace")


def parse_last_update(text: str, field: str) -> Optional[dt.date]:
    """The LATEST date `field` reports in a "Last Update"-style sheet, or None.

    Two real shapes, both live:
      quantum  Last SFDC Object Update: 8/25/2026 | Latest Activities Data Update: 8/24/2026
      nds      Last Server Update: 2026-08-26 07:46 ETData Source Sales Date Range: 2024-06-17  -  2026-08-25

    Which field matters is per-workbook (see the EXTRACTS entry) — they do NOT
    move together, and on 2026-08-26 the difference between quantum's two fields
    was exactly the difference between "gate passes" and "gate catches it".

    Reads only that field's OWN segment, bounded by the next label, because the
    fields sit on one line and a greedy scan would happily return a neighbour's
    date. Within the segment the MAX token wins, so a range ("2024-06-17 -
    2026-08-25") yields the end of the range, which is the coverage that matters."""
    import re
    m = re.search(re.escape(field) + r"\s*:", text or "", re.IGNORECASE)
    if not m:
        return None
    rest = (text or "")[m.end():]
    nxt = re.search(_NEXT_FIELD, rest)
    segment = rest[:nxt.start()] if nxt else rest
    found = []
    for us, iso in re.findall(_DATE_TOKEN, segment):
        try:
            if us:
                mth, day, yr = (int(x) for x in us.split("/"))
            else:
                yr, mth, day = (int(x) for x in iso.split("-"))
            found.append(dt.date(yr, mth, day))
        except (ValueError, TypeError):
            continue                        # an impossible date is not a date
    return max(found) if found else None


# Two observations of the same day's total, this far apart, both equal = the day
# has stopped loading. Shorter and a slow trickle reads as "settled" between two
# samples; much longer and nothing posts before mid-morning.
#
# 10, not 20 (Megan 2026-08-26). The cost of this gap is paid EVERY day, not just
# a bad one: the trackers run first in the orchestrator's order, so the first
# sample is the run's own, and the boards cannot post until a second one lands.
# 20 pushed a normal 4:11 thread to ~4:30. The failure this gate exists to catch
# was not a marginal one — NDS was still growing HOURS later (744 at 04:11,
# 1,075 at 10:30) — so 10 minutes discriminates just as well at half the delay.
# Raise it again only if something is seen trickling in under 10-minute steps.
STABILITY_GAP_MIN = 10

# Per-day totals seen so far today: {"date": iso, "obs": {extract: [[ts, total]]}}
# THIS MACHINE's copy. The samples that decide the verdict are these MERGED with
# every other runner's (stability_store) — see _read_stability.
STABILITY_FILE = OUT_DIR / "_stability.json"

# Also read/write today's samples to the shared Mini Control tab, so a run on any
# machine sees the history of every other one. Off = local file only, which is
# what shipped on 8/26 and what held five boards off #alisei-b2b-sales' first
# thread at 21:03 because the morning run had been on a different Lucy. Tests
# flip this; ops can use TRACKER_STABILITY_SHARED_OFF=1.
SHARED_SAMPLES = True

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def _num(cell: str) -> Optional[float]:
    """'1,075' -> 1075.0; '5%', '08/24 - 08/25', '' -> None."""
    t = (cell or "").strip().replace(",", "")
    if not t or "%" in t or "/" in t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_day_total(text: str, target: dt.date) -> Optional[float]:
    """The target day's grand total off a per-day crosstab, or None.

    Two real layouts, both live (verified 2026-08-26):

      att / b2b — "Summary Product by Day": the day is a COLUMN.
        Product Type ... | Mon (08-24) | Tue (08-25) | Total
        Grand Total      | 1,310       | 1,413

      nds — "New/Port/Air": the day is a ROW, keyed by weekday name.
        Tuesday | 08/24 - 08/25 | 1,075 | 5% | ...

    Neither sheet carries TODAY (nds leaves Wednesday..Sunday blank), which is
    what makes this usable as a stability signal — today's live accumulation
    would otherwise keep the number moving all day and nothing would ever settle."""
    rows = [r.split("\t") for r in (text or "").splitlines() if r.strip()]
    if not rows:
        return None
    # Layout 1: a header cell naming the target day -> read that column's total.
    stamp_dash = target.strftime("%m-%d")
    stamp_slash = target.strftime("%m/%d")
    for row in rows:
        col = next((i for i, c in enumerate(row)
                    if stamp_dash in (c or "") or stamp_slash in (c or "")), None)
        if col is None:
            continue
        for r2 in rows:
            head = (r2[0] if r2 else "").strip().lower()
            if head in ("grand total", "total") and len(r2) > col:
                val = _num(r2[col])
                if val is not None:
                    return val
        break
    # Layout 2: a row keyed by the target weekday -> its first numeric cell.
    want = _WEEKDAYS[target.weekday()].lower()
    for row in rows:
        if (row[0] if row else "").strip().lower() != want:
            continue
        for cell in row[1:]:
            val = _num(cell)
            if val is not None:
                return val
    return None


# A day that is a small fraction of its OWN week's other business days did not
# finish loading, however settled the number looks. 0.5 because real day-to-day
# variation lives well above it — the six Fridays before 2026-08-29 ran 139-215
# against ~180 midweek — while the failure it exists to catch came in at 0.27
# (NDS) and 0.12 (Quantum).
WEEKDAY_FLOOR_FRAC = 0.5

# Baseline days needed before the floor may fire. 2 keeps Monday and Tuesday
# targets out of it: one prior day is an anecdote, not a baseline.
MIN_BASELINE_DAYS = 2


def week_baseline_totals(text: str, target: dt.date) -> Dict[dt.date, float]:
    """{date: grand total} for the BUSINESS days of target's week BEFORE it, read
    off the very same crosstab.

    No extra pull and no stored history: both live layouts already carry the
    whole week (Mon..Sun), which is the only reason a relative floor is possible
    here at all. The sheets hold ONE week, so a trailing 4-week same-weekday
    average — the textbook baseline — is simply not available to this probe.
    A zero or unreadable day is dropped rather than counted: Sunday reads 0 on
    every one of these sheets, and averaging that in would sink the median."""
    out: Dict[dt.date, float] = {}
    monday = target - dt.timedelta(days=target.weekday())
    for i in range(target.weekday()):        # Mon .. the day before target
        d = monday + dt.timedelta(days=i)
        if d.weekday() >= 5:                 # Sat/Sun are legitimately near-zero
            continue
        try:
            val = parse_day_total(text, d)
        except Exception:                    # noqa: BLE001 — one odd column
            continue
        if val:                              # None and 0.0 both carry no signal
            out[d] = val
    return out


def volume_shortfall(text: str, target: dt.date, total: float, *,
                     frac: float = WEEKDAY_FLOOR_FRAC,
                     min_days: int = MIN_BASELINE_DAYS) -> Optional[str]:
    """Why `total` is too small to be a FINISHED day, or None to allow it.

    WHY THIS EXISTS (2026-08-29). The stability test above asks only whether the
    number STOPPED MOVING, which is not the same question as whether the day is
    complete — and it fails in the worst possible direction: the longer a feed
    stays broken, the more confident the "finished loading" verdict gets. That
    morning NDS Friday sat at 280 against Mon-Thu of ~1,050 from 04:01 to 08:52,
    and all three runners independently agreed it was settled ("unchanged for
    289m"). Nothing in the gate asked whether 280 was a PLAUSIBLE Friday. The
    boards went to sixteen channels showing a -70% day that never happened.

    So this asks the other half of the question: is the number believable next to
    the rest of its own week? Deliberately conservative — it may only ever fire
    on a landslide, because a false HOLD costs a morning's boards:
      * weekday targets only — Sat/Sun are genuinely tiny, not broken;
      * needs `min_days` real baseline days, so Mon/Tue never trip on thin
        evidence and a fresh week is never judged on one number;
      * compares against the MEDIAN, so a single monster or dead day can't move
        the bar;
      * silent on any parse trouble. An unreadable week is not evidence of a bad
        one — same fail-open rule as everywhere else in this module.

    The message ends in "extract not refreshed" deliberately: that substring is
    what `stale_boards` matches to actually HOLD a board rather than merely note
    it. Reword it and the boards post anyway."""
    if target.weekday() >= 5:
        return None
    base = week_baseline_totals(text, target)
    if len(base) < min_days:
        return None
    vals = sorted(base.values())
    mid = len(vals) // 2
    median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
    if median <= 0 or total >= frac * median:
        return None
    return ("%s = %g is only %.0f%% of this week's Mon-%s median of %g — the day "
            "is still part-loaded — extract not refreshed"
            % (target.isoformat(), total, 100.0 * total / median,
               _WEEKDAYS[max(base).weekday()][:3], median))


def _read_local_stability(today: dt.date) -> Dict[str, list]:
    """Just this machine's file."""
    try:
        data = json.loads(STABILITY_FILE.read_text())
    except Exception:                       # noqa: BLE001 — no file yet is normal
        return {}
    if data.get("date") != today.isoformat():
        return {}                           # yesterday's samples prove nothing
    return dict(data.get("obs") or {})


def _read_stability(today: dt.date) -> Dict[str, list]:
    """Today's samples from EVERY runner: this machine's file merged with the
    shared tab. A run on a machine that hasn't sampled today is the normal case,
    not the exception — an onboarding, a one-off, a report that moved Lucys — and
    on its own history it can only ever conclude "first sample of the day"."""
    local = _read_local_stability(today)
    if not SHARED_SAMPLES:
        return local
    try:
        from automations.tableau_screenshots import stability_store as _store
        return _store.merge(local, _store.read_today(today))
    except Exception:                       # noqa: BLE001 — shared read is a bonus
        return local


def _record_observation(today: dt.date, extract_id: str, total: float) -> list:
    """Record this reading in both stores; return the merged series for the
    verdict, oldest first."""
    at = dt.datetime.now().isoformat(timespec="seconds")
    local = _read_local_stability(today)
    series = list(local.get(extract_id) or [])
    series.append([at, total])
    local[extract_id] = series[-10:]        # a short tail is all the verdict needs
    try:
        STABILITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        STABILITY_FILE.write_text(json.dumps(
            {"date": today.isoformat(), "obs": local}, indent=2))
    except Exception:                       # noqa: BLE001 — cache is best-effort
        pass
    if SHARED_SAMPLES:
        try:
            from automations.tableau_screenshots import stability_store as _store
            _store.record(today, extract_id, at, total)
        except Exception:                   # noqa: BLE001 — publishing is a bonus
            pass
    # Re-read through the merged view: the local file already holds the sample we
    # just wrote, so this returns the day's full history either way — with every
    # other machine's readings when the shared tab is reachable, without them
    # when it isn't.
    return _read_stability(today).get(extract_id) or series


def _check_stable_total(extract_id: str, cfg: dict, target: dt.date,
                        today: dt.date, *, page=None,
                        log=lambda m: None) -> Tuple[bool, str]:
    """(fresh, reason) for "has yesterday STOPPED loading?".

    WHY THIS EXISTS (2026-08-26). Every earlier gate asked whether yesterday was
    PRESENT. It was — partially. The 4:11am boards went out with NDS Tuesday at
    744 and AT&T Tuesday at 1,118; by 10:30 the same days read 1,075 (+44%) and
    1,413 (+26%). Both gates passed all morning because a third of a day and a
    whole day look identical to a max-date test.

    So: sample the day's total, and only call it done when two samples
    STABILITY_GAP_MIN apart agree. A day still growing is not a day you can post.

    A zero/absent total is never "stable" — otherwise a board whose day never
    loaded (quantum on 8/26, 0 sales, -100%) would sail through on two matching
    zeros. Unreadable is never stale: fail open, as everywhere here."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    conf = cfg["stable_total"]
    out = OUT_DIR / "_freshness" / ("%s_day.csv" % extract_id.replace(":", "_"))
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        path = download_crosstab_patchright(
            conf["view_url"], conf["sheet"], out, verbose=False, page=page)
    except Exception as e:                  # noqa: BLE001 — not pullable yet
        line = str(e).splitlines()[0][:120] if str(e) else repr(e)
        return True, "day-total sheet not pullable (%s) — not held" % line
    text = _read_crosstab_text(Path(path))
    total = parse_day_total(text, target)
    if total is None:
        return True, ("could not read %s's total off %r — not held (the sheet's "
                      "layout may have changed)" % (target.isoformat(),
                                                    conf["sheet"]))
    floor = float(conf.get("min_total", 1))
    if total < floor:
        return False, ("%s shows %g — the day hasn't loaded yet — extract not "
                       "refreshed" % (target.isoformat(), total))
    series = _record_observation(today, extract_id, total)
    log("%s total for %s = %g (sample %d of today, all machines)"
        % (conf["sheet"], target.isoformat(), total, len(series)))
    # A number that has stopped moving still has to be a BELIEVABLE day. Checked
    # AFTER the sample is recorded so the day's history stays continuous whether
    # this holds or not — the run that finally sees good data still needs the
    # earlier samples to prove the number settled.
    try:
        short = volume_shortfall(
            text, target, total,
            frac=float(conf.get("weekday_floor_frac", WEEKDAY_FLOOR_FRAC)))
    except Exception:                        # noqa: BLE001 — a floor bug must
        short = None                         # never break the gate
    if short:
        return False, short
    if len(series) < 2:
        return False, ("%s = %g, first sample of the day — no proof it has "
                       "finished loading — extract not refreshed"
                       % (target.isoformat(), total))
    # HOW LONG HAS IT READ THIS? Walk back while the value is unchanged; the
    # earliest sample in that run is when the number stopped moving. Deliberately
    # NOT "compare the last two": with samples merged across machines the last
    # two can be seconds apart (two runners probing at once) while a sample from
    # this morning already proves the day settled hours ago. The old pairwise
    # test threw that proof away and reported "only 0m apart".
    t_now, v_now = series[-1]
    since = t_now
    differing = None                        # newest sample that read something else
    for at, val in reversed(series[:-1]):
        if val != v_now:
            differing = (at, val)
            break
        since = at
    age = _minutes_between(since, t_now)
    if age >= STABILITY_GAP_MIN:
        return True, ("%s = %g, unchanged for %.0fm — finished loading"
                      % (target.isoformat(), v_now, age))
    if differing:
        return False, ("%s grew %g -> %g since %s — still loading — extract not "
                       "refreshed" % (target.isoformat(), differing[1], v_now,
                                      str(differing[0])[11:16]))
    return False, ("%s = %g unchanged, but only %.0fm apart (need %dm) — "
                   "extract not refreshed" % (target.isoformat(), v_now, age,
                                              STABILITY_GAP_MIN))


def _minutes_between(earlier_iso: str, later_iso: str) -> float:
    """Minutes between two sample stamps. An unreadable stamp counts as a FULL
    gap: the samples are real readings either way, and the alternative — treating
    a parse slip as "0 minutes apart" — holds a board over a formatting bug."""
    try:
        return (dt.datetime.fromisoformat(later_iso)
                - dt.datetime.fromisoformat(earlier_iso)).total_seconds() / 60.0
    except Exception:                       # noqa: BLE001
        return float(STABILITY_GAP_MIN)


def _check_last_update(extract_id: str, cfg: dict, target: dt.date, *,
                       page=None, log=lambda m: None) -> Tuple[bool, str]:
    """(fresh, reason) for a workbook that PUBLISHES its own refresh date.

    Strictly better than the sale-date proxy the other extracts use: it asks the
    workbook which day its data reaches instead of inferring it from whether any
    row happens to carry yesterday's date. A workbook that says 8/24 on the 26th
    is behind, full stop — no owner floor, no partial-day ambiguity.

    Unreadable/unparseable is NOT stale (same rule as everywhere here): a probe
    that can't read must never hold a board that may be perfectly fine."""
    from automations.shared.tableau_patchright import download_crosstab_patchright
    conf = cfg["last_update"]
    field = conf.get("field", "Latest Activities Data Update")
    out = OUT_DIR / "_freshness" / ("%s.csv" % extract_id.replace(":", "_"))
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        path = download_crosstab_patchright(
            conf["view_url"], conf["sheet"], out, verbose=False, page=page)
    except Exception as e:                  # noqa: BLE001 — not pullable yet
        line = str(e).splitlines()[0][:120] if str(e) else repr(e)
        return True, "last-update sheet not pullable (%s) — not held" % line
    text = _read_crosstab_text(Path(path))
    got = parse_last_update(text, field)
    if got is None:
        return True, ("%r not found on the %r sheet — not held (the sheet's "
                      "wording may have changed)" % (field, conf["sheet"]))
    log("%s reports %s = %s" % (conf["sheet"], field, got.isoformat()))
    if got >= target:
        return True, "%s reaches %s (need >= %s)" % (field, got.isoformat(),
                                                     target.isoformat())
    return False, ("%s only reaches %s, need %s — extract not refreshed"
                   % (field, got.isoformat(), target.isoformat()))


def check_extract(extract_id: str, today: Optional[dt.date] = None, *,
                  page=None, verbose: bool = True,
                  use_cache: bool = True) -> Tuple[bool, str]:
    """(fresh, reason) for ONE extract. Pulls the reused daily crosstab and
    confirms its max date reaches the latest completed reporting day, with an
    owner-count floor. NO fail-open floor here — this is the raw data answer;
    the floor is applied by extract_ready() (orchestrator gate) and by run.py's
    board-level hold, which need it in different places.

    `page` reuses a live patchright session when the caller already has one; when
    None the downloader opens and closes its own."""
    today = today or dt.date.today()
    if extract_id not in EXTRACTS:
        return False, "unknown extract id %r" % (extract_id,)
    cfg = EXTRACTS[extract_id]

    if use_cache:
        cached = _read_verdicts(today).get(extract_id)
        if cached:
            return True, "%s (cached earlier today)" % cached

    target = target_day(today)
    if target is None:
        return True, "no completed reporting day to gate on"

    log = (lambda m: print("   %s" % m, flush=True)) if verbose else (lambda m: None)

    # A workbook that publishes its own refresh date is asked directly; only the
    # rest need a sale-date proxy off a stand-in worksheet.
    if cfg.get("last_update"):
        ok, why = _check_last_update(extract_id, cfg, target, page=page, log=log)
        if ok and "not held" not in why:
            _record_ready(today, extract_id, why)
        return ok, why

    # "Has yesterday stopped loading?" — NOT cached as READY, because unlike a
    # coverage date this verdict is a claim about a moment: the day was still
    # enough to post at 07:10, which says nothing about 04:11.
    if cfg.get("stable_total"):
        return _check_stable_total(extract_id, cfg, target, today, page=page,
                                   log=log)

    try:
        from automations.org_sales_board import section_pull as _sp
    except Exception as e:                  # noqa: BLE001 — code problem, not data
        return False, "cannot import section_pull (%s)" % (e,)

    spec = _resolve_spec(extract_id)
    try:
        path = _sp.pull_section_byday(spec, OUT_DIR / "_freshness", page,
                                      logfn=log, today=today)
    except Exception as e:                  # noqa: BLE001 — not pullable yet
        line = str(e).splitlines()[0][:120] if str(e) else repr(e)
        return False, "extract not pullable yet (%s)" % line
    try:
        parsed = _sp.parse_crosstab_byday(spec, path, today)
    except Exception as e:                  # noqa: BLE001
        return False, "crosstab not parseable yet (%s)" % (str(e)[:100],)

    owners = [o for o, m in parsed.items() if m.get(spec.metric)]
    min_owners = int(cfg.get("min_owners", 3))
    if len(owners) < min_owners:
        return False, ("crosstab thin (%d owner(s) < %d floor) — extract not "
                       "refreshed" % (len(owners), min_owners))
    maxd = max(d for o in owners for d in parsed[o][spec.metric])
    if maxd >= target:
        reason = "fresh through %s (need >= %s)" % (maxd.isoformat(),
                                                    target.isoformat())
        _record_ready(today, extract_id, reason)
        return True, reason
    return False, ("only through %s, need %s — extract not refreshed"
                   % (maxd.isoformat(), target.isoformat()))


def _past_floor(fallback_hhmm: str, now: Optional[dt.datetime] = None) -> bool:
    """True once the local clock has passed the fail-open floor. A malformed
    floor string must never break the gate — treat it as 'not past'."""
    try:
        fb_h, fb_m = (int(x) for x in str(fallback_hhmm).split(":"))
    except Exception:                       # noqa: BLE001
        return False
    now = now or dt.datetime.now()
    return (now.hour, now.minute) >= (fb_h, fb_m)


def extract_ready(extract_id: str, today: Optional[dt.date] = None, *,
                  verbose: bool = False) -> Tuple[bool, str]:
    """(ready, reason) WITH the fail-open floor — what day_orchestrator's
    readiness probe calls. Past `fallback_hhmm` this always returns ready, so the
    gate can hold the run for a couple of hours but can never skip it."""
    today = today or dt.date.today()
    cfg = EXTRACTS.get(extract_id) or {}
    floor = str(cfg.get("fallback_hhmm", DEFAULT_FALLBACK_HHMM))
    if _past_floor(floor):
        return True, ("past %s fallback — running (a freshness gate never skips "
                      "the trackers; stale boards are held + flagged instead)" % floor)
    try:
        return check_extract(extract_id, today, verbose=verbose)
    except Exception as e:                  # noqa: BLE001 — never break the batch
        return True, ("probe error (%s: %s) — running" %
                      (type(e).__name__, str(e)[:80]))


# ---------------- board-level staleness (run.py's belt-and-braces) ----------------

def stale_boards(board_ids, today: Optional[dt.date] = None, *,
                 page=None, verbose: bool = True) -> Tuple[Dict[str, str],
                                                           Dict[str, str]]:
    """({board_id: why}, {extract_id: verdict}) for the boards in `board_ids`.

    Probes each covering extract ONCE. An ungated board is never stale (it has no
    gate to be stale against) and a probe ERROR is never stale either — a broken
    probe must not hold a board that might be perfectly fine. Only a confirmed
    "the extract has not reached the completed day" holds a board."""
    today = today or dt.date.today()
    stale: Dict[str, str] = {}
    verdicts: Dict[str, str] = {}
    for eid in extracts_for_boards(board_ids):
        try:
            ok, why = check_extract(eid, today, page=page, verbose=verbose)
        except Exception as e:              # noqa: BLE001 — fail open, never hold
            ok, why = True, "probe error (%s) — not held" % (type(e).__name__,)
        verdicts[eid] = ("FRESH — %s" if ok else "STALE — %s") % why
        if verbose:
            print("   %s %s: %s" % ("✓" if ok else "⚠",
                                    EXTRACTS[eid]["label"], why), flush=True)
        if ok:
            continue
        # An unpullable/unparseable extract is a PROBE failure, not proof the data
        # is stale — flagging it would hold boards on every Tableau flake.
        if "not refreshed" not in why and "thin" not in why:
            if verbose:
                print("     (probe could not read the extract — boards NOT held)",
                      flush=True)
            continue
        for b in EXTRACTS[eid]["boards"]:
            if b in set(board_ids or ()):
                stale[b] = why
    return stale, verdicts


# ---------------- held-board handoff to the ~7am catch-up ----------------

def write_held(today: dt.date, held: Dict[str, str]) -> None:
    """Record the boards this morning held for staleness, so --late-only picks
    them up with Box. Rewritten each morning; a stale file from yesterday is
    ignored on read (never resurrect a board off an old date)."""
    try:
        HELD_FILE.parent.mkdir(parents=True, exist_ok=True)
        HELD_FILE.write_text(json.dumps(
            {"date": today.isoformat(), "held": held}, indent=2))
    except Exception:                       # noqa: BLE001 — best effort
        pass


def read_held(today: dt.date) -> Dict[str, str]:
    """{board_id: why} held earlier TODAY (empty if none / a different day)."""
    try:
        data = json.loads(HELD_FILE.read_text())
    except Exception:                       # noqa: BLE001
        return {}
    if data.get("date") != today.isoformat():
        return {}
    return dict(data.get("held") or {})


# ---------------- worksheet discovery (for wiring quantum_fiber) ----------------

def discover(board_id: str, *, verbose: bool = True) -> List[str]:
    """List the crosstab worksheet names a board's view actually offers, so an
    ungated board can be wired without guessing. Needs a warm Tableau session —
    run it on the machine that owns the session, not from a laptop (a laptop
    scrape evicts the mini's session holder)."""
    from automations.tableau_screenshots import pages as pages_mod
    from automations.recruiting_report.opt_phase import list_crosstab_sheets
    spec = pages_mod.by_id(board_id)
    if spec is None:
        raise SystemExit("no tracker with id %r" % (board_id,))
    if not spec.get("url"):
        raise SystemExit("%s has no Tableau url (email-sourced?)" % (board_id,))
    names = list_crosstab_sheets(spec["url"], verbose=verbose)
    for n in names:
        print("   • %s" % (n,), flush=True)
    return names


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=None,
                    help="Check as of this date (YYYY-MM-DD) instead of today.")
    ap.add_argument("--discover", default=None, metavar="BOARD_ID",
                    help="List the crosstab worksheet names this board's view "
                         "offers, so an ungated board can be wired.")
    ap.add_argument("--no-cache", action="store_true",
                    help="Ignore today's cached READY verdicts and re-pull.")
    args = ap.parse_args(argv)

    if args.discover:
        discover(args.discover)
        return 0

    today = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
             if args.date else dt.date.today())
    target = target_day(today)
    print("Tracker freshness — %s (extract must reach %s)"
          % (today.isoformat(), target.isoformat() if target else "n/a"), flush=True)
    bad = 0
    for eid, e in EXTRACTS.items():
        ok, why = check_extract(eid, today, verbose=True,
                                use_cache=not args.no_cache)
        print("  %s %-24s %s" % ("✓" if ok else "⚠", eid, why), flush=True)
        print("     boards: %s" % ", ".join(e["boards"]), flush=True)
        print("     floor:  %s (past it: runs anyway)"
              % e.get("fallback_hhmm", DEFAULT_FALLBACK_HHMM), flush=True)
        if not ok:
            bad += 1
    print("\n  ungated boards:", flush=True)
    for b, why in UNGATED.items():
        print("   • %-12s %s" % (b, why), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
