"""Which offices get the Sunday Weekly Knock Dispositions board.

TWO SOURCES, ONE GATE (Megan 2026-08-22):

  * Raf's office — the explicit RAF row below. Live first, alone.
  * Every office ALREADY enrolled for the daily Knocks/Time-Gaps board in
    its metrics thread — DERIVED from office_metrics' declarative table
    (the same SECTION_OVERRIDES → onboarding-subset → default-all logic the
    runner applies), so an office that enrolls later auto-appears here with
    its channel, header label, and ownerville name. No second list to
    maintain.

  INCLUDE_ENROLLED is the go-live gate: False until Raf says take it live
  (flip it — or set WKD_INCLUDE_ENROLLED=1 to test the derivation). While
  False, enabled() returns only the RAF row.

Row fields (the explicit row and derived rows share this shape):
  name             ownerville office name (impersonation + alias lookup) —
                   for derived rows this is knocks_office, same as the
                   daily knocks scrape uses.
  ov               "master" (Raf: the rhidalgo login IS office 11280) or
                   "impersonate".
  campaign_id      TeleMapper campaign pin (sticky-campaign guard); "3" =
                   RES AT&T. Empty for NDS offices (no fiber campaign).
  pss_owner        Owner Name to slice from the D2D PSS crosstab; None =
                   apps not wired for this office (NDS offices — their
                   sales live in the NDS workbook, not DailyRepBDreportpull)
                   → apps columns render blank + the post is flagged.
  channel_id/channel_name/header_label
                   where this office's Sunday Metrics thread lives; empty
                   channel_id = the default #alphalete-sales.
  slack_token_file cross-workspace bot token file (trang) — posting with it
                   is NOT wired here yet; run.py skips such offices loudly.
"""
from __future__ import annotations

import os

INCLUDE_ENROLLED = True     # Raf's go-wide, 2026-08-22: "for everyone
                            # else's metrics thread, let's go ahead and do
                            # this for them on Sunday"

RAF = {
    "name": "Rafael Hidalgo", "ov": "master", "campaign_id": "3",
    "pss_owner": "Rafael Hidalgo",
    "channel_id": "", "channel_name": "#alphalete-sales",
    "header_label": "", "slack_token_file": "",
}

# Chan Park has no metrics thread of his own (his daily knocks ride the
# 'Knocks for other offices' thread) — Raf 2026-08-22: "can we also do Chan
# in there" → his weekly board posts into the SAME #alphalete-sales Metrics
# thread as Raf's. Empty channel_id = the default channel.
CHAN = {
    "name": "Chan Park", "ov": "impersonate", "campaign_id": "3",
    "pss_owner": "Chan Park",
    "channel_id": "", "channel_name": "#alphalete-sales",
    "header_label": "", "slack_token_file": "",
}

# Both spellings of the enrollment key resolve to the knocks/gaps board
# (runner's OWNER_KEY_TO_SLUG maps "knocks" → "knocks_gaps").
_KG = {"knocks", "knocks_gaps"}

# Enrolled offices EXCLUDED from this report by name (office_metrics keys).
# drew: Precision Management is reworking their Slack workspace (Megan
# 2026-08-22) — back in by deleting the line once they've settled.
_EXCLUDED_KEYS = {"drew"}


def enrolled_offices() -> list[dict]:
    """WKD rows for every office whose metrics thread already carries the
    Knocks/Time-Gaps board — mirrors the runner's section resolution:
    a committed SECTION_OVERRIDES entry wins (empty = posts nothing), else
    an onboarding subset, else the default = every board (which includes
    knocks_gaps)."""
    from automations.office_metrics import offices as OM
    out: list[dict] = []
    for key, o in OM.OFFICES.items():
        if key in _EXCLUDED_KEYS:
            continue
        if key in OM.SECTION_OVERRIDES:
            has_kg = bool(_KG & {str(s) for s in OM.SECTION_OVERRIDES[key]})
        else:
            enrolled = (OM.ONBOARDED_EXTRA.get(key, {})
                        .get("enrolled_reports") or [])
            has_kg = (not enrolled) or bool(_KG & {str(s) for s in enrolled})
        if not has_kg:
            continue
        nds = bool(getattr(o, "nds", False)) or key in OM.NDS_OFFICES
        out.append({
            "name": o.knocks_office or o.owner,
            "ov": "impersonate",
            "campaign_id": "" if nds else "3",
            # NDS sales live in the NDS workbook, not the D2D PSS this
            # report pulls — apps stay blank + flagged until that's wired.
            "pss_owner": None if nds else o.owner,
            "channel_id": o.channel_id,
            "channel_name": o.channel_name,
            "header_label": o.header_label,
            "slack_token_file": (
                o.slack_token_file
                or OM.CROSS_WS_TOKEN_FILES.get(key, "")),
        })
    return out


def all_offices() -> list[dict]:
    include = (INCLUDE_ENROLLED
               or os.environ.get("WKD_INCLUDE_ENROLLED", "") == "1")
    rows = [dict(RAF), dict(CHAN)]
    if include:
        seen = {r["name"].lower() for r in rows}
        for r in enrolled_offices():
            if r["name"].lower() in seen:
                continue
            seen.add(r["name"].lower())
            rows.append(r)
    return rows


def enabled(only: list[str] | None = None) -> list[dict]:
    """The offices this run covers. `only` (from --office) filters by name,
    case-insensitively — an unknown name is a loud error, not a silent
    skip."""
    rows = all_offices()
    if not only:
        return rows
    by_name = {r["name"].lower(): r for r in rows}
    out, unknown = [], []
    for w in only:
        row = by_name.get(w.lower())
        (out.append(row) if row else unknown.append(w))
    if unknown:
        raise SystemExit(
            f"Unknown office(s) {unknown} — not in the active set "
            f"{[r['name'] for r in rows]}. (Enrolled offices join the set "
            "when INCLUDE_ENROLLED / WKD_INCLUDE_ENROLLED=1 is on.)")
    return out
