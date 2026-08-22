"""The office table — one row per office the Sunday board goes out to.

Adding an office is ONE entry here (or the env override below), never a code
change elsewhere. Every field:

  name         Canonical ICD name (the ICD Aliases tab resolves spelling
               drift, both for Ownerville impersonation and the PSS owner
               match — so this is the ONLY name the row needs).
  ov           "master"      — the login account's own office; no
                               impersonation (Raf's office: the rhidalgo
                               login IS Alphalete Marketing 11280).
               "impersonate" — reach the office via Office Access (?p=901),
                               same helpers other_office_knocks uses.
  campaign_id  TeleMapper campaign to pin (invD2DClientId) before scraping —
               the sticky-campaign guard; a stale selection once returned 0
               rows for a day with 7 knocking reps. "3" = RES AT&T (fiber).

Env override (comma-separated canonical names, must exist in OFFICES):
    WEEKLY_KNOCK_DISPO_OFFICES="Rafael Hidalgo,Sahil Multani"
"""
from __future__ import annotations

import os

OFFICES: list[dict] = [
    {"name": "Rafael Hidalgo", "ov": "master", "campaign_id": "3"},
    # Next offices go here when Raf says fire — e.g.:
    # {"name": "Sahil Multani", "ov": "impersonate", "campaign_id": "3"},
]


def enabled(only: list[str] | None = None) -> list[dict]:
    """The offices this run covers. `only` (from --office) filters by name,
    case-insensitively, against the configured rows — an unknown name is a
    loud error, not a silent skip."""
    rows = OFFICES
    env = [o.strip() for o in
           os.environ.get("WEEKLY_KNOCK_DISPO_OFFICES", "").split(",")
           if o.strip()]
    want = only or env
    if not want:
        return rows
    by_name = {r["name"].lower(): r for r in rows}
    out, unknown = [], []
    for w in want:
        row = by_name.get(w.lower())
        (out.append(row) if row else unknown.append(w))
    if unknown:
        raise SystemExit(
            f"Unknown office(s) {unknown} — add them to "
            f"automations/weekly_knock_dispositions/offices.py first. "
            f"Configured: {[r['name'] for r in rows]}")
    return out
