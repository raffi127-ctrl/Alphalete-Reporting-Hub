"""Add this week's surviving new starts to Apex, filled from their Blue Ink packet.

    python -m automations.apex_new_starts.run --preflight   # checks, opens nothing
    python -m automations.apex_new_starts.run --preview     # who + what, no browser
    python -m automations.apex_new_starts.run --dry-run     # opens Apex, types nothing
    python -m automations.apex_new_starts.run --assist      # fills each record for real

WHAT IT DOES
Reads the current 'Sales Board WE <m>.<d>' tab, takes everyone in the
'New Starts/Raf' box who is NOT marked Terminated anywhere in the week, finds
each one's signed Blue Ink packet, and types their I-9 answers into a fresh
Apex employee record.

TWO THINGS IT DELIBERATELY DOES NOT DO
  * It never types a Social Security number. Everything else is filled; the SSN
    is left for the person at the keyboard, and --assist opens that person's own
    signed I-9 in a tab so they can read it off the source. The number never
    passes through this report's output or logs.
  * It never clicks Save. The operator looks at the filled record, adds the SSN,
    and saves it themselves. That is also the duplicate check: they can see
    whether the person is already in Apex before committing anything.

WHY IT IS PUSH-A-BUTTON AND NOT SCHEDULED
Apex has no API here and no session this repo can hold, so the run rides the
Apex login already open in the operator's Chrome (see apex.py). Megan's call
(2026-09-03): "we build it out and then someone pushes play once they have it
logged into."

WHEN TO RUN IT
Thursday or Friday. By then the week's terminations are on the board, so the
people this picks up are the ones who are actually staying -- run it Tuesday
and you add six people who will be gone by Thursday. --preflight says so, and
every mode refuses another day unless you pass --any-day.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.apex_new_starts import board as BRD
from automations.apex_new_starts import blueink_data as BID
from automations.apex_new_starts import fieldmap as FM

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"

GOOD_DAYS = (3, 4)      # Thursday, Friday (Mon=0)
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday")


def _log(msg: str = "") -> None:
    print(msg, flush=True)


def _interactive() -> bool:
    """Is a person actually at a keyboard? The Hub runs these as a subprocess
    with no stdin, and a `input()` there hangs the card forever."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:  # noqa: BLE001
        return False


def _pause(msg: str) -> None:
    if _interactive():
        input(msg)
    else:
        _log(f"    (no terminal — not waiting) {msg.strip()}")


# ------------------------------------------------------------------ preflight

def check_day(today: dt.date, any_day: bool) -> bool:
    ok = today.weekday() in GOOD_DAYS
    if ok:
        _log(f"  ✅ It's {DAY_NAMES[today.weekday()]} — the right day to run "
             "this.")
    elif any_day:
        _log(f"  ⚠️  It's {DAY_NAMES[today.weekday()]}, not Thursday or Friday. "
             "Running anyway (--any-day). The week's terminations may not all "
             "be on the board yet, so you may add someone who is about to go.")
    else:
        _log(f"  ❌ It's {DAY_NAMES[today.weekday()]}. This runs Thursday or "
             "Friday, once the week's terminations are on the board. Add "
             "--any-day if you really mean to run it today.")
    return ok or any_day


def check_blueink() -> bool:
    try:
        FM.load()
    except Exception as e:  # noqa: BLE001
        _log(f"  ❌ Blue Ink field map: {e}")
        return False
    try:
        BID.completed_bundles(limit=1, pages=1)
    except Exception as e:  # noqa: BLE001
        _log(f"  ❌ Blue Ink API: {e}")
        _log("     The key lives in blueink-creds.json at the repo root.")
        return False
    _log("  ✅ Blue Ink is reachable and the form-field map is loaded.")
    return True


def check_apex() -> bool:
    from automations.apex_new_starts import apex as AX
    try:
        with AX.ApexSession(log=lambda m: _log(f"     {m}")) as s:
            s.require_login()
    except AX.PasswordChangeRequired as e:
        _log(f"  ❌ Apex: {e}")
        return False
    except AX.NotLoggedIn as e:
        _log(f"  ❌ Apex: {e}")
        return False
    except Exception as e:  # noqa: BLE001
        _log(f"  ❌ Apex: couldn't open a session — {type(e).__name__}: {e}")
        return False
    _log("  ✅ Apex is signed in on this machine.")
    return True


def preflight(today: dt.date, *, any_day: bool, skip_apex: bool = False) -> int:
    _log("PREFLIGHT")
    ok = check_day(today, any_day)
    ok = check_blueink() and ok
    if skip_apex:
        _log("  ⏭  Apex check skipped (--no-apex-check).")
    else:
        ok = check_apex() and ok
    _log()
    _log("Ready." if ok else "Not ready — fix the ❌ above and run it again.")
    return 0 if ok else 1


# -------------------------------------------------------------------- preview

def gather(today: dt.date, *, tab=None, include_ona=True):
    """(tab, to_add, skipped, {name: NewHire}) — reads only."""
    title, people = BRD.load(today, tab=tab)
    add, skipped = BRD.to_add(people, include_ona=include_ona)
    hires = BID.for_people(add) if add else {}
    return title, add, skipped, hires


def apex_values(c: BRD.Candidate, hire: BID.NewHire) -> dict:
    """Everything that goes into Apex for one person, from three sources.

      the I-9        who they are   -- name, address, DOB, email, phone
      the board      when they started -- the date of their CR (classroom) cell
      DEFAULTS       how this office hires -- Sales Rep, $10/hr, Texas,
                     Commissions, Weekly. Same for everyone, so they are
                     settings rather than data.

    Anything missing is simply absent from the dict; nothing is invented. The
    caller reports the gap and skips rather than typing a placeholder into
    somebody's payroll record.
    """
    from automations.apex_new_starts import apex as AX
    v = dict(hire.fillable())               # SSN cannot be in here -- see
                                            # NewHire.fillable
    v.update(AX.DEFAULTS)
    email = v.pop("email", "")
    if email:
        v["account_email"] = email
        if AX.USERNAME_IS_EMAIL:
            v["username"] = email
    if c.hire_date:
        # MM/dd/yyyy, the format the Hire Date box itself asks for.
        v["hire_date"] = c.hire_date.strftime("%m/%d/%Y")

    # The I-9 does not speak Apex. Two values need converting, and both fail
    # SILENTLY if they aren't -- a dropdown handed something it doesn't have
    # simply stays on 'Select', with no error anywhere.
    st = (v.get("state") or "").strip().upper()
    if st in AX.STATE_NAMES:
        v["state"] = AX.STATE_NAMES[st]     # 'TX' -> 'Texas'
    elif st:
        v.pop("state")                      # unrecognised: report, don't guess
    dob = _us_date(v.get("dob"))
    if dob:
        v["dob"] = dob
    else:
        v.pop("dob", None)

    phone = v.pop("phone", "")
    if phone:
        v[AX.PHONE_FIELD] = phone
    return v


def _us_date(value) -> str:
    """A date the way Apex's boxes write one: M/D/YYYY, no leading zeros.

    The I-9 hands back whatever the person typed, and Apex's own records read
    '6/28/2004'. Anything unparseable comes back empty so the caller drops it --
    a birthday is not a field to approximate.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            d = dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        return f"{d.month}/{d.day}/{d.year}"
    return ""


def _person_line(c: BRD.Candidate, hire: BID.NewHire) -> str:
    if hire.missing_packet:
        return (f"  ❌ {c.name:26} no signed Blue Ink packet — nothing to fill "
                "from")
    missing = [f for f in ("first", "last", "address1", "city", "state", "zip",
                           "dob", "email", "phone") if not hire.values.get(f)]
    ssn = "SSN on file" if hire.values.get("ssn") else "NO SSN on the packet"
    flag = "  ⚠️ O-NA" if c.ona else ""
    hired = c.hire_date.strftime("%m/%d/%Y") if c.hire_date else "?"
    body = (f"  ✅ {c.name:26} hire {hired} · {len(hire.have)}/11 fields · {ssn}"
            f" · matched by {hire.matched_on}{flag}")
    if not c.hire_date:
        body += ("\n       ⚠️ no CR (classroom) day on the board this week — "
                 "hire date has to be typed by hand")
    if missing:
        body += f"\n       missing: {', '.join(missing)}"
    for _sem, why in hire.rejected:
        body += f"\n       ⚠️ {why}"
    return body


def preview(today: dt.date, *, tab=None, include_ona=True,
            save: bool = True) -> int:
    title, add, skipped, hires = gather(today, tab=tab, include_ona=include_ona)
    _log(f"SALES BOARD → {title}  ·  'New Starts/Raf' box")
    _log()
    _log(f"TO ADD TO APEX ({len(add)})")
    lines = []
    for c in add:
        line = _person_line(c, hires.get(c.name) or BID.NewHire(name=c.name,
                                                                missing_packet=True))
        _log(line)
        lines.append(f"{c.name} | row {c.row} | {c.worked_days()}")
    _log()
    _log(f"NOT ADDED ({len(skipped)})")
    for c, why in skipped:
        _log(f"  ⛔ {c.name:26} {why}")
    ona = [c for c in add if c.ona]
    if ona:
        _log()
        _log("⚠️  O-NA this week — added, but they are the ones most likely to "
             "be terminated Monday. Check them first:")
        for c in ona:
            _log(f"     {c.name} — {c.worked_days()}")
    nopacket = [c for c in add if (hires.get(c.name) or
                                   BID.NewHire(name=c.name,
                                               missing_packet=True)).missing_packet]
    if nopacket:
        _log()
        _log("These have no signed packet, so Apex can't be filled for them. "
             "Either their Blue Ink is still unsigned, or Blue Ink spells their "
             "name differently from the board:")
        for c in nopacket:
            _log(f"     {c.name}")
    if save:
        OUTPUT_DIR.mkdir(exist_ok=True)
        out = OUTPUT_DIR / f"apex-new-starts-{today.isoformat()}.txt"
        out.write_text(
            f"{title} — New Starts to add to Apex, {today.isoformat()}\n\n"
            + "\n".join(lines)
            + f"\n\nNot added ({len(skipped)}):\n"
            + "\n".join(f"{c.name} — {why}" for c, why in skipped) + "\n")
        _log()
        _log(f"saved → {out.relative_to(REPO_ROOT)}")
    return 0


# ------------------------------------------------------------- Apex fill

def _open_add_employee(session, log) -> bool:
    """Try to reach the new-employee screen by the words on the buttons.

    Returns False rather than guessing: if it can't get there, the operator
    opens the screen and the run works with whatever is in front of it. That is
    the point of --assist -- somebody is sitting there.
    """
    page = session.page
    for label in ("Add Employee", "New Employee", "Add New Employee",
                  "New Hire", "Employees"):
        for sel in (f'a:has-text("{label}")', f'button:has-text("{label}")',
                    f'[role="menuitem"]:has-text("{label}")'):
            loc = page.locator(sel).first
            try:
                if loc.count():
                    loc.click(timeout=6000)
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                    page.wait_for_timeout(2500)
                    log(f"    clicked {label!r} → {page.url}")
                    if label != "Employees":
                        return True
            except Exception:  # noqa: BLE001
                continue
    return False


def fill_people(today: dt.date, *, tab=None, include_ona=True,
                assist: bool = False) -> int:
    """--dry-run (assist=False) plans the fill; --assist types it."""
    from automations.apex_new_starts import apex as AX

    title, add, _skipped, hires = gather(today, tab=tab, include_ona=include_ona)
    ready = [c for c in add
             if not (hires.get(c.name) or BID.NewHire(name=c.name,
                                                      missing_packet=True)).missing_packet]
    if not ready:
        _log("Nobody to fill — see --preview for why.")
        return 1
    _log(f"{title}: {len(ready)} record(s) to fill"
         f"{' (typing nothing — dry run)' if not assist else ''}")

    with AX.ApexSession(log=lambda m: _log(f"  {m}")) as s:
        s.require_login()
        for i, c in enumerate(ready, 1):
            hire = hires[c.name]
            _log()
            _log(f"[{i}/{len(ready)}] {c.name}")
            # A FRESH blank form per person. After the operator saves someone,
            # Apex is left on that person's record -- filling the next one
            # there would overwrite the record just created. The dry run does
            # this once, on the first person, because it types nothing and only
            # needs a form to match labels against.
            if assist or i == 1:
                if not _open_add_employee(s, _log):
                    _log("    ⚠️  Couldn't find an 'Add Employee' button by "
                         "name. Open a blank new-employee screen in the Apex "
                         "window yourself; this uses whatever is in front of "
                         "it.")
                    _pause("    Press Enter once the blank form is open... ")
            matched, unmatched = AX.plan_fill(s.page, apex_values(c, hire))
            missing_required = [r for r in AX.REQUIRED
                                if r not in {m[0] for m in matched}]
            for semantic, why in unmatched:
                _log(f"    ⚠️ {semantic}: {why}")
            if missing_required:
                _log(f"    ❌ SKIPPED — no field found for "
                     f"{', '.join(missing_required)}. Nothing was typed. Run "
                     "--explore on this screen and send apex_screen.json back "
                     "so the labels can be corrected.")
                continue
            if not assist:
                for semantic, value, hit in matched:
                    shown = "•" * len(value) if semantic in FM.SENSITIVE else value
                    _log(f"    would fill {semantic:9} → "
                         f"{hit['matched_label']!r} = {shown}")
                continue
            AX.apply_fill(s.page, matched, log=_log)
            if AX.set_security_role(s.page):
                _log(f"    security role -> {AX.SECURITY_ROLE!r}")
            else:
                _log(f"    ⚠️ couldn't find a Security Roles option reading "
                     f"exactly {AX.SECURITY_ROLE!r} — nothing was ticked, set "
                     "it yourself before saving.")
            _log("    left for you: the Social, and Save.")
            if hire.values.get("ssn"):
                url = BID.signed_pdf_url(hire.bundle_id)
                if url:
                    s.page.context.new_page().goto(url)
                    _log("    SSN: opened their signed I-9 in a new tab — read "
                         "it from there and type it in. This report never "
                         "handles Social Security numbers.")
                else:
                    _log("    SSN: it's on their signed I-9 in Blue Ink.")
            _pause("    Check the record, add the SSN, click Save in Apex — "
                   "then press Enter for the next person. ")
    _log()
    _log("Done." if assist else "Dry run finished — nothing was typed.")
    return 0


def explore(today: dt.date) -> int:
    from automations.apex_new_starts import apex as AX
    with AX.ApexSession(log=lambda m: _log(f"  {m}")) as s:
        s.require_login()
        _open_add_employee(s, _log)
        _pause("  Put the blank NEW EMPLOYEE form on screen, then press Enter. ")
        inv = AX.explore(s)
    _log(f"\n{inv['title']} — {len(inv['fields'])} field(s) on {inv['url']}")
    for semantic, got in sorted(inv["resolved"].items()):
        _log(f"  {semantic:9} {got or '— NOT FOUND'}")
    _log(f"\nsaved → {AX.SCREEN_PATH.relative_to(REPO_ROOT)}  (send this back "
         "and the label list can be made exact)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true",
                      help="check the day, Blue Ink and the Apex login")
    mode.add_argument("--preview", action="store_true",
                      help="who would be added and what would be filled")
    mode.add_argument("--dry-run", action="store_true",
                      help="open Apex and match the fields, typing nothing")
    mode.add_argument("--assist", action="store_true",
                      help="fill each record for real (you add the SSN and save)")
    mode.add_argument("--explore", action="store_true",
                      help="inventory the Apex new-employee screen")
    ap.add_argument("--any-day", action="store_true",
                    help="run outside Thursday/Friday anyway")
    ap.add_argument("--skip-ona", action="store_true",
                    help="leave out anyone marked O-NA this week")
    ap.add_argument("--tab", help="a specific week tab, e.g. '9.6'")
    ap.add_argument("--no-apex-check", action="store_true",
                    help="preflight only: skip the Apex login check")
    ap.add_argument("--date", help="pretend it is this date (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    today = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    include_ona = not args.skip_ona

    if args.preflight:
        return preflight(today, any_day=args.any_day,
                         skip_apex=args.no_apex_check)
    if args.explore:
        return explore(today)
    if not check_day(today, args.any_day):
        return 1
    if args.preview:
        return preview(today, tab=args.tab, include_ona=include_ona)
    if args.assist and not _interactive():
        _log("--assist needs a terminal: it fills one record, then waits for "
             "you to add the SSN and click Save before moving on. Run it from "
             "Terminal, not from the Hub. (--preview and --dry-run work "
             "anywhere.)")
        return 1
    if args.dry_run or args.assist:
        return fill_people(today, tab=args.tab, include_ona=include_ona,
                           assist=args.assist)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
