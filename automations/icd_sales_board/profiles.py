"""One profile per ICD: what they sell, which metrics that earns them, and
whether they already have an automated feed.

The campaign assignment is NOT hand-maintained here — it is READ from the live
ORG Sales Board, because the board already is the answer. Every daily section is
a campaign, and an ICD having a row in that section is the board asserting the
ICD runs it. `refresh_from_board()` re-reads it and rewrites icd_profiles.json;
everything else in the repo reads the committed JSON so nothing needs Sheets
access at import time.

That means the map self-heals: put an ICD in a new section on the board, refresh,
and their profile (and therefore their metric list) follows. Nobody has to
remember that a new NDS owner shouldn't get internet boards.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from automations.icd_sales_board import campaigns as C

_FILE = Path(__file__).with_name("icd_profiles.json")


@dataclass(frozen=True)
class Profile:
    name: str                 # ICD name as the ORG board spells it
    sections: tuple           # org-board daily sections they appear in
    campaigns: tuple          # campaign keys
    families: tuple           # product families sold
    metrics: tuple            # metric slugs that MEAN something for them
    na_metrics: tuple         # slugs that do not apply (render nothing)
    office_key: str = ""      # office_metrics registry key, when they have a feed
    channel_name: str = ""    # where their daily thread posts today
    feed: bool = False        # do they have an automated daily-metrics feed?

    @property
    def is_wireless_only(self) -> bool:
        return set(self.families) == {C.WIRELESS}

    @property
    def primary_campaign(self) -> str:
        return self.campaigns[0] if self.campaigns else ""


def _build(name: str, sections: list, office_index: dict) -> Profile:
    keys = [C.BY_SECTION[s] for s in sections if s in C.BY_SECTION]
    o = office_index.get(_norm(name))
    return Profile(
        name=name,
        sections=tuple(sections),
        campaigns=tuple(keys),
        families=tuple(sorted(C.families_for(sections))),
        metrics=tuple(C.applicable_metrics(sections)),
        na_metrics=tuple(C.na_metrics(sections)),
        office_key=(o or {}).get("key", ""),
        channel_name=(o or {}).get("channel_name", ""),
        feed=bool(o),
    )


def _norm(n: str) -> str:
    return " ".join((n or "").split()).strip().lower()


def _office_index() -> dict:
    """office_metrics owners keyed by normalized name, so a profile can say
    whether this ICD already has an automated thread today."""
    try:
        from automations.office_metrics import offices as _off
    except Exception:
        return {}
    idx = {}
    for key, o in _off.OFFICES.items():
        idx[_norm(o.owner)] = {"key": key, "channel_name": o.channel_name}
    return idx


def load() -> dict:
    """{ICD name: Profile} from the committed JSON. No network."""
    if not _FILE.exists():
        return {}
    raw = json.loads(_FILE.read_text(encoding="utf-8"))
    office_index = _office_index()
    return {n: _build(n, secs, office_index)
            for n, secs in sorted(raw.get("per_icd", {}).items())}


def get(name: str):
    return load().get(name)


def refresh_from_board(*, tab: str = "", prune: bool = False) -> dict:
    """Re-read the live ORG Sales Board and rewrite icd_profiles.json.

    READ-ONLY against the sheet. Returns the new {name: sections} map.

    NEVER DROPS AN ICD SILENTLY. A section that is missing from the board on
    the day this runs — renamed, emptied, or simply not there yet — takes
    every ICD in it with it: the first refresh lost Abel Draper, whose office
    is the Frontier section, and losing him would have taken his board away
    with nothing said. Anyone in the old file who is not on the board today is
    KEPT and reported. `prune=True` is how an office that really has gone gets
    removed, on purpose."""
    from automations.org_sales_board.run import SHEET_ID, PROD_TAB
    from automations.org_sales_board import sources as S
    from automations.org_sales_board.fill_section import find_daily_section
    from automations.recruiting_report.fill import open_by_key

    grid = open_by_key(SHEET_ID).worksheet(tab or PROD_TAB).get_all_values()
    per_icd: dict[str, list] = {}
    sections: dict[str, list] = {}
    for src in S.DAILY_SOURCES:
        try:
            a = find_daily_section(grid, src.label)
        except ValueError:
            continue                      # section not on the board right now
        names = [n.strip() for n in a.icd_rows if n.strip()]
        sections[src.label] = names
        for n in names:
            per_icd.setdefault(n, []).append(src.label)

    # KEPT ACROSS A REFRESH. Some ICDs sell into Tableau without being a row
    # on the ORG board — Joseph Logan, Nii Tagoe, Steve McElwee and Trang
    # Canavan all had settled numbers stored and no way to be selected on the
    # site. They are listed in 'extra_icds' and merged back in here, so a
    # refresh brings the board up to date without dropping them again
    # (2026-09-22).
    extra = {}
    if _FILE.exists():
        try:
            extra = json.loads(_FILE.read_text()).get("extra_icds") or {}
        except (ValueError, OSError):
            extra = {}
    for name, secs in extra.items():
        if name not in per_icd:
            per_icd[name] = list(secs)
            for lab in secs:
                sections.setdefault(lab, []).append(name)

    # Anyone the board no longer shows: kept unless pruned, and handed back so
    # the caller can say who.
    previous = {}
    if _FILE.exists():
        try:
            previous = json.loads(_FILE.read_text()).get("per_icd") or {}
        except (ValueError, OSError):
            previous = {}
    missing = sorted(n for n in previous if n not in per_icd)
    if not prune:
        for name in missing:
            per_icd[name] = list(previous[name])
    refresh_from_board.missing = missing

    _FILE.write_text(json.dumps(
        {"source_tab": tab or PROD_TAB, "sections": sections,
         "extra_icds": dict(sorted(extra.items())),
         "per_icd": dict(sorted(per_icd.items()))},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return per_icd
