"""Is the Tableau extract behind each country tracker actually refreshed today?

WHY THIS EXISTS (Megan 2026-07-29): "trackers were sent out today without being
updated and we ran them anyway — I thought we had a guard set up for that?" We
didn't. Only B2B Box had a real gate (`tableau:box_daily`, the ~7am catch-up).
The 4:31am run carried `data_sources: []`, and an EMPTY data_sources list makes
day_orchestrator.readiness.report_ready() check Tableau SESSION WARMTH and then
return "all sources ready" — so nothing whatsoever gated the boards on data
freshness. Whatever Tableau rendered at 4:31 got photographed and posted.

WHAT IT CHECKS. Not the picture — the EXTRACT behind the picture. These boards
are captured as images (Download → Image), so there is no crosstab in the run to
inspect. Instead we pull the same daily crosstab the ORG Sales Board already
pulls off each of those three workbooks and ask the only question that matters:
does the extract have rows for the latest COMPLETED reporting day? A board whose
extract stops at the day before that is showing yesterday's numbers.

ONE PROBE PER EXTRACT, NOT PER BOARD. Ten boards sit on three Tableau workbooks;
an extract refresh is workbook-wide, so three pulls cover eight boards:

  tableau:tracker_att   ATTTRACKER2_1-D2D          att_country,
                                                   att_country_internet_only
  tableau:tracker_nds   NDS-SNRES-ATT-OOFWorkbook  nds
  tableau:tracker_b2b   ATTTRACKER-B2B             b2b_att_country,
                                                   b2b_att_country_cru,
                                                   b2b_d2d_consolidated,
                                                   order_tiered_bonus

Each one REUSES a spec that org_sales_board already pulls successfully every
morning (FIBER_SPEC / NDS_SPEC / B2B_SPEC) — same workbook, proven view URL,
proven worksheet name, proven parser, week-pin and `:refresh=yes` included. That
matters: a probe pointed at a guessed worksheet name fails every morning, and a
gate that always errors is a gate that always fail-opens, i.e. no gate at all.

NOT GATED, on purpose:
  quantum_fiber  RES-LumenSalesTrackervMZ — nothing else in the repo reads this
                 workbook, so we have no verified crosstab worksheet name for it.
                 Wiring a guess would produce a permanently-erroring probe. Run
                 `python -m automations.tableau_screenshots.freshness --discover
                 quantum_fiber` on a machine with a warm session to list its real
                 worksheets, then add it below. Until then it posts as before.
  b2b_box        already gated — `tableau:box_daily` on the ~7am catch-up.
  vzftr          email-sourced (an .xlsx), gated by run.py's _gate_email_sources.

FAIL-OPEN, ALWAYS. Megan's standing rule is that a gate must never silently skip
a report. Past `fallback_hhmm` (06:30 — about two hours of circle-back after the
4:31 run), or on any probe error, the verdict is READY and the run goes ahead.
The belt-and-braces half of the guard lives in run.py: a board whose extract is
still stale when the run proceeds is HELD OUT of the thread and flagged, rather
than posted as though it were fresh (Megan's "fill-but-flag" / "flag unfilled
cells" rules). A held board is listed in the header as still coming and the ~7am
catch-up picks it up — the exact treatment Box already gets.

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
    "tableau:tracker_att": {
        "label": "ATTTRACKER2_1-D2D extract (AT&T Country trackers)",
        "spec": ("automations.org_sales_board.section_pull", "FIBER_SPEC"),
        "min_owners": 5,
        "fallback_hhmm": DEFAULT_FALLBACK_HHMM,
        "boards": ["att_country", "att_country_internet_only"],
    },
    "tableau:tracker_nds": {
        "label": "NDS-SNRES-ATT-OOFWorkbook extract (NDS Tracker)",
        "spec": ("automations.org_sales_board.section_pull", "NDS_SPEC"),
        "min_owners": 3,
        "fallback_hhmm": DEFAULT_FALLBACK_HHMM,
        "boards": ["nds"],
    },
    "tableau:tracker_b2b": {
        "label": "ATTTRACKER-B2B extract (B2B AT&T trackers)",
        "spec": ("automations.org_sales_board.section_pull", "B2B_SPEC"),
        "min_owners": 3,
        "fallback_hhmm": DEFAULT_FALLBACK_HHMM,
        "boards": ["b2b_att_country", "b2b_att_country_cru",
                   "b2b_d2d_consolidated", "order_tiered_bonus"],
    },
}

# Boards with no freshness gate, and why — surfaced by the CLI and the run summary
# so "ungated" is never mistaken for "checked and fine".
UNGATED = {
    "quantum_fiber": "RES-LumenSalesTrackervMZ has no verified crosstab worksheet "
                     "yet (run --discover quantum_fiber to wire it)",
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

    try:
        from automations.org_sales_board import section_pull as _sp
    except Exception as e:                  # noqa: BLE001 — code problem, not data
        return False, "cannot import section_pull (%s)" % (e,)

    spec = _resolve_spec(extract_id)
    log = (lambda m: print("   %s" % m, flush=True)) if verbose else (lambda m: None)
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
