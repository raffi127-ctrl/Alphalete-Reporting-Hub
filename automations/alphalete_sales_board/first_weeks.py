"""Move this week's 1st weeks from the 'New Starts/Raf' box up onto the board.

Eve 2026-11-22: *"el viernes al final del día agregá todos los 1st weeks (que no
estén ya en el cuadro superior, porque a veces los agrega el equipo en la
semana porque ya tienen ventas) ... con toda la información completa"*.

Until now Eve did this by hand every Friday, and on 11/20 six of them landed
with no Trainer (Raf, #admin-staff-local-office 11/22: "why maybe the trainer
doesn't transfer over?"). The box HAD the trainers -- the copy lost them.

WHO MOVES UP. Everyone in the box who is NOT marked Terminated anywhere in the
week (same rule as Apex New Starts: `apex_new_starts.board.to_add`). The box's
strike-through is NOT the rule: Kimberly Arreaga was struck on 11/22 with
'Off'/'O-NA' days and no Terminated, and she is a working 1st week.

ALREADY ON THE BOARD. The team adds people mid-week once they sell, and the
5-minute sweep adds any rep who sells with no row. A box name is "already
there" when it matches a roster row once nicknames and (Wk n) tags are
dropped. A CLOSE-but-not-equal name (same surname, or a typo away) is NOT
added -- it is reported, because a duplicate row splits a rep's numbers.

WHAT GETS FILLED, by ROW-1 LABEL (never by index):
  Trainer            full name from the roster ('Bas' -> 'Bas El Hassan');
                     the box's own text when it matches nobody (better than a
                     blank -- that blank is what Raf flagged)
  Field Status       1st Wk
  Campaign           the trainer's own Campaign; ATT when that's empty
  Team               the box's Team; else the trainer's team
  Leadership Status  In Training
  Start Date         their CR day (the week's Monday when no CR)
  Location / Email   from the box, when it has them
For somebody ALREADY on the board only EMPTY cells are written -- a value a
person typed is never replaced.

    python -m automations.alphalete_sales_board.first_weeks            # preview
    python -m automations.alphalete_sales_board.first_weeks --apply
    python -m automations.alphalete_sales_board.first_weeks --sheet <test id> --tab "SANDBOX — Sales Board WE 11.22"
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from typing import Dict, List, Optional, Tuple

from automations.alphalete_sales_board import config as C
from automations.alphalete_sales_board import fill as F
from automations.apex_new_starts import board as AB
from automations.rep_sales_fill import board as B

FIELD_STATUS = "1st Wk"
LEADERSHIP = "In Training"
CAMPAIGN_DEFAULT = "ATT"     # every box 1st week on WE 11.15 + 11.22 reads ATT

# row-1 labels on the board -> the value's key below
BOARD_COLS = ("Trainer", "Field Status", "Campaign", "Team", "Leadership Status",
              "Start Date", "Location", "Email")


def _label_cols(grid) -> Dict[str, int]:
    width = max((len(r) for r in grid[:3]), default=0)
    out: Dict[str, int] = {}
    for c in range(1, width + 1):
        label = " ".join(B.cell(grid, 1, c).split())
        if label in BOARD_COLS and label not in out:
            out[label] = c
    return out


def _variants(name: str) -> List[str]:
    """'Alexis (Lexi) Justice' -> ['alexis justice', 'lexi justice']."""
    out = [B._norm_name(name)]
    m = re.match(r"^\s*(\S+)\s*\(([^)]+)\)\s*(.*)$", name or "")
    if m and m.group(3).strip():
        nick = B._norm_name("%s %s" % (m.group(2), m.group(3)))
        if nick and nick not in out:
            out.append(nick)
    return [v for v in out if v]


def board_match(grid, name: str) -> Tuple[Optional[int], List[str]]:
    """(row already holding this person, near names worth a look)."""
    last = B.last_rep_row(grid)
    rows = {r: B._norm_name(B.cell(grid, r, B.NAME_COL))
            for r in range(B.SUB_ROW + 1, last + 1)
            if B.cell(grid, r, B.NAME_COL).strip()}
    for v in _variants(name):
        hit = [r for r, n in rows.items() if n == v]
        if len(hit) == 1:
            return hit[0], []
    return None, _near(name, [B.cell(grid, r, B.NAME_COL).strip() for r in rows])


def _near(name: str, board_names: List[str]) -> List[str]:
    """Board names that could be this SAME person under another spelling.

    Stricter than fill.near_matches, which refuses on a shared surname alone:
    that is right for a SaraPlus name (often one word, often a nickname), but
    the box lists real first + last names, and a cohort shares surnames all
    the time -- 'Ailonnie Moore' is not 'Kaniyah Moore' (11/22 dry run). So:
    the whole name a typo away, OR the same surname AND a first name that is
    close ('Mike'/'Michael', 'Jovani'/'Jovanni')."""
    import difflib
    out = []
    for v in _variants(name):
        w = v.split()
        for b in board_names:
            n = B._norm_name(b)
            t = n.split()
            if not t or not w or b in out:
                continue
            whole = difflib.SequenceMatcher(None, v, n).ratio() >= 0.85
            first = difflib.SequenceMatcher(None, w[0], t[0]).ratio()
            if whole or (w[-1] == t[-1] and (first >= 0.75 or t[0].startswith(w[0])
                                             or w[0].startswith(t[0]))):
                out.append(b)
    return out


def trainer_details(grid, box_trainer: str, cols: Dict[str, int]
                    ) -> Tuple[str, str, str, str]:
    """(trainer to write, their team, their campaign, note)."""
    raw = " ".join((box_trainer or "").split())
    if not raw:
        return "", "", "", "no trainer in the box"
    full, trow, why = F.roster_match(grid, raw)
    if not full and "Trainer" in cols:
        # Trainers who are not reps themselves (Bas El Hassan, an owner) have
        # no roster row -- but the board's own Trainer column already spells
        # them out on other rows. A UNIQUE full spelling that starts with what
        # the box wrote is that person.
        k = B._norm_name(raw)
        seen = {" ".join(B.cell(grid, r, cols["Trainer"]).split())
                for r in range(B.SUB_ROW + 1, B.last_rep_row(grid) + 1)}
        seen = {s for s in seen if s and "/" not in s}
        hits = sorted(s for s in seen if B._norm_name(s) == k
                      or B._norm_name(s).startswith(k + " "))
        if len(hits) == 1:
            return hits[0], "", "", ""
    if not full:
        return raw, "", "", "trainer %r kept as the box wrote it (%s)" % (raw, why)
    team = B.cell(grid, trow, cols["Team"]).strip() if "Team" in cols else ""
    camp = B.cell(grid, trow, cols["Campaign"]).strip() if "Campaign" in cols else ""
    return full, team, camp, ""


def wanted_values(grid, cand, cols: Dict[str, int]) -> Tuple[Dict[str, str], List[str]]:
    trainer, t_team, t_camp, note = trainer_details(grid, cand.trainer, cols)
    start = cand.hire_date
    vals = {
        "Trainer": trainer,
        "Field Status": FIELD_STATUS,
        "Campaign": t_camp or CAMPAIGN_DEFAULT,
        "Team": (cand.team or "").strip() or t_team,
        "Leadership Status": LEADERSHIP,
        "Start Date": ("%d/%d/%d" % (start.month, start.day, start.year)) if start else "",
        "Location": (cand.location or "").strip(),
        "Email": (cand.email or "").strip(),
    }
    return {k: v for k, v in vals.items() if v and k in cols}, ([note] if note else [])


def came_back(cand) -> str:
    """'' or why this Terminated person needs Eve (Eve 2026-11-22).

    TERMINATED ANYWHERE IN THE WEEK = they don't go up; the box's strike-through
    is not read (a person can strike somebody by mistake). Days left BLANK
    after the Terminated are the usual thing -- whoever terminated them didn't
    copy it across -- so those still count as terminated. But a REAL roll call
    after it ('Terminated' Wed, 'Here' Thu) contradicts it: ask Eve, don't guess.
    """
    term = cand.term_day
    if term is None:
        return ""
    later = [(d, v) for d, v in sorted(cand.roll.items())
             if d > term and (v or "").strip() and not AB._is_terminated(v)]
    if not later:
        return ""
    d, v = later[0]
    return "Terminated on %s but %r on %s" % (
        AB.DAY_NAMES[term], v.strip(), AB.DAY_NAMES[d])


def plan(grid, people) -> Dict[str, list]:
    """{'add': [(cand, values)], 'complete': [(cand, row, {col: value})],
        'doubt': [str], 'skipped': [str]}"""
    cols = _label_cols(grid)
    missing = [c for c in ("Trainer", "Field Status", "Team") if c not in cols]
    if missing:
        raise RuntimeError("board has no %s column on row 1" % ", ".join(missing))
    add_list, skipped = AB.to_add(people)
    out = {"add": [], "complete": [], "doubt": [], "skipped": []}
    for p, why in skipped:
        back = came_back(p)
        if back:
            out["doubt"].append("%s NOT added -- %s. Terminated or still working?"
                                % (p.name, back))
        else:
            out["skipped"].append("%s (%s)" % (p.name, why))
    for p in add_list:
        vals, notes = wanted_values(grid, p, cols)
        row, near = board_match(grid, p.name)
        if row:
            empty = {cols[k]: v for k, v in vals.items()
                     if not B.cell(grid, row, cols[k]).strip()}
            if empty:
                out["complete"].append((p, row, empty))
                if cols["Trainer"] in empty:
                    out["doubt"] += ["%s: %s" % (p.name, n) for n in notes]
            continue
        out["doubt"] += ["%s: %s" % (p.name, n) for n in notes]
        if near:
            out["doubt"].append("%s NOT added -- could be %s already on the board"
                                % (p.name, " or ".join(near[:2])))
            continue
        out["add"].append((p, vals))
    return out


def _board_name(name: str) -> str:
    from automations.shared import name_case
    return name_case.titlecase_name(" ".join(name.split()))


def apply(ws, grid, p: dict) -> List[str]:
    """Write the plan. Returns notes. Re-reads after each add: the board
    re-sorts through the day, so a row number from before is not trusted."""
    notes: List[str] = []
    ups = [{"range": F._a1(row, c), "values": [[v]]}
           for _p, row, cells in p["complete"] for c, v in cells.items()]
    if ups:
        ws.batch_update(ups, value_input_option="USER_ENTERED")
    for cand, vals in p["add"]:
        name = _board_name(cand.name)
        row, why = F.add_rep(ws, grid, name)
        if row is None:
            notes.append("%s NOT added: %s" % (name, why))
            break                         # no blank rows left for anyone after
        grid = ws.get_all_values()
        cols = _label_cols(grid)
        row2, _ = B.find_rep_row(grid, name)
        row2 = row2 or row
        ws.batch_update([{"range": F._a1(row2, cols[k]), "values": [[v]]}
                         for k, v in vals.items()], value_input_option="USER_ENTERED")
        grid = ws.get_all_values()
    return notes


def summary(tab: str, p: dict) -> List[str]:
    lines = []
    for cand, vals in p["add"]:
        lines.append("ADD %s -- %s" % (cand.name, ", ".join(
            "%s=%s" % (k, v) for k, v in vals.items())))
    for cand, row, cells in p["complete"]:
        lines.append("FILL row %d %s -- %d empty cell(s): %s" % (
            row, cand.name, len(cells), ", ".join(cells.values())))
    lines += ["CHECK " + d for d in p["doubt"]]
    lines += ["skip " + s for s in p["skipped"]]
    return lines


def tell_eve(tab: str, lines: List[str]) -> None:
    """No Hub card: what happened (and what needs a person) goes to Eve by DM."""
    try:
        from automations.shared import slack_metrics_post as smp
        from automations.sales_board_fixer.run import EVE_USER_ID
        client = smp._client()
        if "lucy" not in client.auth_test().get("user", "").lower():
            print("! this machine does not post as Lucy -- no DM")
            return
        text = "Sales Board - 1st weeks moved up (%s):\n" % tab + "\n".join(
            "- " + n for n in lines)
        ch = client.conversations_open(users=EVE_USER_ID)["channel"]["id"]
        client.chat_postMessage(channel=ch, text=text)
        print("  DM to Eve")
    except Exception as e:  # noqa: BLE001 -- the DM never hides the exit code
        print("! DM to Eve failed: %s" % e)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write (default: preview)")
    ap.add_argument("--sheet", help="test copy: this sheet id instead of the real board")
    ap.add_argument("--tab", help="this tab instead of this week's 'Sales Board WE'")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today, Central)")
    a = ap.parse_args(argv)
    if a.today:
        today = dt.date.fromisoformat(a.today)
    else:
        from zoneinfo import ZoneInfo
        today = dt.datetime.now(ZoneInfo("America/Chicago")).date()
    from automations.recruiting_report.fill import open_by_key
    from automations.terminated_reps import board as BD
    sheet = a.sheet or C.SPREADSHEET_ID
    sh = open_by_key(sheet)
    tab = a.tab or BD.pick_tab(sh, today)
    ws = sh.worksheet(tab)
    grid = ws.get_all_values()
    people = AB.read_box(grid, tab, today)
    p = plan(grid, people)
    print("1st weeks -> board (%s) on %r, %d in the box:" % (
        "APPLY" if a.apply else "preview", tab, len(people)))
    lines = summary(tab, p)
    for ln in lines or ["nothing to do -- every 1st week is already on the board, complete"]:
        print("  " + ln)
    if not a.apply:
        return 0
    notes = apply(ws, grid, p)
    for n in notes:
        print("  ! " + n)
    real = [l for l in lines if not l.startswith("skip ")] + notes
    if real and not a.sheet:
        tell_eve(tab, real)
    return 1 if notes else 0


if __name__ == "__main__":
    sys.exit(main())
