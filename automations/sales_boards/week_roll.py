"""Vantura Master Sales Board - roll the board onto the new week.

The board holds ONE week at a time. On Monday the 5:00am pass closes SUNDAY and
the 4:00pm pass fills MONDAY, which already belongs to the NEXT week - so the
board has to be rolled in between, or the fill HOLDS (exit 75) and every held
day then needs its own `--date` catch-up run.

Neither `vantura_slack_sales` nor `sales_boards` rolls the board itself, on
purpose: the day cells E:K start life as
    =IFERROR(INDEX(WeekData!$<B..H>$2:$...$5000,
             MATCH($B<row>&"|"&$B$2, WeekData!$A$2:$A$5000,0)),"")
and turn into LITERALS as the fill writes them, so flipping the gold cell alone
leaves a MIXED board - last week's typed numbers under this week's headers, and
the fill only ever RAISES a number, so they would never be corrected down.

A full roll is five things, in this order:

  1. ARCHIVE the closing week into `WeekData` - one row per rep on the board,
     key `<REP>|<WE>`, cols B..H = Mon..Sun exactly as displayed (markers and
     blanks verbatim: that is how every earlier week is stored).
  2. LAST WK - col D of each rep row gets that rep's closing-week total (= col
     C today, which is =SUM(E:K)).
  3. LAST WK, PER CAMPAIGN - col D on the AT&T (B2B) and BOX totals rows. Their
     C neighbours are SUMIFS, but these two are HAND-TYPED literals, so nothing
     else moves them; they are copied from what C showed before the reset.
  4. RESET the day cells back to the INDEX formula. With the gold cell still on
     the OLD week the board must render IDENTICALLY (it now reads its own
     archive) - that equality is the safety check, and the roll stops there
     rather than flip if it fails, leaving the old week intact.
  5. FLIP the week: WeekData!J:K gains the new week on top (AS3 reads the real
     Sunday from there), the gold cell becomes the TEXT label, its dropdown is
     rebuilt, and Stations!S2 follows (its two New-Start FILTERs compare $S$2
     against Roll Call col A).

The gold cell is written as TEXT with RAW on purpose: as a NUMBER, Sheets drops
a trailing zero and 8.30 comes back 8.3 - which broke the gate, the AS3 date
anchor and every WeekData key on 2026-08-24. The dropdown is rebuilt off the
SUNDAY DATES in WeekData!K for the same reason: a label rendered from the number
in J comes back "9.2" for the week ending 9/20, and picking that would key every
day cell `<REP>|9.2` while the fill writes `<REP>|9.20`.

The T / F / X day markers are NOT carried forward. They are hand-typed per week
(Nico Murrugarra: F for 8.9 and 8.16, real numbers for 8.23, F again for 8.30),
and headcount counts every cell that is non-blank and not "F", so a stale "T"
would put terminated reps into the new week's roster before the week starts.
Blank is the correct start-of-week state.

    python -m automations.sales_boards.week_roll            # dry run
    python -m automations.sales_boards.week_roll --apply    # write

Rolls onto the week that contains TODAY, from the week the board is showing.
`--week 9.13` names the target explicitly; `--force` is needed when the target
is not today's week (rolling early, or catching up more than one week behind),
or when the closing week's Sunday is blank for everyone.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from automations.recruiting_report.fill import open_by_key, _retry
from automations.sales_boards.run import SHEET_ID, TAB as BOARD
from automations.sales_boards.zeros import we_label

WEEKDATA, STATIONS = "WeekData", "Stations"
WE_CELL = "B2"                  # gold week selector
STATIONS_WE = "S2"              # Stations' copy of the same week label
WD_DAY_COLS = "BCDEFGH"         # WeekData Mon..Sun, parallel to the board's E..K
PICKER_ROWS = 11                # weeks kept in WeekData!J:K (and the dropdown)
EPOCH = dt.date(1899, 12, 30)   # Sheets serial 0

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]
HDR_NAME, HDR_THIS, HDR_LAST, HDR_CAMPAIGN = ("REP", "Current Week", "Last Wk",
                                              "Campaign")
HDR_NUM = "#"                   # the rep numbering; blank on the totals rows
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "sales_boards"


def a1(col: int) -> str:
    """1 -> 'A'. Rows and columns are found by label, never hardcoded, so the
    writes have to spell their own ranges."""
    s = ""
    while col:
        col, r = divmod(col - 1, 26)
        s = chr(65 + r) + s
    return s


def as_number(v):
    """'7' -> 7, '' / 'X' / 'T' -> unchanged. Keeps the archive typed the way
    every earlier week is typed, so ISNUMBER() in the stats rows still holds."""
    s = str(v).strip()
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    return s


def sunday_of(serial):
    """A Sheets date serial -> date, or None if the cell isn't one."""
    try:
        return EPOCH + dt.timedelta(days=int(serial))
    except (TypeError, ValueError):
        return None


class Board:
    """The board's shape, read once and found by LABEL - the header row's own
    titles and its '#' column. Templates get rows inserted; indices don't
    survive that."""

    def __init__(self, grid):
        self.grid = grid
        self.hdr_row = next((i for i in range(1, len(grid) + 1)
                             for c in range(1, len(grid[i - 1]) + 1)
                             if self.cell(i, c) == HDR_NAME), 0)
        if not self.hdr_row:
            raise SystemExit("no %r header anywhere - is this the board?"
                             % HDR_NAME)
        hdr = {self.cell(self.hdr_row, c).lower(): c
               for c in range(1, len(grid[self.hdr_row - 1]) + 1)}
        try:
            self.c_name = hdr[HDR_NAME.lower()]
            self.c_this = hdr[HDR_THIS.lower()]
            self.c_last = hdr[HDR_LAST.lower()]
            self.c_camp = hdr[HDR_CAMPAIGN.lower()]
            self.c_days = [hdr[d.lower()] for d in DAYS]
        except KeyError as e:
            raise SystemExit("row %d has no %s column - the board's headers "
                             "changed." % (self.hdr_row, e))
        self.c_num = hdr.get(HDR_NUM, max(1, self.c_name - 1))
        if self.c_days != list(range(self.c_days[0], self.c_days[0] + 7)):
            raise SystemExit("Mon..Sun are not seven adjacent columns: %s"
                             % self.c_days)

        # Rep rows carry a '#' and run unbroken from the header down; the
        # first row without one ends the block.
        self.reps = []
        r = self.hdr_row + 1
        while (r <= len(grid) and self.cell(r, self.c_num)
               and self.cell(r, self.c_name)):
            self.reps.append(self.read_row(r))
            r += 1
        if not self.reps:
            raise SystemExit("no rep rows found under row %d" % self.hdr_row)

        # Then the campaign subtotals, down to TOTAL or the blank line under it.
        # Bounded on purpose: the stats block further down also carries campaign
        # names in col L ('Apps', the headcount table), and writing 'Last Wk'
        # into one of those rows would land on somebody's data.
        rep_camps = set(x["campaign"] for x in self.reps if x["campaign"])
        self.campaigns = {}
        while r <= len(grid):
            name = self.cell(r, self.c_name)
            if not name or name.upper() == "TOTAL":
                break
            row = self.read_row(r)
            if row["campaign"] in rep_camps:
                self.campaigns[row["campaign"]] = row
            r += 1

    def cell(self, r: int, c: int) -> str:
        row = self.grid[r - 1] if len(self.grid) >= r else []
        return str(row[c - 1]).strip() if len(row) >= c else ""

    def read_row(self, r: int) -> dict:
        return {"row": r, "name": self.cell(r, self.c_name),
                "days": [self.cell(r, c) for c in self.c_days],
                "this_wk": self.cell(r, self.c_this),
                "last_wk": self.cell(r, self.c_last),
                "campaign": self.cell(r, self.c_camp)}

    def day_formulas(self, row: int) -> list:
        """The seven day cells as they are born - INDEX into WeekData, keyed on
        REP|<gold cell>."""
        name = "$%s%d" % (a1(self.c_name), row)
        gold = "$%s$%s" % (WE_CELL[0], WE_CELL[1:])
        return ['=IFERROR(INDEX(WeekData!$%s$2:$%s$5000,'
                'MATCH(%s&"|"&%s,WeekData!$A$2:$A$5000,0)),"")'
                % (c, c, name, gold) for c in WD_DAY_COLS]

    def rng(self, col: int, last_col=None) -> str:
        """A1 range over the rep rows for one column, or a span of them."""
        first, last = self.reps[0]["row"], self.reps[-1]["row"]
        return "%s%d:%s%d" % (a1(col), first, a1(last_col or col), last)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Roll the Vantura Sales Board "
                                             "onto the new week.")
    ap.add_argument("--apply", action="store_true",
                    help="write (default: dry run, nothing is touched)")
    ap.add_argument("--week", metavar="M.D",
                    help="target week ending (default: the week holding today)")
    ap.add_argument("--force", action="store_true",
                    help="roll even when the target is not today's week, or "
                         "the closing week's Sunday is blank for everyone")
    args = ap.parse_args(argv)

    sh = open_by_key(SHEET_ID)
    sb, wd, st = (_retry(sh.worksheet, t) for t in (BOARD, WEEKDATA, STATIONS))

    shown = str(_retry(sb.acell, WE_CELL).value or "").strip()
    picker = [r for r in _retry(wd.get, "J2:K%d" % (PICKER_ROWS + 1),
                                value_render_option="UNFORMATTED_VALUE") if r]

    # A week is SPELLED off its Sunday DATE in K, never off the number in J:
    # 9.20 is stored 9.2 and no amount of formatting gets the zero back.
    weeks = []
    for row in picker:
        sun = sunday_of(row[1] if len(row) > 1 else None)
        if sun:
            weeks.append((we_label(sun), sun, row[0]))
    if not weeks:
        print("WeekData!J:K has no week with a real Sunday date - stop.")
        return 2

    by_label = dict((lbl, sun) for lbl, sun, _ in weeks)
    old_sunday = by_label.get(shown)
    if old_sunday is None:                   # a lost trailing zero: 8.30 -> 8.3
        old_sunday = next((sun for _, sun, j in weeks
                           if str(j).strip() == shown), None)
    if old_sunday is None:
        print("the gold cell reads %r, which is no week in WeekData!J:K (%s) - "
              "refusing to guess."
              % (shown, ", ".join(l for l, _, _ in weeks)))
        return 2

    today = dt.date.today()
    today_label = we_label(today)
    next_sunday = old_sunday + dt.timedelta(days=7)
    if args.week:
        new_sunday = by_label.get(args.week)
        if new_sunday is None and we_label(next_sunday) == args.week:
            new_sunday = next_sunday
        if new_sunday is None:
            print("--week %s is neither a week in WeekData nor the one after "
                  "%s (%s) - stop."
                  % (args.week, we_label(old_sunday), we_label(next_sunday)))
            return 2
    else:
        new_sunday = next_sunday
    old_we, new_we = we_label(old_sunday), we_label(new_sunday)

    print("board shows %s (week ending %s); rolling to %s (week ending %s)"
          % (old_we, old_sunday, new_we, new_sunday))
    if old_we == today_label:
        print("that IS the week holding today (%s) - the board is already "
              "rolled. Nothing to do." % today)
        return 0
    if new_we != today_label and not args.force:
        print("but today (%s) sits in week %s, not %s. Rolling one week would "
              "leave the board on the wrong week - re-run with --force if that "
              "is really what you want." % (today, today_label, new_we))
        return 2

    grid = _retry(sb.get, "A1:Z60")
    b = Board(grid)
    print("%d rep rows (%d-%d); campaign totals: %s"
          % (len(b.reps), b.reps[0]["row"], b.reps[-1]["row"],
             ", ".join("%s = row %d" % (c, r["row"])
                       for c, r in sorted(b.campaigns.items(),
                                          key=lambda kv: kv[1]["row"]))
             or "none"))

    if not any(r["days"][6] for r in b.reps):
        msg = ("SUNDAY is blank for all %d reps - the 5:00am pass that closes "
               "the week may not have run yet, and archiving now would store "
               "the week a day short." % len(b.reps))
        if not args.force:
            print("\n!! %s\n   Re-run with --force if Sunday really was a zero."
                  % msg)
            return 2
        print("\n!! %s\n   --force given, continuing." % msg)

    # ------------------------------------------------------------- 1. archive
    have = set(k.strip() for k in _retry(wd.col_values, 1))
    new_rows = [["%s|%s" % (r["name"], old_we)] + [as_number(v) for v in r["days"]]
                for r in b.reps if "%s|%s" % (r["name"], old_we) not in have]
    print("\n1. archive %s: %d new WeekData row(s), %d already there"
          % (old_we, len(new_rows), len(b.reps) - len(new_rows)))
    for row in new_rows[:3]:
        print("     e.g.", row)

    # --------------------------------------------------- 2. 'Last Wk' per rep
    d_rng = b.rng(b.c_last)
    d_vals = [[as_number(r["this_wk"])] for r in b.reps]
    changed = sum(1 for r, v in zip(b.reps, d_vals) if str(v[0]) != r["last_wk"])
    print("\n2. 'Last Wk' %s <- each rep's %s total (%d of %d change)"
          % (d_rng, old_we, changed, len(b.reps)))

    # ---------------------------------------------- 3. 'Last Wk' per campaign
    camp_writes = sorted(b.campaigns.items(), key=lambda kv: kv[1]["row"])
    print("\n3. 'Last Wk' on the campaign totals (hand-typed literals - the "
          "roll is the only thing that moves them):")
    if not camp_writes:
        # Forgetting these is exactly how the board sat on 145/66 (week 8.23)
        # after the 9.6 roll, so say it out loud instead of skipping in silence.
        print("     !! none found under the reps - if the board HAS campaign "
              "subtotal rows, their 'Last Wk' will stay on the old week.")
    for camp, r in camp_writes:
        print("     %s%d  %-14s %s -> %s"
              % (a1(b.c_last), r["row"], camp, r["last_wk"] or "(blank)",
                 r["this_wk"] or "0"))

    # -------------------------------------------- 4. day cells back to formula
    day_rng = b.rng(b.c_days[0], b.c_days[-1])
    literals = sum(1 for r in b.reps for v in r["days"] if v != "")
    print("\n4. reset %s to the INDEX formula (%d literal cell(s) today)"
          % (day_rng, literals))

    # ------------------------------------------------------------- 5. the flip
    keep = [w for w in weeks if w[0] != new_we][:PICKER_ROWS - 1]
    new_jk = ([[float(new_we), (new_sunday - EPOCH).days]]
              + [[j, (sun - EPOCH).days] for _, sun, j in keep])
    labels = [new_we] + [l for l, _, _ in keep]
    print("\n5. WeekData!J2:K%d <- %s / %s on top, the rest shifted down"
          % (len(new_jk) + 1, new_we, new_sunday))
    print("   %s <- TEXT %r (RAW)" % (WE_CELL, new_we))
    print("   dropdown <- %s" % ", ".join(labels))
    print("   Stations!%s <- TEXT %r (was %r)"
          % (STATIONS_WE, new_we,
             str(_retry(st.acell, STATIONS_WE).value or "")))

    if not args.apply:
        print("\nDRY RUN - nothing written. Re-run with --apply.")
        return 0

    # ------------------------------------------------------------------ write
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = OUT_DIR / ("week_roll_%s_to_%s_%s.json"
                           % (old_we, new_we, today.isoformat()))
    snap_path.write_text(json.dumps({
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "sheet_id": SHEET_ID, "from_week": old_we, "to_week": new_we,
        WE_CELL: shown,
        "stations_S2": str(_retry(st.acell, STATIONS_WE).value or ""),
        "weekdata_JK": picker, "reps": b.reps, "campaigns": b.campaigns,
    }, indent=1), encoding="utf-8")
    print("\nsnapshot -> %s" % snap_path)

    if new_rows:
        _retry(wd.append_rows, new_rows, value_input_option="USER_ENTERED",
               table_range="A1")
        print("WROTE %d archive row(s) into %s" % (len(new_rows), WEEKDATA))

    _retry(sb.update, values=d_vals, range_name=d_rng,
           value_input_option="USER_ENTERED")
    print("WROTE %s" % d_rng)

    for camp, r in camp_writes:
        cell = "%s%d" % (a1(b.c_last), r["row"])
        _retry(sb.update, values=[[as_number(r["this_wk"] or 0)]],
               range_name=cell, value_input_option="USER_ENTERED")
        print("WROTE %s (%s = %s)" % (cell, camp, r["this_wk"] or 0))

    _retry(sb.update, values=[b.day_formulas(r["row"]) for r in b.reps],
           range_name=day_rng, value_input_option="USER_ENTERED")
    print("WROTE %s (formulas)" % day_rng)

    # The safety check: still on the old week, so the board has to read back
    # the same values off its own archive.
    back = _retry(sb.get, day_rng)
    bad = []
    for r, got in zip(b.reps, list(back) + [[]] * len(b.reps)):
        got = [str(x).strip() for x in (list(got) + [""] * 7)[:7]]
        if got != r["days"]:
            bad.append((r["name"], r["days"], got))
    if bad:
        print("\n!! %d rep row(s) do NOT read back the same after the reset - "
              "the archive did not take. STOPPING BEFORE THE FLIP; %s is still "
              "what the board shows, nothing is lost." % (len(bad), old_we))
        for name, was, got in bad[:8]:
            print("   %-28s was %s -> now %s" % (name, was, got))
        return 3
    print("OK - all %d rep rows read back identical off the %s archive"
          % (len(b.reps), old_we))

    _retry(wd.update, values=new_jk, range_name="J2:K%d" % (len(new_jk) + 1),
           value_input_option="USER_ENTERED")
    _retry(wd.format, "K2:K%d" % (len(new_jk) + 1),
           {"numberFormat": {"type": "DATE"}})
    print("WROTE WeekData!J2:K%d" % (len(new_jk) + 1))

    _retry(sb.update, values=[[new_we]], range_name=WE_CELL,
           value_input_option="RAW")
    _retry(sh.batch_update, {"requests": [{"setDataValidation": {
        "range": {"sheetId": sb.id, "startRowIndex": 1, "endRowIndex": 2,
                  "startColumnIndex": 1, "endColumnIndex": 2},
        "rule": {"condition": {"type": "ONE_OF_LIST",
                               "values": [{"userEnteredValue": l}
                                          for l in labels]},
                 "showCustomUi": True, "strict": False}}}]})
    print("WROTE %s = %r (text) + dropdown list" % (WE_CELL, new_we))

    _retry(st.update, values=[[new_we]], range_name=STATIONS_WE,
           value_input_option="RAW")
    print("WROTE Stations!%s = %r" % (STATIONS_WE, new_we))

    # ---------------------------------------------------------------- verify
    print("\n--- after ---")
    print("%s: %r | Stations!%s: %r"
          % (WE_CELL, _retry(sb.acell, WE_CELL).value, STATIONS_WE,
             _retry(st.acell, STATIONS_WE).value))
    print("headers:", _retry(sb.get, "C2:K3"))
    tot = _retry(sb.get, b.rng(b.c_this, b.c_last))
    print("'This Wk' non-zero rows:",
          [t[0] for t in tot if t and str(t[0]).strip() not in ("", "0")]
          or "none - clean")
    print("'Last Wk' first 5:", [t[1] if len(t) > 1 else "" for t in tot[:5]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
