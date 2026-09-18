"""Sale transfers -- the Sales Board's last step of the day.

WHY. A new rep often has no SaraPlus login of their own for the first week or
two, so they sell under somebody else's. SaraPlus -- and so the 5-minute sweep
-- credits that sale to the LOGIN, not to the rep who made it. The rep then
fills the "ATT Sales Transfers" form, and this moves exactly those sales on the
board: minus on the login owner's row, plus on the rep's. Only the sales on the
form -- the login owner usually has sales of their own on the same day, so a
row is never moved wholesale (Eve 2026-09-18).

SOURCE, spelled out:
  workbook  'All in One Local Office - Raf' (1Ez-mbRO…ML6DVB4)
  tab       'ATT Sales Transfers' (the form's responses)
  col B     "Your Name (That's getting the sale transferred to)"  -> TO
  col C     "Name that the Sale is under"                         -> FROM
  col D     "Date of Sale"  -- ONLY rows equal to the day being closed
  col E     "Type of Product Sold" (a row can carry several, comma-separated)
  col J     "Notes"         -- read only for a line count ("4 Lines")
Columns are found by their header text, never by letter.

TARGET: the same cells the sweep writes -- 'Sales Board WE <m>.<d>' -> the
day's block -> Int / Int Up / DTV / NL on each rep's row (and the SANDBOX twin
while it exists, so the two keep agreeing).

    New Internet -> Int      Upgrade -> Int Up      DTV -> DTV
    New Line     -> NL  (x the number of lines in Notes, else 1)

WHAT IT WILL NOT DO -- every one of these is REPORTED instead, for a person:
  * move a sale the FROM row does not have (moving it anyway would invent a
    sale on one row and a negative on the other);
  * guess a name: a TO or FROM that matches no row, or several, is left alone;
  * touch a day carrying a roll-call status ('X', 'T', ...);
  * move half a form row: all of its products move, or none do;
  * act on a "Your Name" that is not a person -- 'bonus', '$50', 'owners pay'
    are bonus entries, not transfers, and are skipped silently;
  * act on a row whose Date of Sale is not the closed day. Those are listed as
    LATE so nobody assumes they were handled.

NO MINUS, ONLY THE PLUS, in two cases -- both where the sweep never put the
sale on any row, so there is nothing to take back:
  * FROM is the sales manager (config.EXCLUDE_REPS, e.g. Joshua / "JD"
    Mascorro), whose login the sweep keeps off the board;
  * FROM's day carries a roll-call status ('x' -- the login owner did not work
    that day; Rhea McKee on 9/16, Safiya Mahmoud on 9/14). The sweep never
    writes over a status, so the sale landed nowhere.

ONCE ONLY. Every moved form row is recorded in STATE_PATH, and a second run
skips it -- a rerun must not move the same sale twice. The state is per machine,
which is why the scheduled run is pinned to Lucy 1 like the sweep.
MOVED BY HAND (or from another machine): list the sale's key in HAND_DONE_PATH
(checked in, so every machine reads it) and no run will move it again. 9/17:
Eve moved Ana Griffin's three by hand before the 05:00 run got to them.
ALSO: the sweep's own `--date <past day> --force` rewrites a day straight from
SaraPlus and would put the FROM sales back. Re-run this with --force after it.

WHEN. After the day is closed: the sweep's last tick is 21:30 (17:00 Sat), and
most forms come in overnight. The orchestrator runs it every morning for
YESTERDAY.

    python -m automations.alphalete_sales_board.sale_transfers              # preview, yesterday
    python -m automations.alphalete_sales_board.sale_transfers --apply
    python -m automations.alphalete_sales_board.sale_transfers --date 2026-09-16

Python 3.9-safe (Lucy runtime). Cross-platform.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.alphalete_sales_board import calc, config as C, fill
from automations.rep_sales_fill import board as B

FORM_SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
FORM_TAB = "ATT Sales Transfers"
STATE_PATH = Path.home() / ".config" / "recruiting-report" / "sale_transfers_state.json"
HAND_DONE_PATH = Path(__file__).with_name("sale_transfers_hand_done.json")

# Header text (lower-case, contains) -> field. Found by label, not by letter.
HEADERS = {
    "to": "your name",
    "from": "name that the sale is under",
    "date": "date of sale",
    "product": "type of product",
    "customer": "customers name",
    "spm": "spm",
    "notes": "notes",
}

# Product wording on the form -> board column. Checked in order, first hit wins.
PRODUCTS = (
    ("upgrade", "Int Up"),
    ("internet", "Int"),
    ("fiber", "Int"),
    ("dtv", "DTV"),
    ("directv", "DTV"),
    ("line", "NL"),
    ("wireless", "NL"),
)

# Not a person: bonus lines ('$20 bonus', 'owners pay') and test submissions.
_BONUS_WORDS = ("bonus", "owner", "pay", "spiff", "$", "(test)")


# --- reading the form -------------------------------------------------------
def _clean(s) -> str:
    return " ".join(str(s or "").replace("﻿", "").split())


def _norm(s: str) -> str:
    return B._norm_name(_clean(s))


def parse_date(s: str) -> Optional[dt.date]:
    s = _clean(s)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def is_bonus(name: str) -> bool:
    """'bonus', '$50', 'Owners Pay' ... -- anything that is not a person."""
    n = _clean(name).lower()
    if not n:
        return True
    return (any(w in n for w in _BONUS_WORDS) or any(ch.isdigit() for ch in n)
            or not re.search(r"[a-z]", n))


def line_count(notes: str) -> int:
    """'It was 1 internet 1 DTV 4 Lines' -> 4; '2 ported lines' -> 2; else 1."""
    m = re.search(r"(\d+)\s*(?:[a-z]+\s+)?lines?\b", _clean(notes).lower())
    return max(int(m.group(1)), 1) if m else 1


def products(kind: str, notes: str) -> Tuple[Dict[str, int], List[str]]:
    """({metric: qty}, [unknown product words])."""
    out: Dict[str, int] = {}
    unknown: List[str] = []
    for part in re.split(r"[,/&+]| and ", _clean(kind).lower()):
        part = part.strip()
        if not part:
            continue
        metric = next((m for word, m in PRODUCTS if word in part), None)
        if metric is None:
            unknown.append(part)
            continue
        qty = line_count(notes) if metric == "NL" else 1
        out[metric] = max(out.get(metric, 0), qty)
    return out, unknown


def header_map(header: List[str]) -> Dict[str, int]:
    """{field: 0-based index}. Raises naming the header it could not find."""
    low = [_clean(h).lower() for h in header]
    out = {}
    for field, needle in HEADERS.items():
        idx = next((i for i, h in enumerate(low) if h.startswith(needle)), None)
        if idx is None:
            idx = next((i for i, h in enumerate(low) if needle in h), None)
        if idx is None and field in ("to", "from", "date", "product"):
            raise RuntimeError("the %r tab has no %r column any more -- headers "
                               "are: %s" % (FORM_TAB, needle, header))
        if idx is not None:
            out[field] = idx
    return out


def read_form(values: List[List[str]]) -> List[Dict]:
    """Every response as a dict, with its sheet row number."""
    if not values:
        return []
    hm = header_map(values[0])
    out = []
    for r, row in enumerate(values[1:], start=2):
        def get(f):
            i = hm.get(f)
            return _clean(row[i]) if i is not None and i < len(row) else ""
        if not any(_clean(v) for v in row):
            continue
        out.append({"row": r, "to": get("to"), "from": get("from"),
                    "date_raw": get("date"), "date": parse_date(get("date")),
                    "product": get("product"), "customer": get("customer"),
                    "spm": get("spm"), "notes": get("notes")})
    return out


def key(t: Dict) -> str:
    """Identity of ONE sale on the form. The timestamp is left out on purpose,
    so the same sale submitted twice is one sale, not two."""
    return "|".join([_norm(t["to"]), _norm(t["from"]), str(t["date"]),
                     _clean(t["product"]).lower(), _clean(t["spm"]).lower(),
                     _clean(t["customer"]).lower()])


def select(responses: List[Dict], day: dt.date, done: Dict[str, str]
           ) -> Tuple[List[Dict], List[str], List[Dict]]:
    """(transfers to move, notes, late rows) for the closed day."""
    todo, notes, late, seen = [], [], [], set()
    for t in responses:
        if is_bonus(t["to"]):
            continue
        if t["date"] is None:
            notes.append("form row %d: Date of Sale %r unreadable -- skipped"
                         % (t["row"], t["date_raw"]))
            continue
        k = key(t)
        if t["date"] != day:
            if t["date"] < day and k not in done and day - t["date"] <= dt.timedelta(days=7):
                late.append(t)
            continue
        if k in done:
            continue
        if k in seen:
            notes.append("form row %d: same sale as an earlier row (%s, %s, %s) "
                         "-- counted once" % (t["row"], t["to"], t["product"], t["spm"]))
            continue
        seen.add(k)
        t = dict(t, key=k)
        t["metrics"], unknown = products(t["product"], t["notes"])
        if unknown or not t["metrics"]:
            notes.append("form row %d: product %r not understood -- not moved"
                         % (t["row"], t["product"]))
            continue
        todo.append(t)
    return todo, notes, late


# --- planning the board -----------------------------------------------------
def _is_manager(name: str) -> bool:
    """FROM is a login the sweep never puts on the board (EXCLUDE_REPS).
    'JD Mascorro' is Joshua Mascorro: same last name, same first initial."""
    toks = _norm(name).split()
    if not toks:
        return False
    for ex in C.EXCLUDE_REPS:
        et = ex.lower().split()
        if et and et[-1] == toks[-1] and et[0][:1] == toks[0][:1]:
            return True
    return False


def _spelling_match(name: str, names: List[str]) -> Optional[str]:
    """The ONE board name that is the same name typed badly -- 'Pranish
    shresta' / 'kelvinton scar bough' -- judged with the spaces taken out.
    0.85 is the bar fill.near_matches uses for 'a typo or a missing letter';
    two candidates, or a runner-up close behind, is a guess and returns None."""
    import difflib
    want = _norm(name).replace(" ", "")
    if not want:
        return None
    scored = sorted(((difflib.SequenceMatcher(None, want, _norm(b).replace(" ", "")).ratio(), b)
                     for b in names), reverse=True)
    if not scored or scored[0][0] < 0.85:
        return None
    if len(scored) > 1 and scored[1][0] >= 0.85:
        return None
    return scored[0][1]


def _row_for(grid, name: str, names: List[str], alias_map) -> Tuple[Optional[int], str]:
    board_name, note = calc.match_name(name, names, alias_map)
    if not board_name:
        fixed = _spelling_match(name, names)
        if not fixed:
            return None, note
        board_name, note = fixed, "spelling %r read as %r" % (name, fixed)
    row, note2 = B.find_rep_row(grid, board_name)
    return row, note2 or note


def _num(v: str) -> Optional[int]:
    v = str(v or "").strip()
    if not v:
        return 0
    try:
        return int(float(v))
    except ValueError:
        return None


def plan(grid, day: dt.date, transfers: List[Dict],
         alias_map: Optional[Dict[str, str]] = None
         ) -> Tuple[List[Dict], List[Dict], List[str]]:
    """(cell updates, moved transfers, notes). All-or-nothing per form row."""
    cols = B.day_blocks(grid).get(day.strftime("%A"))
    if not cols:
        return [], [], ["no %s block on this tab -- nothing moved"
                        % day.strftime("%A")]
    names = fill.board_names(grid)
    cur: Dict[Tuple[int, int], Optional[int]] = {}

    def off(r) -> bool:
        # Roll call is judged per DAY: the 'X' sits in one cell of the block
        # (usually Int), and the whole day is a status day.
        return any(B.is_status(B.cell(grid, r, c)) for c in cols.values())

    def value(r, c):
        if (r, c) not in cur:
            raw = B.cell(grid, r, c)
            cur[(r, c)] = None if off(r) else _num(raw)
        return cur[(r, c)]

    moved, notes = [], []
    for t in transfers:
        label = "row %d %s <- %s (%s)" % (t["row"], t["to"], t["from"], t["product"])
        to_row, why = _row_for(grid, t["to"], names, alias_map)
        if to_row is None:
            notes.append("%s: TO not on the board -- %s" % (label, why))
            continue
        manager = _is_manager(t["from"])
        from_row = None
        if not manager:
            from_row, why = _row_for(grid, t["from"], names, alias_map)
            if from_row is None:
                notes.append("%s: FROM not on the board -- %s" % (label, why))
                continue
            if from_row == to_row:
                notes.append("%s: TO and FROM are the same row -- nothing to move"
                             % label)
                continue

        problem = ""
        from_status = False
        for m, qty in t["metrics"].items():
            c = cols.get(m)
            if not c:
                problem = "no %s column in the day block" % m
                break
            if value(to_row, c) is None:
                problem = "%s's day carries a roll-call status" % t["to"]
                break
            if from_row is not None:
                have = value(from_row, c)
                if have is None:
                    # FROM did not work that day: the sweep skipped the row, so
                    # the sale is on nobody's -- plus only (see the docstring).
                    from_status = True
                    continue
                if have < qty:
                    problem = ("%s has %d %s on the board, the form moves %d"
                               % (B.cell(grid, from_row, B.NAME_COL).strip(),
                                  have, m, qty))
                    break
        if problem:
            notes.append("%s: NOT moved -- %s" % (label, problem))
            continue

        if from_status:
            from_row = None
        for m, qty in t["metrics"].items():
            c = cols[m]
            cur[(to_row, c)] = value(to_row, c) + qty
            if from_row is not None:
                cur[(from_row, c)] = value(from_row, c) - qty
        if manager:
            src = "%s (manager login, not on the board)" % t["from"]
        elif from_status:
            src = "%s (off that day -- sale was on no row)" % t["from"]
        else:
            src = B.cell(grid, from_row, B.NAME_COL).strip()
        moved.append(dict(t, from_board=src,
                          to_board=B.cell(grid, to_row, B.NAME_COL).strip()))

    updates = []
    for (r, c), v in sorted(cur.items()):
        if v is None:
            continue
        new = str(v) if v else ""
        if new != B.cell(grid, r, c).strip():
            updates.append({"range": fill._a1(r, c), "values": [[new]]})
    return updates, moved, notes


# --- state ------------------------------------------------------------------
def load_state(path: Path = STATE_PATH) -> Dict[str, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("done", {})
    except (OSError, ValueError):
        return {}


def load_hand_done(path: Path = HAND_DONE_PATH) -> Dict[str, str]:
    """Sales a person already moved on the board -- same shape as the state."""
    return load_state(path)


def save_state(done: Dict[str, str], path: Path = STATE_PATH) -> None:
    # Keep ~2 months: enough to never re-move a sale, small enough to read.
    cutoff = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    done = {k: v for k, v in done.items() if v >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"done": done}, indent=1, sort_keys=True),
                    encoding="utf-8")


# --- CLI --------------------------------------------------------------------
def _metrics_txt(m: Dict[str, int]) -> str:
    return ", ".join("%d %s" % (q, k) for k, q in m.items())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="the day to close (YYYY-MM-DD); default yesterday")
    ap.add_argument("--apply", action="store_true", help="write the board")
    ap.add_argument("--force", action="store_true",
                    help="ignore the already-moved record (after a sweep --force)")
    a = ap.parse_args(argv)

    day = (dt.date.fromisoformat(a.date) if a.date
           else dt.date.today() - dt.timedelta(days=1))
    from automations.recruiting_report.fill import _client
    gc = _client()

    # --force also drops the hand list: it follows a sweep --force, which
    # rewrote the day from SaraPlus and wiped the hand moves too.
    done = {} if a.force else dict(load_hand_done(), **load_state())
    form = gc.open_by_key(FORM_SHEET_ID).worksheet(FORM_TAB).get_all_values()
    todo, notes, late = select(read_form(form), day, done)
    print("Sale transfers for %s (%s): %d to move from the form"
          % (day.isoformat(), day.strftime("%A"), len(todo)))

    moved: List[Dict] = []
    if todo:
        try:
            from automations.alphalete_sales_board import aliases
            alias_map = aliases.load()
        except Exception as e:  # noqa: BLE001 -- the aliases tab is a nicety
            print("(aliases tab unreadable: %s -- config.NAME_MAP only)" % e)
            alias_map = {}
        live = fill.open_tab(day, gc)
        updates, moved, pnotes = plan(live.get_all_values(), day, todo, alias_map)
        notes += pnotes
        print("tab %r: %d cell(s) to change" % (live.title, len(updates)))
        twin = fill.sandbox_twin(live, gc)
        twin_updates = []
        if twin is not None:
            twin_updates, _m, tnotes = plan(twin.get_all_values(), day,
                                            [t for t in todo if t["key"] in
                                             {x["key"] for x in moved}], alias_map)
            notes += ["[sandbox] " + n for n in tnotes]
        if a.apply and updates:
            fill.apply(live, updates)
            if twin is not None and twin_updates:
                fill.apply(twin, twin_updates)
                print("mirrored %d cell(s) to %r" % (len(twin_updates), twin.title))
            stamp = dt.date.today().isoformat()
            done = load_state()
            done.update({t["key"]: stamp for t in moved})
            save_state(done)

    for t in moved:
        print("  MOVED  %s: %s -> %s  [form row %d, %s]"
              % (_metrics_txt(t["metrics"]), t["from_board"], t["to_board"],
                 t["row"], t["spm"] or "no SPM"))
    for n in notes:
        print("  CHECK  " + n)
    for t in late:
        print("  LATE   form row %d: %s <- %s, %s on %s -- sold before %s, NOT moved"
              % (t["row"], t["to"], t["from"], t["product"], t["date_raw"], day))
    if not a.apply:
        print("\npreview only -- re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
