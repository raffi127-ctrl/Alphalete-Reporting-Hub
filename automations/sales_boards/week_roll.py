"""Vantura Master Sales Board - roll the board onto the new week.

THREE BOARDS, ONE ROLL (2026-10-02): the reps live on three per-campaign tabs
with identical geometry - "NDS Sales Board" (the AT&T program, NDS on the
sheet since 2026-10-03), "BOX Sales Board" and "Verizon Sales Board" (see
automations/vantura_boards.py). Every step below runs over all three, except
the flip: the gold week cell is B2 on "NDS Sales Board" only (the other two
read it with ='NDS Sales Board'!$B$2), so WeekData!J:K, the gold cell and its
dropdown are written once, on the main tab.

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
  3. LAST WK, PER CAMPAIGN - col D on each board's subtotal row (AT&T NDS /
     BOX / Verizon). Their C neighbours are SUMIFS, but these are HAND-TYPED
     literals, so nothing else moves them; they are copied from what C showed
     before the reset.
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
from automations.sales_boards.run import SHEET_ID
from automations.sales_boards.zeros import we_label
from automations.vantura_boards import (BOARD_TABS, MAIN_TAB as BOARD,
                                        READ_RANGE, board_ws, is_stat_label)

WEEKDATA, STATIONS = "WeekData", "Stations"
WE_CELL = "B2"                  # gold week selector
STATIONS_WE = "Q2"              # Stations' week label (S2 until the 9/3 re-layout dropped two columns)
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
    """One board tab's shape, read once and found by LABEL - the header row's
    own titles. Templates get rows inserted; indices don't survive that.

    `campaign` is the tab's campaign ('NDS' / 'BOX' / 'Verizon') and `tab` its
    title; both ride along into the snapshot so a rolled-forward render can
    put each rep back on the board they came from."""

    def __init__(self, grid, campaign: str = "", tab: str = ""):
        self.grid = grid
        self.campaign, self.tab = campaign, tab
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

        # Rep rows run from the header down to the first TOTALS LABEL in the
        # name column ("AT&T NDS" / "BOX" / "Verizon" - the row that opens
        # the subtotal block; the pre-rename "AT&T (B2B)" still counts, see
        # vantura_boards.STAT_LABELS). NOT to the first row without a '#': the
        # subtotal rows carry one too (48/49/50 on the live boards). NOT to
        # the first blank row either: a cleared row inside the block is
        # skipped, not a stop (2026-09-14 that stop saw 6 reps of 46).
        self.reps = []
        r = self.hdr_row + 1
        while r <= len(grid) and not is_stat_label(self.cell(r, self.c_name)):
            if self.cell(r, self.c_name):
                self.reps.append(self.read_row(r))
            r += 1
        if not self.reps:
            raise SystemExit("no rep rows found under row %d%s"
                             % (self.hdr_row, " on %s" % tab if tab else ""))

        # Then the campaign subtotal (one per board now), down to TOTAL or the
        # blank line under it. Bounded on purpose: the stats block further
        # down also carries campaign names ('Apps', the headcount table), and
        # writing 'Last Wk' into one of those rows would land on somebody's
        # data. Keyed by the BOARD's campaign - the Verizon subtotal row has
        # no label in col L, so the row's own campaign cell can't be the key.
        self.campaigns = {}
        while r <= len(grid):
            name = self.cell(r, self.c_name)
            if not name or name.upper() == "TOTAL":
                break
            row = self.read_row(r)
            self.campaigns[campaign or row["campaign"] or name] = row
            r += 1

    def cell(self, r: int, c: int) -> str:
        row = self.grid[r - 1] if len(self.grid) >= r else []
        return str(row[c - 1]).strip() if len(row) >= c else ""

    def read_row(self, r: int) -> dict:
        return {"row": r, "name": self.cell(r, self.c_name),
                "days": [self.cell(r, c) for c in self.c_days],
                "this_wk": self.cell(r, self.c_this),
                "last_wk": self.cell(r, self.c_last),
                "campaign": self.cell(r, self.c_camp),
                "tab": self.tab}

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


def archived_reps(keys, label: str) -> int:
    """How many WeekData rows are keyed to `label`."""
    return sum(1 for k in keys if k.rsplit("|", 1)[-1].strip() == label)


def read_boards(sh) -> dict:
    """{campaign: Board} for the three tabs. All three must exist: rolling
    some of the boards and not the others would leave reps on two different
    weeks, so a missing tab stops the roll before anything is written."""
    out = {}
    for camp, tab in BOARD_TABS.items():
        try:
            # today's title first, then the one the board had before the
            # 2026-10-03 rename (vantura_boards.LEGACY_TABS)
            ws = board_ws(sh, camp)
        except Exception as e:  # noqa: BLE001 — WorksheetNotFound and kin
            raise SystemExit("no %r tab on the sheet (%s) - every board rolls "
                             "together, so refusing to roll any of them."
                             % (tab, type(e).__name__))
        out[camp] = Board(_retry(ws.get, READ_RANGE), campaign=camp,
                          tab=ws.title)
    return out


def audit_rolled(boards, wd, sunday) -> int:
    """The gold cell is on today's week - but was it ROLLED, or did somebody
    just pick the week from the dropdown?

    Picking is the whole failure: it moves the label and NOTHING else, so last
    week's typed numbers stay under this week's headers (the fill only ever
    raises a number, so they are never corrected down), the closing week is
    never archived, and 'Last Wk' still shows an older week. That is how
    2026-08-17 went, and it looks exactly like a healthy board. Saying
    "nothing to do" here would let it stand, so: check that the week BEFORE
    this one made it into WeekData, and if it didn't, say what to do.

    `boards` is the three Boards (any iterable of them)."""
    reps = [r for b in boards for r in b.reps]
    keys = [k.strip() for k in _retry(wd.col_values, 1) if k.strip()]
    prev = we_label(sunday - dt.timedelta(days=7))
    n_prev, n_this = archived_reps(keys, prev), archived_reps(keys, we_label(sunday))
    if n_prev or not keys or n_this:
        print("the board is already rolled (%s archived with %d rows). "
              "Nothing to do." % (prev, n_prev))
        return 0

    literals = [r["name"] for r in reps if any(v for v in r["days"])]
    print("\n!! ROLLED BY HAND? Week %s is on the gold cell, but %s has NO "
          "archived rows in WeekData." % (we_label(sunday), prev))
    print("   That is what picking the week from the dropdown leaves behind: "
          "the label moves and nothing else does.")
    if literals:
        print("   %d rep row(s) still carry typed day numbers (%s%s) - if "
              "those are %s's, the fill will never take them down."
              % (len(literals), ", ".join(literals[:4]),
                 ", ..." if len(literals) > 4 else "", prev))
    print("   To fix: type the OLD week back into the gold cell as TEXT (an "
          "apostrophe first, e.g. '%s), then run this again." % prev)
    return 4


def _poke_rollcall_flip():
    """The Roll Call flips in the same breath as the board (Carlos 2026-09-18:
    "those two things always work together and update together"). Hit the
    bound-script web app so rollCallNewWeek() runs NOW; its 9am/11am Apps
    Script triggers stay as idempotent backstops. The web-app URL is
    machine-local (vantura-payroll-webapp.json, gitignored). Never raises."""
    try:
        import json as _json
        import pathlib as _pl
        import requests as _rq
        cfg = _pl.Path(__file__).resolve().parents[2] / "vantura-payroll-webapp.json"
        url = _json.loads(cfg.read_text()).get("webapp_url", "")
        if not url:
            print("  roll-call flip: no web-app config (9am trigger will cover)")
            return
        r = _rq.get(url, params={"action": "rollcallflip"}, timeout=300)
        print(f"  roll-call flip: {r.text[:120]}")
    except Exception as e:  # noqa: BLE001
        print(f"  roll-call flip poke failed ({type(e).__name__}: {e}) "
              "- the 9am trigger will cover it")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Roll the Vantura Sales Boards "
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
    sb = board_ws(sh, BOARD)
    wd, st = (_retry(sh.worksheet, t) for t in (WEEKDATA, STATIONS))

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
    # The three boards, read up front: both the audit and the roll need them,
    # and a tab that is missing has to stop everything (read_boards).
    boards = read_boards(sh)
    for camp, b in boards.items():
        print("%s: %d rep rows (%d-%d); campaign subtotal: %s"
              % (b.tab, len(b.reps), b.reps[0]["row"], b.reps[-1]["row"],
                 ", ".join("%s = row %d" % (c, r["row"])
                           for c, r in sorted(b.campaigns.items(),
                                              key=lambda kv: kv[1]["row"]))
                 or "none"))
    if old_we == today_label:
        print("that IS the week holding today (%s)." % today)
        return audit_rolled(boards.values(), wd, old_sunday)
    if new_we != today_label and not args.force:
        print("but today (%s) sits in week %s, not %s. Rolling one week would "
              "leave the board on the wrong week - re-run with --force if that "
              "is really what you want." % (today, today_label, new_we))
        return 2

    tabs = {camp: _retry(sh.worksheet, b.tab) for camp, b in boards.items()}
    all_reps = [r for b in boards.values() for r in b.reps]

    if not any(r["days"][6] for r in all_reps):
        msg = ("SUNDAY is blank for all %d reps - the 5:00am pass that closes "
               "the week may not have run yet, and archiving now would store "
               "the week a day short." % len(all_reps))
        if not args.force:
            print("\n!! %s\n   Re-run with --force if Sunday really was a zero."
                  % msg)
            return 2
        print("\n!! %s\n   --force given, continuing." % msg)

    # ------------------------------------------------------------- 1. archive
    have = set(k.strip() for k in _retry(wd.col_values, 1))
    new_rows = []
    for r in all_reps:
        key = "%s|%s" % (r["name"], old_we)
        if key in have:
            continue                 # already archived - or on two boards
        have.add(key)
        new_rows.append([key] + [as_number(v) for v in r["days"]])
    print("\n1. archive %s: %d new WeekData row(s), %d already there"
          % (old_we, len(new_rows), len(all_reps) - len(new_rows)))
    for row in new_rows[:3]:
        print("     e.g.", row)

    # --------------------------------------------------- 2. 'Last Wk' per rep
    # Per board: each one is its own range on its own tab.
    d_writes = {}                    # camp -> (range, values)
    print("\n2. 'Last Wk' <- each rep's %s total:" % old_we)
    for camp, b in boards.items():
        d_rng = b.rng(b.c_last)
        d_vals = [[as_number(r["this_wk"])] for r in b.reps]
        changed = sum(1 for r, v in zip(b.reps, d_vals)
                      if str(v[0]) != r["last_wk"])
        d_writes[camp] = (d_rng, d_vals)
        print("     %s!%s (%d of %d change)"
              % (b.tab, d_rng, changed, len(b.reps)))

    # ---------------------------------------------- 3. 'Last Wk' per campaign
    camp_writes = [(camp, b, r)
                   for camp, b in boards.items()
                   for _c, r in sorted(b.campaigns.items(),
                                       key=lambda kv: kv[1]["row"])]
    print("\n3. 'Last Wk' on the campaign subtotals (hand-typed literals - the "
          "roll is the only thing that moves them):")
    for camp, b in boards.items():
        if not b.campaigns:
            # Forgetting these is exactly how the board sat on 145/66 (week
            # 8.23) after the 9.6 roll, so say it out loud instead of
            # skipping in silence.
            print("     !! %s: no subtotal row found under the reps - if the "
                  "board HAS one, its 'Last Wk' will stay on the old week."
                  % b.tab)
    for camp, b, r in camp_writes:
        print("     %s!%s%d  %-14s %s -> %s"
              % (b.tab, a1(b.c_last), r["row"], camp, r["last_wk"] or "(blank)",
                 r["this_wk"] or "0"))

    # -------------------------------------------- 4. day cells back to formula
    day_rngs = {camp: b.rng(b.c_days[0], b.c_days[-1])
                for camp, b in boards.items()}
    print("\n4. reset the day cells to the INDEX formula:")
    for camp, b in boards.items():
        literals = sum(1 for r in b.reps for v in r["days"] if v != "")
        print("     %s!%s (%d literal cell(s) today)"
              % (b.tab, day_rngs[camp], literals))

    # ------------------------------------------------------------- 5. the flip
    keep = [w for w in weeks if w[0] != new_we][:PICKER_ROWS - 1]
    new_jk = ([[float(new_we), (new_sunday - EPOCH).days]]
              + [[j, (sun - EPOCH).days] for _, sun, j in keep])
    labels = [new_we] + [l for l, _, _ in keep]
    print("\n5. WeekData!J2:K%d <- %s / %s on top, the rest shifted down"
          % (len(new_jk) + 1, new_we, new_sunday))
    print("   %s!%s <- TEXT %r (RAW); the other boards' B2 read it by formula"
          % (sb.title, WE_CELL, new_we))
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
        "weekdata_JK": picker, "reps": all_reps,
        "campaigns": {camp: r for camp, _b, r in camp_writes},
        "tabs": {camp: b.tab for camp, b in boards.items()},
    }, indent=1), encoding="utf-8")
    print("\nsnapshot -> %s" % snap_path)

    if new_rows:
        _retry(wd.append_rows, new_rows, value_input_option="USER_ENTERED",
               table_range="A1")
        print("WROTE %d archive row(s) into %s" % (len(new_rows), WEEKDATA))

    for camp, (d_rng, d_vals) in d_writes.items():
        _retry(tabs[camp].update, values=d_vals, range_name=d_rng,
               value_input_option="USER_ENTERED")
        print("WROTE %s!%s" % (boards[camp].tab, d_rng))

    for camp, b, r in camp_writes:
        cell = "%s%d" % (a1(b.c_last), r["row"])
        _retry(tabs[camp].update, values=[[as_number(r["this_wk"] or 0)]],
               range_name=cell, value_input_option="USER_ENTERED")
        print("WROTE %s!%s (%s = %s)" % (b.tab, cell, camp, r["this_wk"] or 0))

    for camp, b in boards.items():
        _retry(tabs[camp].update,
               values=[b.day_formulas(r["row"]) for r in b.reps],
               range_name=day_rngs[camp], value_input_option="USER_ENTERED")
        print("WROTE %s!%s (formulas)" % (b.tab, day_rngs[camp]))

    # The safety check: still on the old week, so every board has to read
    # back the same values off its own archive.
    bad = []
    for camp, b in boards.items():
        back = _retry(tabs[camp].get, day_rngs[camp])
        rows = {r["row"]: r for r in b.reps}
        first = b.reps[0]["row"]
        for i, got in enumerate(list(back) + [[]] * len(b.reps)):
            r = rows.get(first + i)
            if r is None:
                continue             # a blank row inside the block
            got = [str(x).strip() for x in (list(got) + [""] * 7)[:7]]
            if got != r["days"]:
                bad.append((b.tab, r["name"], r["days"], got))
    if bad:
        print("\n!! %d rep row(s) do NOT read back the same after the reset - "
              "the archive did not take. STOPPING BEFORE THE FLIP; %s is still "
              "what the board shows, nothing is lost." % (len(bad), old_we))
        for tab, name, was, got in bad[:8]:
            print("   %-16s %-28s was %s -> now %s" % (tab, name, was, got))
        return 3
    print("OK - all %d rep rows on %d boards read back identical off the %s "
          "archive" % (len(all_reps), len(boards), old_we))

    _retry(wd.update, values=new_jk, range_name="J2:K%d" % (len(new_jk) + 1),
           value_input_option="USER_ENTERED")
    _retry(wd.format, "K2:K%d" % (len(new_jk) + 1),
           {"numberFormat": {"type": "DATE"}})
    print("WROTE WeekData!J2:K%d" % (len(new_jk) + 1))

    _retry(sb.update, values=[[new_we]], range_name=WE_CELL,
           value_input_option="RAW")
    we_range = {"sheetId": sb.id, "startRowIndex": 1, "endRowIndex": 2,
                "startColumnIndex": 1, "endColumnIndex": 2}
    # Writing RAW keeps OUR value a string, but a HUMAN picking off the dropdown
    # enters USER_ENTERED, and Sheets parses "9.20" into the number 9.2 - the
    # lost zero that reads exactly like a board nobody rolled. Pinning the cell
    # to TEXT is what makes the pick safe; the list values alone never were.
    _retry(sh.batch_update, {"requests": [
        {"setDataValidation": {
            "range": we_range,
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": l}
                                              for l in labels]},
                     "showCustomUi": True, "strict": False}}},
        {"repeatCell": {
            "range": we_range,
            "cell": {"userEnteredFormat":
                     {"numberFormat": {"type": "TEXT"}}},
            "fields": "userEnteredFormat.numberFormat"}},
    ]})
    print("WROTE %s!%s = %r (text, cell pinned to TEXT) + dropdown list"
          % (BOARD, WE_CELL, new_we))

    _retry(st.update, values=[[new_we]], range_name=STATIONS_WE,
           value_input_option="RAW")
    print("WROTE Stations!%s = %r" % (STATIONS_WE, new_we))

    # ---------------------------------------------------------------- verify
    _poke_rollcall_flip()
    print("\n--- after ---")
    print("%s: %r | Stations!%s: %r"
          % (WE_CELL, _retry(sb.acell, WE_CELL).value, STATIONS_WE,
             _retry(st.acell, STATIONS_WE).value))
    print("headers:", _retry(sb.get, "C2:K3"))
    for camp, b in boards.items():
        tot = _retry(tabs[camp].get, b.rng(b.c_this, b.c_last))
        print("%s 'This Wk' non-zero rows:" % b.tab,
              [t[0] for t in tot if t and str(t[0]).strip() not in ("", "0")]
              or "none - clean")
        print("%s 'Last Wk' first 5:" % b.tab,
              [t[1] if len(t) > 1 else "" for t in tot[:5]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
