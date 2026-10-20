"""The rep's city on the Sales Board, checked against their Blue Ink packet.

Raf, Slack 2026-10-18 ("Sales board - question / Location of reps"): too many
reps have no city in 'Location', he wants it filled automatically and checked
once a week. Eve, 2026-10-20: "si está en blueink debería estar ok, así que
cruza referencia con eso" -- Blue Ink is the truth.

WHY THEY'RE BLANK. The new-rep fill (alphalete_sales_board/fill.py,
new_rep_details) writes Location ONCE, on the day the rep is added, and only
from the hand-written classroom block under the roster. Not in the block that
day, or the block had no city -> blank for good. Nothing ever looked again.

WHAT THIS DOES, on this week's 'Sales Board WE m.d':
  blank      -> the city from their signed Blue Ink packet (I-9 first, W-4 next).
  different  -> Blue Ink's city, with a hover note keeping what was there. That
                also fixes the hand typos ('Mckinny', 'Rowlette').
  same       -> left alone (case and spaces don't count as different).
  no packet / packet without a city -> left alone and listed, for a person.

Location sits inside the board's sort/filter (C..DW), so it moves with the rep;
even so the names are read again right before writing and a row whose rep moved
is skipped, like the rest of the fixer.

Blue Ink's key only lives on Lucy 2 (blueink-creds.json), so this runs there.
Read-only on Blue Ink: GETs on bundles that are already signed.

    python -m automations.sales_board_fixer.city_check            # look only
    python -m automations.sales_board_fixer.city_check --apply    # write
    python -m automations.sales_board_fixer.city_check --date 2026-10-20 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from typing import Dict, List, NamedTuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 -- Windows console, best effort
    pass

from automations.sales_board_fixer import run as R
from automations.rep_sales_fill import board as B
from automations.terminated_reps.board import base_name

LOCATION = "location"
HUB_PHASE = "sales-board-city-check"
# Raf's Loom (2026-10-18): "Allison, maybe once a week ... or the AI somehow
# pings if for a reason we don't have it". Eve 2026-10-20: a group DM, Lucy
# sends, Alisson + Evelyn in it. Lucy is the token's owner, so she is implied.
DM_USERS = ("U0BBG374GE9",   # Alisson Rodriguez
            "U088E2KJEV8")   # Evelyn (Eve)


class Change(NamedTuple):
    row: int
    name: str
    before: str
    after: str


def location_col(grid) -> int:
    """1-based column whose ROW-1 label is 'Location', 0 if none."""
    row = grid[0] if grid else []
    for i, v in enumerate(row, 1):
        if " ".join(str(v).split()).lower() == LOCATION:
            return i
    return 0


def reps(grid, col: int) -> List[tuple]:
    """[(row, name as written, current city)] for the rep block."""
    out = []
    for r in range(B.SUB_ROW + 1, B.last_rep_row(grid) + 1):
        name = B.cell(grid, r, B.NAME_COL).strip()
        if name:
            out.append((r, name, B.cell(grid, r, col).strip()))
    return out


def tidy_city(s: str) -> str:
    """'FORT WORTH' / 'fort worth ' -> 'Fort Worth'; 'mckinney' -> 'McKinney'."""
    words = " ".join(str(s or "").split()).title().split(" ")
    out = []
    for w in words:
        if len(w) > 2 and w.startswith("Mc"):
            w = "Mc" + w[2].upper() + w[3:]
        out.append(w)
    return " ".join(out).strip(" ,")


def _same(a: str, b: str) -> bool:
    k = lambda s: re.sub(r"[^a-z]", "", str(s).lower())  # noqa: E731
    return k(a) == k(b)


def _near(a: str, b: str) -> bool:
    """Same city spelled two ways ('Arlington' / 'Arlingotn')."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.8


def plan(rows: List[tuple], cities: Dict[str, str]):
    """(changes, missing). cities = {name as written: Blue Ink city or ''}.

    A TYPO IS NOT A MOVE. People misspell their own city on the packet too:
    the first look (2026-10-20) would have turned Hank Tran's 'Arlington' into
    Blue Ink's 'Arlingotn'. When the two are the same city spelled differently,
    the spelling that shows up more often across the board and Blue Ink wins
    (a tie goes to Blue Ink) -- so 'Mckinny' still becomes 'McKinney'."""
    seen: Dict[str, int] = {}
    for v in [now for _, _, now in rows] + list(cities.values()):
        v = tidy_city(v)
        if v:
            seen[v] = seen.get(v, 0) + 1
    changes, missing = [], []
    for r, name, now in rows:
        city = tidy_city(cities.get(name, ""))
        if not city:
            missing.append((r, name, now))
            continue
        if now and _near(now, city) and seen.get(tidy_city(now), 0) > seen.get(city, 0):
            city = tidy_city(now)
        if not _same(now, city):
            changes.append(Change(r, name, now, city))
    return changes, missing


def blueink_cities(names: List[str]) -> Dict[str, Dict[str, str]]:
    """{name as written: {'city', 'why'}} -- 'why' says why a city is missing.
    '(Wk 3)' / '(NC)' come off before matching; Blue Ink has the bare name."""
    from automations.apex_new_starts import blueink_data as BID
    bare = {n: base_name(n).strip() for n in names}
    found = BID.for_people(sorted(set(bare.values())))
    out = {}
    for n, b in bare.items():
        hire = found.get(b)
        if hire is None or hire.missing_packet:
            out[n] = {"city": "", "why": "no signed Blue Ink packet"}
        elif not hire.values.get("city"):
            out[n] = {"city": "", "why": "packet has no city"}
        else:
            out[n] = {"city": hire.values["city"], "why": ""}
    return out


def dm_text(title: str, blanks: List[tuple], why: Dict[str, str]) -> str:
    """The Tuesday ping: only the reps still WITHOUT a city after the fill.
    Empty string = nothing to ask anyone, so nothing is sent."""
    if not blanks:
        return ""
    lines = ["*%s* - %d rep%s still %s no city in *Location* and Blue Ink "
             "doesn't have it either. Please add it by hand:"
             % (title, len(blanks), "" if len(blanks) == 1 else "s",
                "has" if len(blanks) == 1 else "have")]
    lines += ["- %s (%s)" % (n, why.get(n) or "no signed Blue Ink packet")
              for _, n, _ in blanks]
    return "\n".join(lines)


def send_dm(text: str) -> str:
    """Group DM as Lucy (the user token on Lucy 2, as_bot=False on purpose --
    see reference_lucy-slack-identity). conversations_open is idempotent: the
    same three people get the same DM every week."""
    from automations.shared import slack_metrics_post as smp
    cl = smp._client()
    ch = cl.conversations_open(users=",".join(DM_USERS))["channel"]["id"]
    return cl.chat_postMessage(channel=ch, text=text).get("ts", "")


def _note_request(sheet_id: int, row: int, col: int, old_note: str,
                  before: str, after: str, when: str) -> dict:
    text = "Lucy (%s): city from Blue Ink. Was: %s." % (when, before or "blank")
    if old_note.strip():
        text = old_note.rstrip() + "\n\n" + text
    return {"updateCells": {
        "range": {"sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                  "startColumnIndex": col - 1, "endColumnIndex": col},
        "rows": [{"values": [{"note": text}]}], "fields": "note"}}


def apply(sh, ws, col: int, changes: List[Change]) -> List[Change]:
    """Write the cities. Rows whose rep moved since the read are skipped."""
    from gspread.utils import rowcol_to_a1
    names_now = ws.col_values(B.NAME_COL)
    todo = []
    for c in changes:
        now = names_now[c.row - 1].strip() if c.row - 1 < len(names_now) else ""
        if now == c.name:
            todo.append(c)
        else:
            print("  SALTEADA (la fila %d ya no es %s)" % (c.row, c.name))
    if not todo:
        return []
    ws.batch_update([{"range": rowcol_to_a1(c.row, col), "values": [[c.after]]}
                     for c in todo], value_input_option="USER_ENTERED")
    # A note only where something was REPLACED -- a blank that got its city
    # needs no explanation, a changed city does (and keeps the old one).
    replaced = [c for c in todo if c.before]
    if replaced:
        notes = _notes(sh, ws.title, col)
        when = dt.date.today().strftime("%m/%d")
        sh.batch_update({"requests": [
            _note_request(ws.id, c.row, col,
                          notes[c.row - 1] if c.row - 1 < len(notes) else "",
                          c.before, c.after, when)
            for c in replaced]})
    return todo


def _notes(sh, title: str, col: int) -> List[str]:
    from gspread.utils import rowcol_to_a1
    letter = re.sub(r"\d", "", rowcol_to_a1(1, col))
    data = sh.fetch_sheet_metadata({
        "ranges": ["'%s'!%s:%s" % (title, letter, letter)], "includeGridData": True,
        "fields": "sheets(data(rowData(values(note))))"})
    rows = data["sheets"][0]["data"][0].get("rowData", [])
    return [((rd.get("values") or [{}])[0] or {}).get("note", "") for rd in rows]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="escribir (backup antes)")
    ap.add_argument("--sheet-id", default=R.SHEET_ID)
    ap.add_argument("--date", help="YYYY-MM-DD dentro de la semana (default: hoy)")
    ap.add_argument("--no-dm", action="store_true",
                    help="no mandar el DM a Alisson + Evelyn")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    title = R.week_tabs(today)[0]

    sh = R._book(a.sheet_id)
    ws = sh.worksheet(title)
    grid = ws.get_all_values()
    col = location_col(grid)
    if not col:
        print("%s: no 'Location' column in row 1 -- nothing to do" % title)
        return 1
    rows = reps(grid, col)
    info = blueink_cities([n for _, n, _ in rows])
    changes, missing = plan(rows, {n: v["city"] for n, v in info.items()})

    print("%s: %d reps, %d blank, %d to write, %d not in Blue Ink"
          % (title, len(rows), sum(1 for _, _, v in rows if not v),
             len(changes), len(missing)))
    for c in changes:
        print("  %-32s %s -> %s" % (c.name, c.before or "(blank)", c.after))
    for _, n, now in missing:
        print("  SIN CIUDAD EN BLUE INK: %-32s (%s) board: %s"
              % (n, info[n]["why"], now or "(blank)"))

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    R.OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = R.OUT_DIR / ("city_%s.json" % stamp)
    payload = {"tab": title, "applied": a.apply,
               "changes": [c._asdict() for c in changes],
               "missing": [{"row": r, "name": n, "board": v, "why": info[n]["why"]}
                           for r, n, v in missing],
               "backup": {str(r): v for r, _, v in rows}}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("reporte + backup:", out)

    if a.apply and changes:
        done = apply(sh, ws, col, changes)
        print("  escritas: %d" % len(done))
    blanks = [m for m in missing if not m[2]]
    text = dm_text(title, blanks, {n: v["why"] for n, v in info.items()})
    if text and a.apply and not a.no_dm and a.sheet_id == R.SHEET_ID and not a.date:
        try:
            print("  DM Alisson + Evelyn:", send_dm(text))
        except Exception as e:  # noqa: BLE001 -- the board is already fixed
            print("  DM falló: %s: %s" % (type(e).__name__, str(e)[:200]))
    elif text:
        print("  DM (no se manda en esta corrida):\n" + text)
    if a.apply and a.sheet_id == R.SHEET_ID and not a.date:
        # a step on the Sales Board card, like the rest of the fixer
        R.hub_phase(HUB_PHASE, "Lucy Salesboard Fixer — rep cities", True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
