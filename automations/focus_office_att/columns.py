"""Header-based column resolver for the Focus Office ATT report.

WHY: Column positions in the Sheet are NOT stable — Megan and Raf edit
the live Sheets continuously (add metrics, reorder, rename). Hard-coded
column indices silently corrupt data the moment the Sheet shifts.

WHAT: Resolves canonical metric names to actual 1-based column indices
by reading row 1 (day labels) and row 2 (metric headers). Per-day blocks
are detected by row-1 day-label cells ("Mon 5/11", "Tue 5/12", ...).

WHEN A HEADER ISN'T FOUND: the resolver asks the user interactively in
the terminal (since this script is CLI-driven). The user's answer is
persisted to `output/focus_office_header_aliases.json` so re-runs don't
re-prompt.

Usage:
    from automations.focus_office_att.columns import resolve_layout
    layout = resolve_layout(ws)
    # layout.rep_name_col → 2
    # layout.day_cols[0]["first_knock"] → 17  (Mon's First Knock col)
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Canonical metric names — keep this list tight and explicit. The actual
# header text in the Sheet can differ (typos, parenthetical suffixes); the
# resolver handles fuzzy match + prompts the user when ambiguous.
CANONICAL_METRICS = [
    "Total Apps",
    "Total Leads Knocked",
    "Talk To's",
    "Presentations",
    "First Knock",
    "Last Knock Date",
    "# of gaps",
    "total gap time",
    "New INT",
    "Upgrades",
    "DTV",
    "New Lines",
]

DAY_PREFIXES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

ALIASES_PATH = Path(__file__).resolve().parent.parent.parent / "output" / "focus_office_header_aliases.json"


def _normalize(s: str) -> str:
    """Lowercase + collapse whitespace for forgiving header comparison."""
    return " ".join((s or "").lower().split())


def _load_aliases() -> dict:
    """Load user-confirmed canonical → actual-header overrides."""
    if not ALIASES_PATH.exists():
        return {}
    try:
        return json.loads(ALIASES_PATH.read_text())
    except Exception:
        return {}


def _save_aliases(aliases: dict) -> None:
    ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALIASES_PATH.write_text(json.dumps(aliases, indent=2, sort_keys=True))


@dataclass
class Layout:
    """Resolved column layout for one worksheet."""
    rep_name_col: int
    # day_cols[weekday_idx] = {metric_canonical: col_idx_1based}
    day_cols: dict[int, dict[str, int]] = field(default_factory=dict)


def _find_day_starts(row1: list[str]) -> dict[int, int]:
    """Return {weekday_idx: 1-based start col} for any day labels found in row 1."""
    starts: dict[int, int] = {}
    for col_idx, raw in enumerate(row1, start=1):
        norm = _normalize(raw)
        for wd, prefix in enumerate(DAY_PREFIXES):
            # "mon 5/11" → starts with "mon" but NOT a header like "monday total"
            if norm.startswith(prefix) and (len(norm) == 3 or not norm[3].isalpha()):
                # Take the LEFTMOST occurrence per weekday (in case of duplicates)
                if wd not in starts:
                    starts[wd] = col_idx
                break
    return starts


def _match_header(canonical: str, candidates: list[tuple[int, str]],
                  aliases: dict, day_label: str) -> Optional[int]:
    """Try to match a canonical metric name against (col_idx, header_text)
    candidates. Returns 1-based col or None.

    Match order:
      1. User-saved alias for this canonical (from aliases JSON)
      2. Exact normalized match
      3. Header startswith canonical (handles "Talk To's (Not interested + …)")
      4. None — caller must prompt.
    """
    canon_norm = _normalize(canonical)

    # Aliases stored as {"Presentations": "Presenations (Not interested + Sale)"}
    alias = aliases.get(canonical)
    if alias:
        alias_norm = _normalize(alias)
        for col, text in candidates:
            if _normalize(text) == alias_norm:
                return col

    for col, text in candidates:
        if _normalize(text) == canon_norm:
            return col

    for col, text in candidates:
        if _normalize(text).startswith(canon_norm):
            return col

    return None


def _prompt_for_header(canonical: str, day_label: str,
                       candidates: list[tuple[int, str]]) -> tuple[Optional[int], Optional[str]]:
    """Ask the user which header in the day block corresponds to `canonical`.

    Returns (col_idx, header_text_to_save_as_alias) or (None, None) if skipped.
    Raises SystemExit if the user aborts.
    """
    print()
    print(f"⚠  Couldn't find a column for '{canonical}' in {day_label}'s block.")
    print(f"   Headers in this block:")
    for n, (col, text) in enumerate(candidates, start=1):
        print(f"     [{n}] col {col}: {text!r}")
    print(f"   What's '{canonical}' called here?")
    print(f"     Enter a number to pick one of the above,")
    print(f"     's' to skip this metric on this run,")
    print(f"     'a' to abort (no Sheet writes).")
    while True:
        try:
            choice = input(f"   > ").strip().lower()
        except EOFError:
            print("   (no input — aborting)")
            sys.exit(1)
        if choice == "a":
            print("   Aborting at user request.")
            sys.exit(1)
        if choice == "s":
            return None, None
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(candidates):
                col, text = candidates[n - 1]
                return col, text
        print(f"   Not a valid choice. Pick 1-{len(candidates)}, 's', or 'a'.")


def resolve_layout(ws, metrics: list[str] = None, interactive: bool = True) -> Layout:
    """Read row 1 + row 2 of the worksheet and resolve the column layout.

    Args:
        ws: gspread Worksheet
        metrics: which canonical metrics to resolve (defaults to CANONICAL_METRICS)
        interactive: if True, prompt user when a header is missing; save answer
                     to aliases JSON. If False, raise on missing.

    Returns:
        Layout with rep_name_col + day_cols populated.
    """
    if metrics is None:
        metrics = CANONICAL_METRICS

    row1 = ws.row_values(1)
    row2 = ws.row_values(2)

    # Rep Name col (anywhere in row 2)
    rep_name_col = None
    for col_idx, text in enumerate(row2, start=1):
        if _normalize(text) == "rep name":
            rep_name_col = col_idx
            break
    if rep_name_col is None:
        if not interactive:
            raise LookupError("Could not find a 'Rep Name' header in row 2.")
        candidates = [(c, t) for c, t in enumerate(row2, start=1) if (t or "").strip()]
        col, _ = _prompt_for_header("Rep Name", "the entire sheet", candidates)
        if col is None:
            raise LookupError("Rep Name col is required — can't continue.")
        rep_name_col = col

    # Day-block starts
    day_starts = _find_day_starts(row1)
    if not day_starts:
        raise LookupError("No day labels (Mon/Tue/.../Sun) found in row 1.")

    # Day-block ranges: from each day's start to (next day's start - 1).
    # Last day extends to the rightmost non-empty header in row 2.
    sorted_starts = sorted(day_starts.items(), key=lambda kv: kv[1])
    last_data_col = max((c for c, t in enumerate(row2, start=1) if (t or "").strip()), default=len(row2))
    day_ranges: dict[int, tuple[int, int]] = {}
    for i, (wd, start) in enumerate(sorted_starts):
        if i + 1 < len(sorted_starts):
            end = sorted_starts[i + 1][1] - 1
        else:
            end = last_data_col
        day_ranges[wd] = (start, end)

    aliases = _load_aliases()
    aliases_changed = False
    layout = Layout(rep_name_col=rep_name_col)

    for wd, (start, end) in day_ranges.items():
        day_label = row1[start - 1] if start - 1 < len(row1) else DAY_PREFIXES[wd].title()
        candidates = [(c, row2[c - 1] if c - 1 < len(row2) else "")
                      for c in range(start, end + 1)]
        # Filter out empty header cells
        candidates = [(c, t) for c, t in candidates if (t or "").strip()]

        wd_cols: dict[str, int] = {}
        for metric in metrics:
            col = _match_header(metric, candidates, aliases, day_label)
            if col is None and interactive:
                col, picked_text = _prompt_for_header(metric, day_label, candidates)
                if picked_text:
                    aliases[metric] = picked_text
                    aliases_changed = True
            if col is None and not interactive:
                raise LookupError(
                    f"Could not find canonical metric '{metric}' in {day_label} block (cols {start}-{end})."
                )
            if col is not None:
                wd_cols[metric] = col
        layout.day_cols[wd] = wd_cols

    if aliases_changed:
        _save_aliases(aliases)
        print(f"   ✓ Saved header aliases → {ALIASES_PATH}")

    return layout
