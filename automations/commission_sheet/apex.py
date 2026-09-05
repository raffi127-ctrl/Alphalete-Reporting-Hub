"""Step 11 — enter the week's payroll in Apex.

JD's last chore: once the week is approved, each person's Got Paid figure goes
into Apex under Payroll -> Payroll Entry.

WHERE THE NUMBERS COME FROM. `Raf PNL 2026`, the week's `Got Paid` column — not
the commission workbook. That is the column JD names, it is what step 10 has
just written, and it is the only place the non-rep lines exist at all. Reading
it live also honours his rule that a figure he corrects after approving is the
figure that gets entered.

WHO GOES WHERE. Most rows are commission adjustments. A few are not:

    "Bas Partner Pay and Owl Partner Pay and Willie Partner Pay all go in the
     bonuses."

House lines are marked by a TEAM beginning `A - `, and there are four:
`A - Partner Pay`, `A - Chef`, `A - Food Cost`, `A - Sales Manager`. Only the
first is confidently a bonus — the rest are NOT entered without JD saying so,
for two reasons found in the data:

  * `A - Chef` and `A - Food Cost` are not people. They are house costs sitting
    in the P&L, and there is nobody in Apex to pay them to.
  * `A - Sales Manager` holds BOTH Basil Elhassan and JD himself, and they are
    not treated alike. JD's own line exists for P&L only — "I'm not on there,
    I just put mine on there just for keeping track of PL purposes" — so
    entering his $1,500 would pay someone who is not on Apex payroll.

So team routing decides nothing on its own here. An unrecognised house team is
EXCLUDED and reported, never guessed into a payroll box.

WHY THIS ONE CANNOT RUN UNATTENDED. Apex is not a system an automated login can
reach, so this rides the session JD already has in his own Chrome and never
handles a credential. He clicks Run in the Hub while signed in; on a login page
the run STOPS and reports rather than asking for anything.

    python -m automations.commission_sheet.apex             # the plan, no browser
    python -m automations.commission_sheet.apex --probe     # is JD's session live?
    python -m automations.commission_sheet.apex --explore   # map the entry form
    python -m automations.commission_sheet.apex --write     # enter it

WHERE THE LOGIN HAS TO LIVE. Every run deletes its Chrome profile and rebuilds
it by copying JD's EVERYDAY Chrome (`rm -rf` then rsync from
~/Library/Application Support/Google/Chrome). So a code typed into the window
the automation opens is thrown away on the next run and wasted. The login must
be done in JD's normal Chrome, on the machine that will run the Hub — once
there, every future run re-copies it.

UNTESTED AGAINST APEX. The plan half below is verified against real data; the
browser half is adapted from `apex_payroll` (built for Lucy 2) and has NOT been
run on JD's machine. A human Chrome already running is a known hazard there —
see reference_browser_profile_collisions — so `--probe` first, always.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from automations.commission_sheet import config as C
from automations.commission_sheet.pnl import (FIRST_REP_ROW, _num, banner_for,
                                              col_letter)
from automations.commission_sheet.names import nrm

#: A team beginning with this is a house line, not an ordinary rep.
HOUSE_TEAM_PREFIX = "a - "

#: House teams JD has confirmed go into Apex, and where. Anything else marked
#: `A - ` is excluded pending his word — the safe direction for payroll.
HOUSE_ROUTING: Dict[str, str] = {
    "a - partner pay": "bonuses",
}

#: Named lines that are never entered, whatever their team. JD's own row is
#: P&L bookkeeping, not pay (his Loom, 2026-09-03).
NEVER_ENTER = {"jd mascorro", "joshua mascorro"}


@dataclass
class Entry:
    row: int
    name: str
    team: str
    amount: float
    note: str = ""


@dataclass
class Plan:
    week: dt.date
    banner: str
    paid_col: str
    entries: List[Entry] = field(default_factory=list)   # commission adjustments
    bonuses: List[Entry] = field(default_factory=list)   # confirmed house lines
    excluded: List[Entry] = field(default_factory=list)  # NOT entered — needs JD
    skipped: List[Entry] = field(default_factory=list)   # no payout this week

    @property
    def total(self) -> float:
        return sum(e.amount for e in self.entries + self.bonuses)


def _last_sunday(today: Optional[dt.date] = None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def plan(week: Optional[dt.date] = None,
         all_in_one_id: str = C.ALL_IN_ONE_ID) -> Plan:
    """Read the week's Got Paid column and split it by destination."""
    from automations.recruiting_report.fill import open_by_key
    week = week or _last_sunday()
    ws = open_by_key(all_in_one_id).worksheet(C.TAB_YEAR_PNL)

    banner = banner_for(week)
    header = ws.get("A1:GZ1")[0]
    hits = [i for i, c in enumerate(header) if nrm(c) == nrm(banner)]
    if len(hits) != 1:
        have = [c for c in header if str(c).strip().upper().startswith("WE ")]
        raise KeyError(f"{banner!r} matched {len(hits)} banner(s) on "
                       f"{C.TAB_YEAR_PNL}. Weeks present: {have}")
    paid_col = col_letter(hits[0] + 1)          # Brought In, Got Paid, P/L

    people = ws.get(f"A{FIRST_REP_ROW}:F600")
    # Stop where column A stops: below the rep block the tab holds other
    # sections whose E/F names would otherwise be read as people.
    last = max((i for i, r in enumerate(people)
                if str((list(r) + [""])[0]).strip()), default=-1)
    people = people[:last + 1]
    paid = ws.get(f"{paid_col}{FIRST_REP_ROW}:{paid_col}{FIRST_REP_ROW + last}")

    p = Plan(week=week, banner=banner, paid_col=paid_col)
    for off, raw in enumerate(people):
        row = FIRST_REP_ROW + off
        cells = list(raw) + [""] * 6
        team = str(cells[1]).strip()
        name = " ".join(x for x in (str(cells[4]).strip(),
                                    str(cells[5]).strip()) if x)
        value = (list(paid[off]) + [""])[0] if off < len(paid) else ""
        amount = _num(value)
        if not name:
            continue
        e = Entry(row=row, name=name, team=team, amount=amount or 0.0)
        if amount is None or amount == 0:
            e.note = "no payout this week"
            p.skipped.append(e)
        elif nrm(name) in NEVER_ENTER:
            e.note = "JD's own line — P&L bookkeeping, not Apex pay"
            p.excluded.append(e)
        elif team.lower().startswith(HOUSE_TEAM_PREFIX):
            dest = HOUSE_ROUTING.get(team.lower())
            if dest == "bonuses":
                e.note = f"{team} -> bonuses"
                p.bonuses.append(e)
            else:
                e.note = f"{team} — not confirmed with JD"
                p.excluded.append(e)
        else:
            p.entries.append(e)
    return p


def report(p: Plan) -> str:
    out = [f"\nApex entry for {p.banner} (column {p.paid_col})",
           f"\n  COMMISSION ADJUSTMENTS  ({len(p.entries)})"]
    for e in p.entries[:6]:
        out.append(f"    row {e.row:<5} {e.name[:26]:<26} ${e.amount:>10,.2f}")
    if len(p.entries) > 6:
        out.append(f"    … {len(p.entries) - 6} more")
    out.append(f"\n  BONUSES — house lines  ({len(p.bonuses)})")
    if not p.bonuses:
        out.append("    —")
    for e in p.bonuses:
        out.append(f"    row {e.row:<5} {e.name[:26]:<26} ${e.amount:>10,.2f}"
                   f"   {e.team}")
    out.append(f"\n  EXCLUDED — needs JD's word  ({len(p.excluded)})")
    if not p.excluded:
        out.append("    —")
    for e in p.excluded:
        out.append(f"    row {e.row:<5} {e.name[:26]:<26} ${e.amount:>10,.2f}"
                   f"   {e.note}")
    out.append(f"\n  NOT ENTERED — no payout  ({len(p.skipped)})")
    out.append(f"\n  TOTAL TO ENTER  ${p.total:,.2f}"
               f"   (excludes ${sum(e.amount for e in p.excluded):,.2f} above)")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Apex itself — adapted from apex_payroll, UNTESTED on JD's machine.
# --------------------------------------------------------------------------
#: Where --explore leaves what it finds, so it can be read back without
#: anyone having to copy terminal output around.
EXPLORE_TAB = "Apex Form Map"


def probe() -> int:
    """Is JD's Apex session reachable? Read-only, always safe to run."""
    from automations.apex_payroll.run import probe as _probe
    return _probe()


def explore(workbook_id: str = C.WORKBOOK_ID) -> int:
    """Map the Payroll Entry form and write what it finds into the workbook.

    Read-only against Apex: it navigates, reads, screenshots, and types
    nothing. Nobody has mapped this form yet — apex_payroll only ever got as
    far as probe/explore — so this is the step that makes the entry logic
    writable instead of guessed.

    Results go to a tab in the workbook rather than the terminal, so whoever
    runs it does not have to copy anything back by hand."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.apex_payroll.run import (APEX_URL, _attach, _copy_default_profile,
                                              _kill_ours, _launch, _log,
                                              _looks_logged_out)
    from automations.recruiting_report.fill import open_by_key

    lines: List[str] = []

    def say(msg: str) -> None:
        lines.append(msg)
        _log(msg)

    prof = _copy_default_profile()
    proc = _launch(APEX_URL, prof)
    time.sleep(8)
    png = None
    try:
        with sync_playwright() as pw:
            _browser, page = _attach(pw)
            page.wait_for_load_state("domcontentloaded", timeout=30000)
            time.sleep(3)
            if _looks_logged_out(page):
                say("STOP: Apex is showing a login page — the session did not "
                    "ride along. Log in to Apex in your NORMAL Chrome, quit "
                    "Chrome, then run this again.")
                png = page.screenshot(full_page=False)
                return 3
            say(f"logged in at {page.url}")

            for label in ("Payroll", "Payroll Entry"):
                for sel in (f'a:has-text("{label}")', f'button:has-text("{label}")',
                            f'[role="menuitem"]:has-text("{label}")', f'text="{label}"'):
                    loc = page.locator(sel).first
                    try:
                        if loc.count():
                            loc.click(timeout=8000)
                            page.wait_for_load_state("domcontentloaded", timeout=20000)
                            time.sleep(3)
                            say(f"clicked {label!r} -> {page.url}")
                            break
                    except Exception:                      # noqa: BLE001
                        continue

            say("")
            say("--- PAGE TEXT ---")
            body = page.inner_text("body", timeout=10000) or ""
            for ln in body[:4000].split("\n"):
                if ln.strip():
                    say("  | " + ln.strip()[:160])

            say("")
            inputs = page.locator("input, select, textarea")
            total = inputs.count()
            say(f"--- INPUTS ({total}) ---")
            for i in range(min(total, 120)):
                el = inputs.nth(i)
                attrs = " ".join(
                    f"{k}={el.get_attribute(k)!r}"
                    for k in ("name", "id", "type", "placeholder", "aria-label",
                              "class", "value")
                    if el.get_attribute(k))
                say(f"  #{i:<3} {attrs[:200]}")

            say("")
            rows = page.locator("tr")
            say(f"--- TABLE ROWS ({rows.count()}) first 15 ---")
            for i in range(min(rows.count(), 15)):
                try:
                    say(f"  r{i:<3} " + (rows.nth(i).inner_text(timeout=3000)
                                         or "").replace("\n", " | ")[:180])
                except Exception:                          # noqa: BLE001
                    continue
            png = page.screenshot(full_page=True)
            return 0
    finally:
        proc.terminate()
        _kill_ours()
        try:
            sh = open_by_key(workbook_id)
            try:
                tab = sh.worksheet(EXPLORE_TAB)
                tab.clear()
            except Exception:                              # noqa: BLE001
                tab = sh.add_worksheet(title=EXPLORE_TAB, rows=2000, cols=2)
            tab.update(values=[[ln] for ln in lines] or [["(nothing captured)"]],
                       range_name="A1")
            _log(f"wrote {len(lines)} line(s) to the {EXPLORE_TAB!r} tab")
            if png:
                import base64
                b64 = base64.b64encode(png).decode()
                chunks = [b64[i:i + 45000] for i in range(0, len(b64), 45000)]
                shot = f"{EXPLORE_TAB} PNG"
                try:
                    t2 = sh.worksheet(shot)
                    t2.clear()
                except Exception:                          # noqa: BLE001
                    t2 = sh.add_worksheet(title=shot, rows=100, cols=1)
                t2.update(values=[[c] for c in chunks], range_name="A1")
                _log(f"screenshot -> {shot!r} ({len(chunks)} chunk(s))")
        except Exception as e:                             # noqa: BLE001
            _log(f"could not write the map back: {type(e).__name__}: {e}")


def apply(p: Plan) -> Dict[str, int]:
    raise NotImplementedError(
        "The Apex-driving half is not wired yet. It needs to run once on JD's "
        "own machine with his session live — `--probe` first, since a human "
        "Chrome already running is a known collision hazard. The plan above is "
        "verified and ready to feed it.")


def _parse_week(text: str) -> dt.date:
    m = re.match(r"^\s*(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\s*$", text)
    if not m:
        raise argparse.ArgumentTypeError(f"Use M.D (e.g. 8.30), got {text!r}")
    month, day = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else dt.date.today().year
    return dt.date(year + (2000 if year < 100 else 0), month, day)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--week", type=_parse_week, default=None)
    ap.add_argument("--probe", action="store_true",
                    help="check JD's Apex session; changes nothing")
    ap.add_argument("--explore", action="store_true",
                    help="map the Payroll Entry form into the workbook; read-only")
    ap.add_argument("--write", action="store_true", help="enter it in Apex")
    args = ap.parse_args(argv)

    if args.probe:
        return probe()
    if args.explore:
        return explore()
    p = plan(args.week)
    print(report(p))
    if not args.write:
        print("\n(plan only — nothing entered in Apex)")
        return 0
    done = apply(p)
    print(f"\nEntered {done['entered']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
