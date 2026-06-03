"""Google-Sheet operations for the Int WoW Report 'Penetration %' table.

Every weekly run inserts ONE new column at B (newest first) inside ONLY the
Penetration table's row range (header -> NATIONAL) — never a full-sheet column,
so the other tables on the tab are untouched (Eve's decision (b), 2026-06-02).

Rows / columns are located by LABEL, never by hardcoded index (templates move):
  header row  = col-A cell == 'PENETRATION %'
  total row   = col-A cell == 'NATIONAL'
  owner rows  = everything between, EXCEPT "...'s Team" sub-headers (skipped).

Owner matching is canonicalized through the ICD Aliases sheet on BOTH sides
(Tableau spelling and sheet label), mirroring owners_metrics_churn.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import defaultdict
from typing import Optional

from automations.recruiting_report.fill import open_by_key

SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
WORKSHEET_GID = 164937446          # 'Int WoW Report' (production tab)
# Sandbox during build was gid 1597480198 ('Int WoW Report - TEST').
HEADER_LABEL = "PENETRATION %"
TOTAL_LABEL = "NATIONAL"
NO_DATA = "-%"

_TEAM_RE = re.compile(r"\bteam$", re.I)            # 'Aron's Team', 'Raf's Team'
_SUFFIX = {"ii", "iii", "iv", "v", "jr", "sr"}


def open_ws():
    return open_by_key(SHEET_ID).get_worksheet_by_id(WORKSHEET_GID)


def week_label(d: dt.date) -> str:
    """Sunday weekending -> 'WE M.D' (no leading zeros, no year)."""
    return f"WE {d.month}.{d.day}"


def last_sunday(d: dt.date) -> dt.date:
    """The Sunday on/before d. Mon=0..Sun=6 -> Sunday subtracts (wd+1)%7."""
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


class NameMatcher:
    """Match owner names across spelling variants using the ICD Aliases sheet
    as an UNDIRECTED graph: every (alias, canonical) pair is an edge, and two
    names are the same person iff they sit in the same connected component.

    More robust than a single-hop alias_to_canonical lookup, which breaks when
    the sheet stores MORE THAN ONE canonical string for the same person —
    'Hammad Haque' and 'Muhammad Haque' are both canonicals, 'Tre Mitchell' and
    'Lamar Mitchell' likewise (all the same people). Single-hop sends the
    Tableau spelling to one canonical and the sheet spelling to another, so
    they never meet. Union-find collapses every variant into one component, so
    matching works WITHOUT editing the alias sheet (Eve, 2026-06-02)."""

    def __init__(self, aliases: dict):
        self._parent: dict[str, str] = {}
        for canonical, names in (aliases or {}).items():
            kc = self._norm(canonical)
            for alias in names:
                self._union(kc, self._norm(alias))

    @staticmethod
    def _norm(s: str) -> str:
        return (s or "").strip().lower()

    def _find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def _union(self, a: str, b: str) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            self._parent[ra] = rb

    def key(self, name: str) -> str:
        """Match-key for `name`: its component root if it appears in the alias
        graph, else its plain normalized form (non-aliased names match by exact
        spelling)."""
        k = self._norm(name)
        return self._find(k) if k in self._parent else k


def _toks(name: str) -> list[str]:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return [t for t in re.sub(r"[^a-zA-Z ]", " ", n).lower().split()
            if t and t not in _SUFFIX]


def _lev(a: str, b: str) -> int:
    """Levenshtein distance (small strings; early-out when lengths diverge)."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def near_match(name: str, sheet_names: list[str]) -> Optional[str]:
    """Return an existing sheet name that looks like the SAME person as `name`
    (so we warn instead of inserting a duplicate). Rule: same LAST token AND
    first names are prefix-compatible OR within edit-distance 1 — catches
    'Zachary Hogue'/'Zach Hogue', 'Hammad UI Haque'/'Hammad Haque',
    'Milly Villagrana'/'Mily Villagrana'. Returns None if nothing looks alike."""
    ta = _toks(name)
    if not ta:
        return None
    for other in sheet_names:
        tb = _toks(other)
        if not tb or ta[-1] != tb[-1]:
            continue
        fa, fb = ta[0], tb[0]
        if (fa == fb or fa.startswith(fb) or fb.startswith(fa)
                or _lev(fa, fb) <= 1):
            return other
    return None


def find_table(ws) -> dict:
    """Locate the Penetration table by col-A labels. Returns header_row,
    total_row (1-indexed), and owner_rows = [(row, raw_name)] skipping the
    '...'s Team' sub-headers."""
    colA = ws.col_values(1)
    header_row = total_row = None
    for i, v in enumerate(colA, start=1):
        n = (v or "").strip().upper()
        if header_row is None and n == HEADER_LABEL:
            header_row = i
        elif header_row is not None and n == TOTAL_LABEL:
            total_row = i
            break
    if header_row is None or total_row is None:
        raise RuntimeError(
            f"Couldn't find {HEADER_LABEL!r} + {TOTAL_LABEL!r} in col A "
            f"(header={header_row}, total={total_row}).")
    owner_rows = []
    for r in range(header_row + 1, total_row):
        name = (colA[r - 1] if r - 1 < len(colA) else "").strip()
        if not name or _TEAM_RE.search(name):
            continue
        owner_rows.append((r, name))
    return {"header_row": header_row, "total_row": total_row,
            "owner_rows": owner_rows}


def current_week_at_b(ws, header_row: int) -> str:
    return (ws.cell(header_row, 2).value or "").strip()


def _values_update(ws, a1_range: str, values: list) -> None:
    """RAW write so '1.60%' / '-%' / 'WE 5.24' land as literal strings (the
    column mixes percent strings and '-%', so it's all text)."""
    ws.spreadsheet.values_update(
        f"'{ws.title}'!{a1_range}",
        params={"valueInputOption": "RAW"},
        body={"values": values})


def insert_week_column(ws, header_row: int, total_row: int,
                       dry_run: bool = False) -> None:
    """Insert ONE blank column at B, shifting cells right ONLY within rows
    header_row..total_row (bounded range — leaves the rest of the tab alone)."""
    if dry_run:
        print(f"  [dry-run] would insert column B over rows "
              f"{header_row}-{total_row}")
        return
    ws.spreadsheet.batch_update({"requests": [{"insertRange": {
        "range": {"sheetId": ws.id,
                  "startRowIndex": header_row - 1, "endRowIndex": total_row,
                  "startColumnIndex": 1, "endColumnIndex": 2},
        "shiftDimension": "COLUMNS"}}]})


def insert_owner_row(ws, name: str, dry_run: bool = False) -> int:
    """Insert a new owner row in alphabetical (case-insensitive) position
    among the owner rows, just above NATIONAL. Returns the new row (or the
    would-be row in dry-run). Re-reads the table so positions stay correct
    when several owners are added in one run."""
    table = find_table(ws)
    pos = table["total_row"]               # default: just above NATIONAL
    for row, existing in table["owner_rows"]:
        if name.lower() < existing.lower():
            pos = row
            break
    if dry_run:
        print(f"  [dry-run] would insert owner {name!r} at row {pos}")
        return pos
    ws.spreadsheet.batch_update({"requests": [{"insertDimension": {
        "range": {"sheetId": ws.id, "dimension": "ROWS",
                  "startIndex": pos - 1, "endIndex": pos},
        "inheritFromBefore": True}}]})
    _values_update(ws, f"A{pos}", [[name]])
    return pos


def apply_week(ws, label: str, owners_pct: dict, national: Optional[str],
               aliases: dict, dry_run: bool = False,
               force: bool = False) -> dict:
    """Insert the week column and write penetration values.

    owners_pct: {raw_tableau_owner_name: 'X.XX%'} from the pull.
    Returns a summary dict (matched / no_data / new / near_match / unmatched).
    """
    matcher = NameMatcher(aliases)
    norm = NameMatcher._norm

    # Index CSV owners by exact-normalized name AND by alias-component key.
    csv_by_norm: dict[str, list] = defaultdict(list)
    csv_by_key: dict[str, list] = defaultdict(list)
    for cname in owners_pct:
        csv_by_norm[norm(cname)].append(cname)
        csv_by_key[matcher.key(cname)].append(cname)

    def match_rows(owner_rows):
        """Bind each sheet row to a CSV owner in TWO passes, consuming each CSV
        owner once:
          1) exact normalized name  (Pat Thompson -> Pat Thompson)
          2) same alias-component    (Tre Mitchell -> Tre Mitchell III)
        So two sheet rows of the same person each get THEIR OWN Tableau value
        (Pat vs Patrick Thompson), and the one Tableau didn't report falls to
        '-%' — never the same value copied to both (Eve, 2026-06-02)."""
        consumed: set = set()
        row_pct: dict[int, str] = {}
        for row, sname in owner_rows:                      # pass 1: exact
            for cname in csv_by_norm.get(norm(sname), []):
                if cname not in consumed:
                    row_pct[row] = owners_pct[cname]
                    consumed.add(cname)
                    break
        for row, sname in owner_rows:                      # pass 2: component
            if row in row_pct:
                continue
            for cname in csv_by_key.get(matcher.key(sname), []):
                if cname not in consumed:
                    row_pct[row] = owners_pct[cname]
                    consumed.add(cname)
                    break
        return row_pct, consumed

    table = find_table(ws)
    sheet_names = [n for _, n in table["owner_rows"]]
    _, consumed = match_rows(table["owner_rows"])

    # CSV owners that matched no sheet row -> genuinely new, or look-alike.
    new_owners: list[tuple[str, str]] = []
    near_warn: list[tuple[str, str]] = []
    for cname, pct in owners_pct.items():
        if cname in consumed:
            continue
        hit = near_match(cname, sheet_names)
        if hit:
            near_warn.append((cname, hit))
        else:
            new_owners.append((cname, pct))

    # 1) Insert genuinely-new owners (alphabetical) BEFORE touching columns.
    for name, _pct in sorted(new_owners, key=lambda t: t[0].lower()):
        insert_owner_row(ws, name, dry_run=dry_run)

    # 2) Idempotency: if this week is already at B, overwrite it; else insert.
    table = find_table(ws)                       # re-read after row inserts
    overwrite = (current_week_at_b(ws, table["header_row"]) == label
                 and not force)
    if overwrite:
        print(f"  ⚠ '{label}' already at column B — overwriting it "
              f"(no new column).")
    else:
        insert_week_column(ws, table["header_row"], table["total_row"],
                           dry_run=dry_run)

    # 3) Re-read (rows/cols moved), re-match, build the B column top-to-bottom.
    table = find_table(ws)
    h, t = table["header_row"], table["total_row"]
    row_pct, _ = match_rows(table["owner_rows"])
    owner_row_set = {row for row, _ in table["owner_rows"]}

    col_b: list[list[str]] = []
    no_data = matched = 0
    for r in range(h, t + 1):
        if r == h:
            col_b.append([label]); continue
        if r == t:
            col_b.append([national or NO_DATA]); continue
        if r not in owner_row_set:               # team sub-header → leave blank
            col_b.append([""]); continue
        if r in row_pct:
            col_b.append([row_pct[r]]); matched += 1
        else:
            col_b.append([NO_DATA]); no_data += 1

    if dry_run:
        print(f"  [dry-run] would write B{h}:B{t} "
              f"({matched} matched, {no_data} '-%', total={national!r})")
    else:
        _values_update(ws, f"B{h}:B{t}", col_b)

    return {"label": label, "matched": matched, "no_data": no_data,
            "new_inserted": [n for n, _ in new_owners],
            "near_match": near_warn, "national": national,
            "overwrite": overwrite}
