"""Today's tracker stability samples, shared by every MACHINE that runs them.

WHY THIS EXISTS (Megan 2026-08-26, same evening the gate shipped). The stability
gate asks "has yesterday STOPPED loading?" and answers it by comparing two
samples of the same day's total, STABILITY_GAP_MIN apart. Those samples lived in
`output/tableau_screenshots/_stability.json` — and `output/` is gitignored
per-machine scratch, so the history is only ever the history of ONE runner.

What that cost: the 21:03 tracker ONBOARDING run for #alisei-b2b-sales ran on
Lucy 1. The morning run had been on Lucy 3. Lucy 1 had no samples for the day, so
every gated extract came back "first sample of the day" and five of nine boards
were held — from a brand-new office's very first thread — while the data had been
settled since ~10:30 that morning (NDS 1,075, the same number the evening probe
read). Nothing was stale. The gate simply had amnesia about the other machine.

Any run that is not the machine that ran the morning batch hits this: a one-off,
an onboarding, a `--fresh` re-post from the laptop, a report moved between Lucys.
It can only pass by being run twice, ten minutes apart, which nobody does.

THE SUBSTRATE is the one place every runner already reaches: the Mini Control
workbook (`mini_control.CONTROL_SHEET_ID`) through
`recruiting_report.fill._client()` — gspread, any machine, already how the minis
take commands. Same choice, and the same reasoning, as
[[reference_lucy_machine_logins]]'s cross_machine_lock.

SHAPE — one row per observation, newest appended:

    Date       | Extract              | Observed At         | Total | Machine
    2026-08-26 | tableau:tracker_nds  | 2026-08-26T04:31:07 | 1075  | Lucy 3

Append-only, because an append always lands on its own row: two machines
sampling at once produce two rows, never one clobbered cell. Rows from earlier
days are dropped on the first read of a new day, so the tab stays small.

COST is ~1 read + 1 append per EXTRACT per run (4 extracts = ~5 calls), and the
read is memoized for the life of the process. That is the same order as the post
lock and well clear of the per-cell write loops that earn a 429 on this workbook
[[reference_sheets_write_quota_429]].

BEST-EFFORT, ALWAYS. Every failure path — no network, no credentials, a 429, a
malformed row — returns "nothing shared" and lets the caller fall back to its
local file. The failure this fixes is a board wrongly held; the failure it must
never cause is a board wrongly POSTED, and it cannot: an unreachable sheet can
only ever make the gate see FEWER samples, which is the strict side. Set
TRACKER_STABILITY_SHARED_OFF=1 to turn it off without a deploy.
"""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, List, Optional

TAB = "Tracker Stability"
HEADERS = ["Date", "Extract", "Observed At", "Total", "Machine"]

# Guard against an unbounded tab if pruning ever fails: read the tail only.
MAX_ROWS_READ = 2000


def disabled() -> bool:
    return os.environ.get("TRACKER_STABILITY_SHARED_OFF", "") not in ("", "0")


def _machine() -> str:
    """This runner's name, for a human reading the tab — never used in logic."""
    try:
        from automations.shared import hub_identity
        return hub_identity.machine_name()
    except Exception:                       # noqa: BLE001
        import socket
        try:
            return socket.gethostname()
        except Exception:                   # noqa: BLE001
            return "unknown"


def _ws():
    """The worksheet, created on first use. Raises — every caller treats any
    exception as 'nothing shared' and carries on with local samples."""
    import gspread

    from automations.day_orchestrator.mini_control import CONTROL_SHEET_ID
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        return sh.worksheet(TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=TAB, rows=1000, cols=len(HEADERS))
        ws.update([HEADERS], "A1")
        return ws


# Read once per process: the gate probes several extracts in one run and they all
# want the same day's history. A stale read within a run is harmless — the run's
# OWN samples are merged in locally by the caller.
_CACHE: Dict[str, Dict[str, list]] = {}


def read_today(today: dt.date) -> Optional[Dict[str, list]]:
    """{extract_id: [[observed_at_iso, total], …]} for `today`, oldest first.

    None means "the shared store said nothing" (off, unreachable, empty) — which
    the caller must treat as no extra history, never as an error."""
    if disabled():
        return None
    key = today.isoformat()
    if key in _CACHE:
        return _CACHE[key]
    try:
        rows = _ws().get_all_values()[-MAX_ROWS_READ:]
    except Exception:                       # noqa: BLE001 — no shared history
        return None
    out: Dict[str, list] = {}
    stale = False
    for row in rows:
        if len(row) < 4 or (row[0] or "").strip() == HEADERS[0]:
            continue
        date, extract, at, total = (c.strip() for c in row[:4])
        if date != key:
            stale = stale or bool(date)
            continue
        try:
            out.setdefault(extract, []).append([at, float(total)])
        except (TypeError, ValueError):     # a hand-edited row is not a sample
            continue
    for series in out.values():
        series.sort(key=lambda s: s[0])
    _CACHE[key] = out
    if stale:
        _prune(key)
    return out


def record(today: dt.date, extract_id: str, at_iso: str, total: float) -> None:
    """Append one observation. Best-effort: a failure here costs this machine's
    contribution to the shared history, never the run."""
    if disabled():
        return
    row = [today.isoformat(), extract_id, at_iso, repr(float(total)), _machine()]
    try:
        _ws().append_row(row, value_input_option="RAW")
    except Exception:                       # noqa: BLE001
        return
    # Keep the in-process view consistent with what we just wrote, so a second
    # extract probed later in the same run doesn't re-read to see it.
    day = _CACHE.setdefault(today.isoformat(), {})
    day.setdefault(extract_id, []).append([at_iso, float(total)])


def _prune(keep_date: str) -> None:
    """Drop rows from other days. Yesterday's totals prove nothing about today
    (freshness._read_stability already refuses them), so they are pure bulk."""
    try:
        ws = _ws()
        rows = ws.get_all_values()
        keep = [HEADERS] + [r for r in rows[1:]
                            if len(r) > 0 and (r[0] or "").strip() == keep_date]
        if len(keep) == len(rows):
            return
        ws.clear()
        ws.update(keep or [HEADERS], "A1")
    except Exception:                       # noqa: BLE001 — a big tab is survivable
        pass


def merge(local: Dict[str, list], shared: Optional[Dict[str, list]]
          ) -> Dict[str, list]:
    """Local samples + shared samples, de-duplicated, oldest first per extract.

    De-dupe on (timestamp, total): this machine writes every observation to BOTH
    stores, so its own samples come back from the shared read and would otherwise
    be counted twice — which would let two readings of one moment masquerade as
    two readings ten minutes apart."""
    out: Dict[str, list] = {}
    for src in (local or {}, shared or {}):
        for extract, series in src.items():
            bucket = out.setdefault(extract, [])
            for at, total in series:
                pair = [str(at), float(total)]
                if pair not in bucket:
                    bucket.append(pair)
    for series in out.values():
        series.sort(key=lambda s: s[0])
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """Read-only: today's shared samples, as the gate sees them."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)
    day = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    shared = read_today(day)
    if shared is None:
        print("shared store unavailable or off — local samples only")
        return 0
    if not shared:
        print("no shared samples for %s yet" % day.isoformat())
        return 0
    for extract in sorted(shared):
        print(extract)
        for at, total in shared[extract]:
            print("   %s  %g" % (at, total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
