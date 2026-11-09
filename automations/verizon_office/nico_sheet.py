"""Nico's own Sales Board ('Verizon Reporting and Sales') kept filled off the
same Slack tally Lucy already reads (verizon_office.slack_tally).

Nico 2026-11-09 asked for his board to get filled out. His 'Sales Board' tab is
all formulas: per rep per day it shows the HIGHEST 'Included' NL counter on the
hidden 'Slack Team Tallies' tab (A date, B rep, C counter, H status; rows from
5), for the week picked in B2. Something outside the Hub filled that tab in two
batches (11/4, 11/7) and stopped -- newest row a Nov 6 sale.

What this does: for each tally post in #alphalete-gp-sales, every rep whose
count beats what the tab already holds for that day gets ONE appended row in
the tab's own shape (A:K). Append only: nothing on his sheet is edited or
cleared, his corrections block (M:O) wins on his board as before, and a stale
repost with a lower number adds nothing.

Names are written the way HIS board spells them (Sales Board column B): the
list name is matched through his tab's own 'Source Row Label' history
(jair -> Jair Otero, gio -> Giovanni Monreal ...), then first name / surname
against the board. A name that matches nobody or 2+ reps is reported, never
guessed.

Shared with alphaletereporting@ only, so it runs on LUCY 4, inside the 5-minute
tally job (slack_tally.tick).

  python -m automations.verizon_office.nico_sheet                       # dry run, today
  python -m automations.verizon_office.nico_sheet --date 2026-11-07 --write
  python -m automations.verizon_office.nico_sheet --snapshot DIR       # dry run off CSVs
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.verizon_office import slack_tally as T

SHEET_ID = "1DOITkoe7FUBPTPMeiN9yviXF90EMI6bE28xqB100emE"
BOARD_TAB = "Sales Board"
TALLY_TAB = "Slack Team Tallies"
FIRST_ROW = 5                       # the board's formulas read A5:A2000
METHOD = "blood_drop_counter"


def _norm_date(v: str) -> Optional[dt.date]:
    v = (v or "").strip()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    return None


def board_names(board_rows: List[List[str]]) -> List[str]:
    """Rep names in column B under the '#' / 'REP' header."""
    out, started = [], False
    for r in board_rows:
        b = (r[1] if len(r) > 1 else "").strip()
        if b.upper() == "REP":
            started = True
            continue
        if started and b and (r[0].strip().isdigit() if r else False):
            out.append(b)
    return out


def label_aliases(tally_rows: List[List[str]]) -> Dict[str, str]:
    """Source Row Label (G) -> Rep (B) from the tab's own history."""
    seen: Dict[str, set] = {}
    for r in tally_rows[FIRST_ROW - 1:]:
        if len(r) > 6 and r[1].strip() and r[6].strip():
            seen.setdefault(r[6].strip().lower(), set()).add(r[1].strip())
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def match(name: str, names: List[str], aliases: Dict[str, str]) -> Tuple[Optional[str], str]:
    key = name.strip().lower()
    if key in aliases and aliases[key] in names:
        return aliases[key], ""
    hits = [n for n in names if key in [w.lower() for w in n.split()]]
    first = [n for n in hits if n.split()[0].lower() == key]
    pick = first if len(first) == 1 else hits
    if len(pick) == 1:
        return pick[0], ""
    return None, "%s (%s)" % (name, "no match" if not pick else "matches " + ", ".join(pick))


def current_max(tally_rows: List[List[str]]) -> Dict[Tuple[dt.date, str], int]:
    best: Dict[Tuple[dt.date, str], int] = {}
    for r in tally_rows[FIRST_ROW - 1:]:
        if len(r) < 8 or r[7].strip() != "Included":
            continue
        d = _norm_date(r[0])
        try:
            n = int(float(r[2]))
        except ValueError:
            continue
        if d and r[1].strip():
            k = (d, r[1].strip())
            best[k] = max(best.get(k, 0), n)
    return best


def plan(day: dt.date, msgs: List[dict], board_rows, tally_rows,
         now: Optional[dt.datetime] = None) -> Tuple[List[List[str]], List[str]]:
    """Rows to append for `day` (oldest post first), and unmatched names."""
    names = board_names(board_rows)
    aliases = label_aliases(tally_rows)
    best = current_max(tally_rows)
    observed = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
    rows, problems = [], []
    for m in sorted(msgs, key=lambda m: float(m["ts"])):
        when = dt.datetime.fromtimestamp(float(m["ts"]), dt.timezone.utc)
        text = m.get("text", "")
        if T.sales_day(when) != day or not T.is_tally(text):
            continue
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        url = "https://ao-pbns.slack.com/archives/%s/p%s" % (T.CHANNEL, m["ts"].replace(".", ""))
        for label, n in T.parse(text).items():
            rep, why = match(label, names, aliases)
            if not rep:
                if why not in problems:
                    problems.append(why)
                continue
            if n <= best.get((day, rep), 0):
                continue
            best[(day, rep)] = n
            rows.append([day.isoformat(), rep, str(n), m["ts"], url, m.get("user", ""),
                         label.lower(), "Included", observed, sha, METHOD])
    return rows, problems


def _open():
    from automations.recruiting_report.fill import open_by_key
    return open_by_key(SHEET_ID)


def sync(days: List[dt.date], *, write: bool, snapshot: Optional[Path] = None, log=print) -> int:
    if snapshot:
        board_rows = list(csv.reader(open(snapshot / "board.csv", encoding="utf-8")))
        tally_rows = list(csv.reader(open(snapshot / "tallies.csv", encoding="utf-8")))
        ws = None
    else:
        from automations.recruiting_report.fill import _retry
        sh = _open()
        board_rows = _retry(lambda: sh.worksheet(BOARD_TAB).get_all_values())
        ws = sh.worksheet(TALLY_TAB)
        tally_rows = _retry(lambda: ws.get_all_values())
    total = 0
    for day in days:
        rows, problems = plan(day, T.fetch_raw(day), board_rows, tally_rows)
        log("[nico sheet] %s: %d new row(s)" % (day, len(rows)))
        for r in rows:
            log("   %-30s %s" % (r[1], r[2]))
        for p in problems:
            log("   ⚠ not on his board: " + p)
        if rows and write and ws is not None:
            from automations.recruiting_report.fill import _retry
            # under the last filled A cell, A:K only -- his M:O corrections
            # share these rows, so no insert / table append that could shift them
            last = max([i for i, r in enumerate(tally_rows, 1) if r and r[0].strip()] + [FIRST_ROW - 1])
            top = last + 1
            if ws.row_count < top + len(rows):
                _retry(lambda: ws.add_rows(top + len(rows) - ws.row_count + 50))
            _retry(lambda: ws.update(range_name="A%d:K%d" % (top, top + len(rows) - 1),
                                     values=rows, value_input_option="USER_ENTERED"))
            tally_rows = tally_rows + rows
            total += len(rows)
    if write and ws is not None:
        log("[nico sheet] wrote %d row(s) to '%s'" % (total, TALLY_TAB))
    else:
        log("[nico sheet] DRY RUN -- nothing written")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", help="YYYY-MM-DD (repeatable; default today's sales day)")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--snapshot", type=Path, help="dir with board.csv + tallies.csv (dry run, no sheet access)")
    a = ap.parse_args(argv)
    days = [dt.date.fromisoformat(d) for d in a.date] if a.date else \
        [T.sales_day(dt.datetime.now(dt.timezone.utc))]
    return sync(days, write=a.write and not a.snapshot, snapshot=a.snapshot)


if __name__ == "__main__":
    sys.exit(main())
