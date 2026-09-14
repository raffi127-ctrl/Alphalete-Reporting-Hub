"""The 'WEEKLY KNOCKS DATA' box on an ATT Program - Focus Report office tab.

Rafael (via Eve, 2026-09-14): every week, each office's Weekly Knock
Dispositions OFFICE TOTALS row also lands in that office's Focus Report tab,
one column per week, in the box Eve laid out under the OPT section.

No hardcoded rows or columns (CLAUDE.md): the box is found by its column-B
header, each row by its column-B label, and the week by the row-1 date header
(`fill.find_sunday_columns`). The box ends at its first blank label row.

THE BOX LABELS ARE THE BOARD'S OWN HEADERS. Eve typed them off the board as
Raf re-labelled it on 2026-09-13 (every column says its span: "Mon–Fri Total
Knocks", "Mon–Sat Total Talk To's", "Sat Avg Doors / Day"…), so a board column
lands on the box row with the same name — compared case-, dash- and
spacing-insensitively, since the board prints en dashes and the box was typed
with hyphens. A column the board grows later lands the day someone adds a row
with its name; a box row with no board column simply stays blank.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

BOX_HEADER = "WEEKLY KNOCKS DATA"
BOX_MAX_ROWS = 30          # a runaway box (no blank row under it) stops here

# Board columns that are not office numbers.
SKIP_HEADERS = ("Rep",)
SKIP_PREFIXES = ("# Reps",)

# Box rows whose cell format has no decimals by default but whose value does
# (Kash's test tab showed 65.68 as "66" on 2026-09-14).
TWO_DECIMAL_LABELS = (
    "Mon-Fri Avg Doors / Day",
    "Mon-Sat Avg Talk To's / Day",
    "Mon-Sat Avg Talk To's per App",
    "Sat Avg Doors / Day",
    "Sat Avg Talk To's / Day",
)


def norm(s: str) -> str:
    """Case, dash and spacing-insensitive: the board prints en dashes
    ("Mon–Fri"), the box was typed with hyphens."""
    s = (s or "").replace("–", "-").replace("—", "-").lower()
    return re.sub(r"\s+", " ", s).strip()


def find_box(col_b: List[str]) -> Tuple[Optional[int], Dict[str, int]]:
    """(header row, {normalized label: row}), 1-indexed. (None, {}) when the
    tab has no box."""
    header = next((i for i, v in enumerate(col_b, 1)
                   if norm(v) == norm(BOX_HEADER)), None)
    if header is None:
        return None, {}
    rows: Dict[str, int] = {}
    last = min(header + BOX_MAX_ROWS, len(col_b))
    for r in range(header + 1, last + 1):
        label = norm(col_b[r - 1])
        if not label:
            break
        rows.setdefault(label, r)
    return header, rows


def totals_row(rows: List[List[str]], label: str = "OFFICE TOTALS"
               ) -> Optional[List[str]]:
    """The office's own totals row, found by its label — never by position:
    comparison rows (CHAN PARK TOTALS) sit above it and team bands below."""
    return next((r for r in rows if len(r) > 1
                 and str(r[1]).strip().upper() == label.upper()), None)


def plan(headers: List[str], totals: List[str],
         col_b: List[str]) -> Tuple[Optional[int], List[Tuple[int, str, str]],
                                    List[str]]:
    """What to write: (box header row, [(row, box label, value)], board
    columns with a value but no box row on this tab).

    A blank board cell is skipped, never written as blank — a column the pull
    couldn't fill must not wipe a number somebody typed."""
    header, rows = find_box(col_b)
    if header is None:
        return None, [], []
    labels = {norm(col_b[r - 1]): col_b[r - 1].strip() for r in rows.values()}
    out: List[Tuple[int, str, str]] = []
    missing: List[str] = []
    for i, h in enumerate(headers):
        if h in SKIP_HEADERS or any(h.startswith(p) for p in SKIP_PREFIXES):
            continue
        value = str(totals[i] if i < len(totals) else "").strip()
        if not value:
            continue
        row = rows.get(norm(h))
        if row is None:
            missing.append(h)
            continue
        out.append((row, labels[norm(h)], value))
    return header, out, missing
