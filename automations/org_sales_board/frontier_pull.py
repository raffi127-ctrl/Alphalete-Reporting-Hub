"""Frontier daily production for the Org Sales Board — automates the previously
hand-keyed Frontier section (1 ICD, Abel Draper) from the emailed Credico
'Daily Sales - Frontier - Events by Store' PDF. Mirrors je_pull: fetch -> parse
-> to_board_pull, consumed by orchestrate's _adapter_frontier.

Validated 2026-07-07 against the real emailed PDF + Abel's hand-keyed VA row:
the PDF's summed per-store dailies are ordered [Sun, Mon, Tue, Wed, Thu, Fri,
Sat] for the Frontier Saturday-ending week, and map 1:1 onto the board's Sun-Sat
Frontier section — matched EXACTLY (WE-Sat 7/11 -> board WE-Sun 7/12: Sun=2,
Mon=5, total=7). The section is Sun-Sat while the rest of the board is Mon-Sun
(per its header note).

Day-behind, like JE: Sunday's number posts Monday. Blank days = not posted yet.
to_board_pull returns the CURRENT Frontier week only, so a not-yet-posted week
never writes a stale week's numbers into this week's columns.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

from automations.alphalete_org_report import opt_frontier, frontier_email_source
from automations.alphalete_org_report.tableau_http import _norm_owner

ICD = "Abel Draper"
METRIC = "sales"
_BY_STORE = "by Store"          # which of the 3 Frontier globs is the daily one


def fetch(dest_dir: Optional[Path] = None, page=None) -> Optional[Path]:
    """Download the newest 'Daily Sales - Frontier - Events by Store' PDF from
    the reporting inbox. `page` is accepted + ignored (adapter parity — Frontier
    comes from email, not the Tableau session)."""
    dest = Path(dest_dir) if dest_dir else Path("output")
    dest.mkdir(parents=True, exist_ok=True)
    got = frontier_email_source.fetch(dest, verbose=False)
    return next((p for g, p in got.items() if _BY_STORE in g), None)


def parse(pdf_path: Path, today: Optional[dt.date] = None) -> dict:
    """Read the by-store PDF -> {we_sat: {'is_current': bool, 'days': {date:int}}}
    for Abel Draper, summing his stores per day. PDF day order = Sun..Sat for the
    Saturday-ending week."""
    out: dict = {}
    for pw in opt_frontier.parse_frontier_pdf(pdf_path, ICD):
        dailies = [st.daily for st in pw.rows if st.daily]
        if not dailies:
            continue
        per_day = [sum(x) for x in zip(*dailies)]          # sum across his stores
        sun = pw.we_sat - dt.timedelta(days=6)             # week starts Sunday
        days = {sun + dt.timedelta(days=i): v for i, v in enumerate(per_day)}
        out[pw.we_sat] = {"is_current": pw.is_current, "days": days}
    return out


def to_board_pull(parsed: dict, only_current: bool = True) -> dict:
    """parse() output -> the engine shape {owner_norm: {metric: {date: value}}}.
    Current Frontier week only by default; returns {} when the current week
    hasn't posted yet (day-behind) so no stale week is written."""
    if not parsed:
        return {}
    weeks = ([v for v in parsed.values() if v.get("is_current")] if only_current
             else list(parsed.values()))
    if not weeks:
        return {}
    days: dict = {}
    for w in weeks:
        days.update(w["days"])
    return {_norm_owner(ICD): {METRIC: days}}
