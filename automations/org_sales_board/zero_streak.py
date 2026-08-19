"""Who has gone cold — the detector half of the two-week zero rule.

THE RULE (Eve, 2026-08-19): a rep who closes TWO consecutive weeks at a literal
0 comes off that campaign's boxes. This module finds them; `roster_remove.py`
does the removing and `distro_remove.py` takes them off the mailing groups.

SCOPED PER CAMPAIGN, NEVER PER PERSON. Reps switch campaigns: someone who
stopped selling BOX and now sells Retail Internet must lose the BOX rows and
KEEP the Internet ones. So the streak is counted inside each box separately, and
a rep who is cold in one box while selling in another is reported as
`ACTIVO EN OTRA` — a warning that they must not go into `roster_sync.EXCLUDE`,
which is board-wide.

WHERE THE NUMBERS COME FROM: each leaderboard's `WE m.d` columns, which hold the
per-rep weekly totals. Columns D.. are LITERALS (only col C, the live week, is a
formula), so history is stable and a closed week reads the same tomorrow.

THREE THINGS THAT ARE NOT A ZERO:

  * the LIVE week — it is still filling, so it is skipped entirely. The board
    rolls on TUESDAY (week.py), which is why the live week is derived from
    `reporting_sunday` rather than from "the first column".
  * a BLANK — no data is not a zero. A new hire with no history simply has no
    streak; without this rule every rep's first week on the board would look
    like the start of one. Reported separately as `sin historial`.
  * a rep already in EXCLUDE — they were removed in an earlier pass and only
    still appear if someone re-added them by hand.

    python -m automations.org_sales_board.zero_streak              # report
    python -m automations.org_sales_board.zero_streak --weeks 3    # stricter
    python -m automations.org_sales_board.zero_streak --commands   # + the removal cmds
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.recruiting_report.fill import open_by_key, _retry     # noqa: E402
from automations.org_sales_board.run import SHEET_ID, SANDBOX_TAB      # noqa: E402
from automations.org_sales_board import week as wk                     # noqa: E402
from automations.org_sales_board import roster_sync                    # noqa: E402
from automations.org_sales_board.roster_remove import (                # noqa: E402
    text, norm, _blank, _owner_above, END_LABELS, WE_RE)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = Path(__file__).resolve().parents[2] / "output"
DEFAULT_WEEKS = 2


def _md(label: str):
    m = re.match(r"^WE\s+(\d{1,2})\.(\d{1,2})$", str(label).strip(), re.I)
    return (int(m.group(1)), int(m.group(2))) if m else None


def parse_we(label: str, today: dt.date):
    """'WE 08.16' -> the date, guessing the year as the one nearest today.

    ⚠ ONLY safe for the FIRST (newest) column. The headers carry no year and the
    long leaderboards reach ~2 years back, so 'WE 8.17' is Aug 2025 while
    nearest-year would read it as two days ago. Everything else must go through
    `week_dates`."""
    md = _md(label)
    if not md:
        return None
    mo, da = md
    best = None
    for y in (today.year - 2, today.year - 1, today.year, today.year + 1):
        try:
            d = dt.date(y, mo, da)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def week_dates(labels: list, today: dt.date) -> list:
    """Dates for a leaderboard's WE headers, POSITIONALLY.

    The columns are a strictly weekly descending run, so only the first one needs
    a year guess: every later column is exactly 7 days earlier. Each label is
    then CHECKED against that date, and the run stops at the first mismatch
    rather than guessing — a wrong year here silently breaks a real streak
    (an old 'WE 8.17' column read as two days ago is non-zero, so the walk
    stops and a cold rep looks active)."""
    if not labels:
        return []
    first = parse_we(labels[0], today)
    if not first:
        return []
    out = [first]
    for i, lab in enumerate(labels[1:], start=1):
        d = first - dt.timedelta(days=7 * i)
        if _md(lab) != (d.month, d.day):
            break
        out.append(d)
    return out


def num(v):
    """A number, or None for a blank / non-numeric cell. `0` must survive as a
    real 0 — the whole rule turns on telling it apart from empty."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").replace(",", "").replace("$", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_boxes(grid, today: dt.date) -> list:
    """Every leaderboard section as
    {owner, section, weeks:[(date, col)], reps:[{row, name, vals{date:num}}]}.

    Found the same way as everywhere else on this tab: a row carrying >=2
    'WE m.d' headers opens a leaderboard, a col-A label with an empty col B
    opens a section inside it, and the section ends at TOTALS."""
    out = []
    for r in range(len(grid)):
        cols = [(c, text(grid, r, c)) for c in range(len(grid[r]))
                if WE_RE.match(text(grid, r, c))]
        if len(cols) < 2:
            continue
        dates = week_dates([lab for _c, lab in cols], today)
        weeks = sorted(zip(dates, [c for c, _l in cols]), reverse=True)
        owner, sec, rr = _owner_above(grid, r), "", r + 1
        while rr < len(grid) and not _blank(grid, rr):
            a, b = text(grid, rr, 0), text(grid, rr, 1)
            if a and not b and a.lower() not in END_LABELS:
                sec = a
                out.append({"owner": owner, "section": sec, "weeks": weeks, "reps": []})
            elif b and a.lower() not in END_LABELS and out:
                out[-1]["reps"].append({
                    "row": rr + 1, "name": b,
                    "vals": {d: num(grid[rr][c] if c < len(grid[rr]) else "")
                             for d, c in weeks}})
            rr += 1
    return [b for b in out if b["reps"]]


def streak(vals: dict, closed: list) -> int:
    """Consecutive closed weeks at a literal 0, newest first. A blank STOPS the
    count — it is missing data, not a zero, and counting it would manufacture a
    streak for anyone whose history simply doesn't reach that far back."""
    n = 0
    for d in closed:
        if vals.get(d) == 0:
            n += 1
        else:
            break
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="org_sales_board.zero_streak")
    ap.add_argument("--weeks", type=int, default=DEFAULT_WEEKS,
                    help=f"closed weeks at 0 to flag on (default {DEFAULT_WEEKS})")
    ap.add_argument("--tab", default=SANDBOX_TAB)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, for a past run")
    ap.add_argument("--commands", action="store_true",
                    help="also print the roster_remove / distro_remove commands")
    ap.add_argument("--csv", default=None, help="output path (default output/…)")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()

    ws = _retry(lambda: open_by_key(SHEET_ID).worksheet(args.tab))
    grid = _retry(lambda: ws.get("A1:ZZ2200", value_render_option="UNFORMATTED_VALUE")) or []
    boxes = read_boxes(grid, today)
    if not boxes:
        print("no se encontró ningún leaderboard — ¿cambió el tab?")
        return 1

    live_sun = wk.reporting_sunday(today)
    all_weeks = sorted({d for b in boxes for d, _c in b["weeks"]}, reverse=True)
    closed = [d for d in all_weeks if d < live_sun]
    print(f"=== zero_streak — {args.tab!r} — {today:%Y-%m-%d %a}")
    print(f"    semana viva WE {live_sun:%m.%d} (se ignora) · "
          f"cerradas más recientes: {', '.join(f'WE {d:%m.%d}' for d in closed[:4])}")
    print(f"    umbral: {args.weeks} semana(s) cerradas en 0\n")

    # The guard against pulling a rep who just CHANGED campaigns: where is this
    # person still selling RIGHT NOW? Recent means the live week or the last
    # closed one — a positive number from two years ago says nothing about
    # whether they moved, and counting it would flag every veteran as "active".
    recent = [d for d in ([live_sun] + closed[:1])]
    active = set()
    for b in boxes:
        for rep in b["reps"]:
            if any((rep["vals"].get(d) or 0) > 0 for d in recent):
                active.add((norm(rep["name"]), b["owner"], b["section"]))
    active_names = {n for n, _o, _s in active}
    excluded = {norm(x) for x in roster_sync.EXCLUDE}

    flags, newbies, rows = [], [], []
    for b in boxes:
        box_closed = [d for d, _c in b["weeks"] if d < live_sun]
        for rep in b["reps"]:
            key = norm(rep["name"])
            n = streak(rep["vals"], box_closed)
            if n < args.weeks:
                continue
            ever = [d for d in box_closed if (rep["vals"].get(d) or 0) > 0]
            item = {"name": rep["name"], "row": rep["row"], "owner": b["owner"],
                    "section": b["section"], "streak": n,
                    "last_sale": f"WE {ever[0]:%m.%d}" if ever else "—",
                    # OTHER boxes only — a rep is always "active" in the box
                    # being judged if they ever sold there, and listing it makes
                    # the warning self-referential.
                    "elsewhere": sorted({f"{o}/{s}" for nm, o, s in active
                                         if nm == key
                                         and (o, s) != (b["owner"], b["section"])}),
                    "excluded": key in excluded}
            (newbies if not ever and key not in active_names else flags).append(item)

    def show(items, title):
        if not items:
            return
        print(f"--- {title}")
        for f in sorted(items, key=lambda x: (-x["streak"], x["name"])):
            tag = "  [YA EN EXCLUDE]" if f["excluded"] else ""
            warn = ("  ⚠ ACTIVO EN OTRA: " + ", ".join(f["elsewhere"])
                    if f["elsewhere"] else "")
            print(f"  {f['name'][:22]:<22} {f['owner'][:24]:<25} {f['section'][:26]:<26} "
                  f"{f['streak']:>2} sem · últ. venta {f['last_sale']:<9} r{f['row']}{tag}{warn}")
        print()

    show(flags, f"CANDIDATOS A BAJA ({len(flags)} fila(s))")
    show(newbies, f"SIN HISTORIAL DE VENTAS — decidir a mano ({len(newbies)} fila(s))")
    if not flags and not newbies:
        print("nadie llega al umbral. Nada que hacer.\n")

    for f in flags + newbies:
        rows.append({k: (", ".join(v) if isinstance(v, list) else v)
                     for k, v in f.items()})
    if rows:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = Path(args.csv) if args.csv else OUT_DIR / f"org_board_zero_streak_{today}.csv"
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"CSV: {out}")

    if args.commands:
        # Only people cold EVERYWHERE can be excluded board-wide; someone still
        # selling another campaign gets their rows removed but must NOT be
        # excluded, or the self-heal would refuse to keep the campaign they sell.
        clean = sorted({f["name"] for f in flags
                        if not f["elsewhere"] and not f["excluded"]})
        mixed = sorted({f["name"] for f in flags if f["elsewhere"]})
        if clean:
            names = "|".join(clean)
            print(f"\n1) agregá a roster_sync.EXCLUDE y a all_campaigns_board.roster.EXCLUDE:")
            for n in clean:
                print(f'     "{n}",')
            print(f'\n2) python -m automations.org_sales_board.roster_remove --names "{names}"'
                  f'   # sacá --dry-run agregando --apply')
            print(f'3) python -m automations.all_campaigns_board.roster_remove --names "{names}" --apply')
            print(f"4) actualizá REMOVALS en distro_remove.py y corré --apply")
        if mixed:
            print(f"\n⚠ estos cambiaron de campaña — borrar SOLO su caja fría, "
                  f"SIN EXCLUDE: {', '.join(mixed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
