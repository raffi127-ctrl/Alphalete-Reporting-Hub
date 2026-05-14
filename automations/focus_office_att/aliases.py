"""Centralized owner-name alias lookup, backed by a Google Sheet.

Source of truth: the 'ICD Aliases' tab in the 'PROJECT REQUESTS FROM REPORT
HUB' workbook (1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw). Schema:
  Col A: Alias (the name as it appears in Tableau / ownerville / etc.)
  Col B: Canonical (the EXACT Sheet tab name for this person)
  Row 1: headers; data starts at row 2.

Why a Sheet, not JSON: every teammate can edit it directly in the browser
without touching code or git. New ICD added to a Sheet tab → confirm the
mapping in each external platform → add a row here → automation picks it
up on the next run.

Public API:
  load_aliases() → {canonical_sheet_tab: [alias1, alias2, ...]}
  alias_to_canonical(name, raw)
  get_search_candidates(name, raw)
  save_alias(canonical, alias)   # appends a new row
"""
from __future__ import annotations

from automations.recruiting_report import fill as _fill

ALIAS_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
ALIAS_TAB = "ICD Aliases"


def _open_alias_tab():
    sh = _fill._client().open_by_key(ALIAS_SHEET_ID)
    return sh.worksheet(ALIAS_TAB)


def load_aliases() -> dict[str, list[str]]:
    """Read the alias Sheet and return {canonical_sheet_tab: [aliases]}.

    Skips header row + empty rows. Multiple alias rows pointing to the same
    canonical get grouped under one key.
    """
    out: dict[str, list[str]] = {}
    try:
        ws = _open_alias_tab()
    except Exception as e:
        print(f"⚠ Couldn't open '{ALIAS_TAB}' tab: {e}")
        return out
    rows = ws.get("A2:B500")
    for row in rows:
        if len(row) < 2:
            continue
        alias = (row[0] or "").strip()
        canonical = (row[1] or "").strip()
        if not alias or not canonical:
            continue
        out.setdefault(canonical, [])
        if alias not in out[canonical]:
            out[canonical].append(alias)
    return out


def alias_to_canonical(name: str, raw: dict) -> str:
    """Reverse lookup: any alias OR canonical → canonical Sheet tab name.
    Returns the input unchanged if not in the alias table."""
    n = (name or "").lower().strip()
    for canonical, aliases in raw.items():
        if canonical.lower().strip() == n:
            return canonical
        for a in aliases:
            if a.lower().strip() == n:
                return canonical
    return name


def get_search_candidates(sheet_tab_name: str, raw: dict) -> list[str]:
    """Return the search-name candidates to try when looking this person up
    in an external system. Sheet tab name first, then aliases."""
    candidates = [sheet_tab_name]
    for alias in raw.get(sheet_tab_name, []):
        if alias not in candidates:
            candidates.append(alias)
    return candidates


def save_alias(canonical: str, alias: str) -> None:
    """Append a new (alias, canonical) row to the alias Sheet. No-op if the
    pair already exists. Prints a confirmation."""
    canonical = canonical.strip()
    alias = alias.strip()
    if not canonical or not alias:
        return
    try:
        ws = _open_alias_tab()
    except Exception as e:
        print(f"⚠ Couldn't open '{ALIAS_TAB}' tab to save: {e}")
        return
    # Check existing rows for duplicates before appending.
    existing = ws.get("A2:B500") or []
    for row in existing:
        if len(row) >= 2:
            ea = (row[0] or "").strip().lower()
            ec = (row[1] or "").strip().lower()
            if ea == alias.lower() and ec == canonical.lower():
                print(f"  (alias '{alias}' → '{canonical}' already in Sheet — skipped)")
                return
    ws.append_row([alias, canonical], value_input_option="RAW")
    print(f"  ✓ Saved alias to Sheet: '{alias}' → '{canonical}'")
