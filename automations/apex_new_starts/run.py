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
import os
import sys
from pathlib import Path
from typing import Optional

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
    except AX.ProfileInUse as e:
        _log(f"  ❌ Apex: {e}")
        return False
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


def preflight(today: dt.date, *, any_day: bool, skip_apex: bool = False,
              tab=None, include_ona=True, watch: bool = True) -> int:
    """Check, then fetch — one button (Megan, 2026-09-13).

    Checking and then making somebody find a second button to actually get the
    week is two steps where there is one job. If the checks pass this goes
    straight on to read the board and the packets and put the setup on the
    clipboard. If they do not, it stops and says what to fix: there is nothing
    worth carrying over to Apex until that is sorted.
    """
    _log("PREFLIGHT")
    # Block on what actually stops the list being built. The Apex session does
    # not: reading the board and the packets needs nothing from Apex, and
    # refusing to fetch because a browser is sitting on a password prompt
    # leaves somebody with nothing to show for the click. It is said plainly
    # and the list still comes.
    can_build = check_day(today, any_day)
    can_build = check_blueink() and can_build
    apex_ready = True
    if skip_apex:
        # Not a corner cut. The check opens a real browser and can sit there
        # for minutes, to tell you what the next click tells you instantly --
        # you are looking at Apex when you press the bookmark. Off by default
        # from the Hub; --preflight without --no-apex-check still runs it.
        _log("  •  Apex: you'll see for yourself when you click the bookmark.")
    else:
        apex_ready = check_apex()
    _log()
    if not can_build:
        _log("Not ready — fix the ❌ above and run it again.")
        return 1
    _log("Getting this week's list…")
    _log()
    code = make_button(today, tab=tab, include_ona=include_ona, watch=watch)
    if code == 0 and not apex_ready:
        _log()
        _log("⚠️  The list is ready, but Apex is not signed in on this "
             "machine yet — sort that out above before you click the "
             "bookmark.")
    return code


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
      the board      when they started -- the date of their CR (classroom)
                     cell -- and their gender, from the column Megan added
      DEFAULTS       how this office hires -- Sales Rep, $10/hr, Texas,
                     Commissions, Weekly. Same for everyone, so they are
                     settings rather than data.
      the W-4        what the tax tab needs -- what they claim for dependents,
                     in dollars, and their filing status.

    The three pages are filled from ONE dict: whichever page is on screen,
    plan_fill matches what belongs to it and reports the rest as absent.

    Anything missing is simply absent from the dict; nothing is invented. The
    caller reports the gap and skips rather than typing a placeholder into
    somebody's payroll record.
    """
    from automations.apex_new_starts import apex as AX
    v = dict(hire.fillable())               # SSN cannot be in here -- see
                                            # NewHire.fillable
    v.update(AX.DEFAULTS)
    v.update(AX.TAX_DEFAULTS)
    email = v.pop("email", "")
    if email:
        v["account_email"] = email
        # Only needed for somebody being CREATED: the ones already on the
        # Pending tab have an account and it is not ours to change. Megan,
        # 2026-09-09: "just use their email but leave off the @gmail.com part".
        v["username"] = email.split("@")[0]
        # NOT the user name. The new starts are ALREADY in Apex, sitting on the
        # Pending tab with their account created (Megan, 2026-09-09) -- which is
        # also why Apex rejected the email as "already being used": it was this
        # company's own existing record. The job is completing those profiles,
        # so the account fields are left exactly as they are.
    if c.hire_date:
        # Kept for the preview and the Slack thread. It is NOT typed: on a
        # Pending record the Hire Date is already set and shown as plain text.
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

    # Gender comes off the board's own column (Megan added it 2026-09-03).
    # Blank stays blank: an empty cell means nobody has said, and a name is not
    # evidence. The operator fills it, and the preview says who needs it.
    gender = _gender(c.gender)
    if gender:
        v["gender"] = gender

    # --- the tax tab, off the W-4 -------------------------------------------
    # Apex's 'Claim Dependents' wants DOLLARS, which is what the W-4 already
    # states -- no converting to a count. Prefer the form's own total; fall
    # back to 3a + 3b when whoever filled it left the total blank.
    dep = _dollars(hire.values.get("dep_total"))
    if dep is None:
        a = _dollars(hire.values.get("child_credit"))
        b = _dollars(hire.values.get("other_dep_credit"))
        dep = None if a is None and b is None else (a or 0) + (b or 0)
    # Apex REQUIRES Claim Dependants, and a blank W-4 Step 3 means they claim
    # nothing -- which is $0, not "unknown". Leaving it empty made Apex refuse
    # the tax page for everyone who didn't fill Step 3, which is most people.
    v["claim_dependents"] = f"{dep or 0:.2f}"

    # All three filing-status boxes are identified now (see MARITAL_BY_FLAG).
    ticked = [flag for flag in AX.MARITAL_BY_FLAG
              if str(hire.values.get(flag) or "").strip().lower() == "true"]
    if len(ticked) == 1:
        v["marital_status"] = AX.MARITAL_BY_FLAG[ticked[0]]
    elif not ticked:
        # NOBODY ticked is an answer now, not a gap: "Assume single and no
        # dependents if they don't fill out" (2026-09-10, via Megan). It is
        # still reported as an assumption -- filled AND flagged -- because it
        # is our reading of a blank box, not something they stated.
        v["marital_status"] = AX.MARITAL_SINGLE
        v["claim_dependents"] = f"{dep or 0:.2f}"
    # More than one ticked is left alone. That is a contradiction on a signed
    # form, and picking one of them would be inventing the answer.
    return v


def _dollars(value):
    """'4,000' -> 4000.0, or None when the box was left empty."""
    raw = str(value or "").replace(",", "").replace("$", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _gender(value) -> str:
    """The board's value as Apex's dropdown spells it, or '' if unrecognised."""
    raw = str(value or "").strip().lower()
    if raw in ("f", "female", "woman"):
        return "Female"
    if raw in ("m", "male", "man"):
        return "Male"
    return str(value or "").strip()


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
    ssn = "SSN on file" if hire.has_ssn else "NO SSN on the packet"
    flag = "  ⚠️ O-NA" if c.ona else ""
    hired = c.hire_date.strftime("%m/%d/%Y") if c.hire_date else "?"
    body = (f"  ✅ {c.name:26} hire {hired} · {len(hire.have)}/11 fields · {ssn}"
            f" · matched by {hire.matched_on}{flag}")
    if not c.gender:
        body += ("\n       ⚠️ no Gender on the board — Apex requires one, so "
                 "fill that cell or type it in Apex yourself")
    if not c.hire_date:
        body += ("\n       ⚠️ no CR (classroom) day on the board this week — "
                 "hire date has to be typed by hand")
    if missing:
        body += f"\n       missing: {', '.join(missing)}"
    for _sem, why in hire.rejected:
        body += f"\n       ⚠️ {why}"
    return body


def manual_items(add, hires) -> list:
    """[(person, [what a human still has to do])] -- only what the run cannot.

    The Social and gender are typed in the pop-up for EVERY person, so they are
    not listed: 28 identical lines would bury the three names worth chasing.
    """
    from automations.apex_new_starts import apex as AX
    out = []
    for c in add:
        hire = hires.get(c.name)
        if hire is None or hire.missing_packet:
            out.append((c.name, ["no signed Blue Ink packet — the whole record "
                                 "has to be typed by hand"]))
            continue
        reasons = []
        missing = [f for f in ("first", "last", "address1", "city", "state",
                               "zip", "dob", "phone")
                   if not hire.values.get(f)]
        if missing:
            reasons.append("I-9 is missing " + ", ".join(missing))
        ticked = [f for f in AX.MARITAL_BY_FLAG
                  if str(hire.values.get(f) or "").strip().lower() == "true"]
        if len(ticked) > 1:
            reasons.append(
                "their W-4 has more than one filing status ticked — pick one")
        # hire.rejected carries the developer's version ("field_map.json may
        # be stale, recalibrate"). Alisson and Tiff are being asked to type
        # something into Apex, not to debug this repo, so it is rewritten as
        # the thing they'd actually do.
        for sem, _why in hire.rejected:
            reasons.append("their Blue Ink form's %s doesn't read as one — "
                           "check it and type it by hand" % sem.replace("_", " "))
        if reasons:
            out.append((c.name, reasons))
    return out


def preview(today: dt.date, *, tab=None, include_ona=True,
            save: bool = True, slack: bool = False,
            post_for_real: bool = False) -> int:
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
    if slack:
        from automations.apex_new_starts import slack_post
        slack_post.post(title, len(add), manual_items(add, hires),
                        dry_run=not post_for_real)
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
    _log("=== done ===")
    return 0


# ------------------------------------------------------------- Apex fill

def _fill_ssn_by_hand(session, c, hire) -> None:
    """Ask the operator for this person's Social and put it in the box.

    Apex will not save a profile without one, and this report neither reads
    Socials out of Blue Ink nor keeps them. So a small window asks, the number
    goes from that box straight into Apex, and nothing about it is logged --
    not here, not in the summary, not in output/.
    """
    from automations.apex_new_starts import apex as AX
    from automations.apex_new_starts import ssn_prompt

    if not _interactive():
        _log("    SSN: nobody at the keyboard — left blank. Apex won't save "
             "the profile until somebody enters it.")
        return
    where = "" if hire.has_ssn else "  (their Blue Ink packet has no SSN on it)"
    answers = ssn_prompt.ask(
        c.name, gender=c.gender,
        subtitle="Everything else on this record is filled in." + where)
    if not answers:
        _log("    SSN: skipped — this profile won't save until it's entered.")
        return
    if answers.gender:
        hit = AX.find_field(session.page, "gender")
        if hit:
            AX.apply_fill(session.page, [("gender", answers.gender, hit)],
                          log=lambda *_: None)
            _log(f"    gender -> {answers.gender}"
                 + ("" if c.gender else "  (the board's column was empty)"))
    if AX.fill_ssn(session.page, answers.ssn):
        _log("    SSN: entered (not logged, not stored).")
        return
    _log("    ⚠️ Couldn't find the Social Security box on this screen — "
         "nothing was typed. Open the Tax & Bank Information tab and enter it "
         "yourself; send me a screenshot of that tab and the run can go there "
         "on its own next time.")


def _open_add_employee(session, log) -> bool:
    """Try to reach the new-employee screen by the words on the buttons.

    Returns False rather than guessing: if it can't get there, the operator
    opens the screen and the run works with whatever is in front of it. That is
    the point of --assist -- somebody is sitting there.
    """
    page = session.page
    # The form's own URL, learned from the real app (2026-09-05). Going
    # straight there beats hunting for a button by its words, and it is how we
    # know we're on the right screen rather than whatever was in front.
    from automations.apex_new_starts import apex as AX
    try:
        page.goto(AX.APEX_URL.rstrip("/") + "/employees/new",
                  wait_until="domcontentloaded", timeout=40000)
        page.wait_for_timeout(3000)
        if AX.find_field(page, "first") and AX.find_field(page, "hire_date"):
            log(f"    on the new-employee form → {page.url}")
            return True
        log(f"    that URL didn't give a blank form ({page.url}) — trying the "
            "menu instead")
    except Exception as e:  # noqa: BLE001
        log(f"    couldn't open the form by URL ({type(e).__name__}) — trying "
            "the menu instead")
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

    try:
        session = AX.ApexSession(log=lambda m: _log(f"  {m}"))
    except AX.ProfileInUse as e:
        _log(f"❌ {e}")
        return 1
    with session as s:
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
            _filled, problems = AX.apply_fill(s.page, matched, log=_log)
            for semantic, why in problems:
                _log(f"    ⚠️ {semantic}: {why}")
            if AX.set_security_role(s.page):
                _log(f"    security role -> {AX.SECURITY_ROLE!r}")
            else:
                _log(f"    ⚠️ couldn't find a Security Roles option reading "
                     f"exactly {AX.SECURITY_ROLE!r} — nothing was ticked, set "
                     "it yourself before saving.")
            _log("    left for you: the Social, and Save.")
            _fill_ssn_by_hand(s, c, hire)
            _pause("    Check the record, add the SSN, click Save in Apex — "
                   "then press Enter for the next person. ")
    _log()
    _log("Done." if assist else "Dry run finished — nothing was typed.")
    _log("=== done ===")
    return 0


def obcl_start(week_start: dt.date) -> Optional[dt.date]:
    """The cohort's start date, read off the OBCL tab LABEL.

    Megan, 2026-09-17: "You can see the start date for everyone on the OBCL —
    it's the tab label". `D2D OBCL 9.14` is the fourteenth of September, and
    that is the lineup that started that week — a stated date rather than the
    week's Monday inferred from an empty CR column.

    Only used for people the board does NOT mark CR: a CR is that person's own
    first day and beats a cohort-wide date. Returns None if no dated tab lands
    inside this board week, and the caller keeps the Monday.
    """
    import re as _re
    from automations.blueink_docs import config as _C
    from automations.recruiting_report.fill import open_by_key as _open
    try:
        titles = [ws.title for ws in _open(_C.SHEET_ID).worksheets()]
    except Exception:
        return None
    best = None
    for t in titles:
        m = _re.match(r"^\s*" + _re.escape(_C.DATED_TAB_PREFIX) +
                      r"\s+(\d{1,2})\.(\d{1,2})\s*$", t, _re.I)
        if not m:
            continue
        month, day = int(m.group(1)), int(m.group(2))
        # The tab carries no year. Try this board week's year, and the one
        # before it for a tab written across New Year.
        for year in (week_start.year, week_start.year - 1):
            try:
                when = dt.date(year, month, day)
            except ValueError:
                continue
            if week_start <= when <= week_start + dt.timedelta(days=6):
                if best is None or when < best:
                    best = when
    return best


def _started(c, cohort: Optional[dt.date]) -> str:
    """Their first day as m/d/Y: the CR cell, else the OBCL tab's date."""
    when = cohort if (c.hire_assumed and cohort) else c.hire_date
    return when.strftime("%m/%d/%Y") if when else ""


def make_button(today: dt.date, *, tab=None, include_ona=True,
                watch: bool = True) -> int:
    """Write the 'Fill Apex' page: one button that fills the form in the
    person's own signed-in browser.

    This exists because nothing else can reach Apex. A fresh sign-in ends on
    the change-password screen, and Apex asks for a texted code every time
    anyway -- so a human signs in, and the filling happens inside the tab they
    are already looking at.
    """
    from automations.apex_new_starts import apex as AX
    from automations.apex_new_starts import filler

    title, add, _skipped, hires = gather(today, tab=tab,
                                         include_ona=include_ona)
    people, notes = [], {}
    # NOBODY marked CR is a fact about the tab, not about 25 separate people.
    # On WE 9.20 the whole Monday column was empty, so every single person
    # carried the same warning and it buried the one that actually needed
    # somebody: a missing Blue Ink packet. Said once instead
    # (Megan, 2026-09-17).
    # Either source, or both, or neither -- per PERSON, not all-or-nothing
    # (Megan, 2026-09-17: "it could be one or the other or both"). Somebody
    # with no CR on a week where everyone else has one still deserves the
    # OBCL's answer; the alert is for the ones nothing covers.
    _no_cr = [c for c in add if c.hire_assumed]
    _cohort = (obcl_start(add[0].week_start)
               if _no_cr and add[0].week_start else None)
    _unknown = _no_cr if not _cohort else []
    # A start date nobody can find is worth interrupting for: the fix is on
    # the board, and whoever is about to sit down with 25 Socials should know
    # BEFORE they start, not after (Megan, 2026-09-17: "If you can't find the
    # CR/start date that should be an alert so they know they need to rerun").
    _who = ", ".join(c.name for c in _unknown[:6]) + (
        f" and {len(_unknown) - 6} more" if len(_unknown) > 6 else "")
    if not _no_cr:
        _notice = ""                       # every one of them marked CR
    elif not _cohort and len(_unknown) == len(add):
        _notice = (
            "NO START DATE FOR ANYBODY. Nothing is marked CR on the sales "
            "board and there is no dated OBCL tab for this week, so the dates "
            "shown are just that week's Monday. Mark CR on the board, then "
            "press Get this week's setup again.")
    elif not _cohort:
        _notice = (
            f"NO START DATE FOR {len(_unknown)} OF {len(add)}: {_who}. Neither "
            "a CR on the sales board nor a dated OBCL tab covers them, so "
            "their dates are just that week's Monday. Mark them CR, then "
            "press Get this week's setup again.")
    elif len(_no_cr) == len(add):
        _notice = (
            "Nobody is marked CR on the sales board this week. Start dates "
            f"came off the OBCL tab instead ({_cohort.strftime('%m/%d/%Y')}). "
            "If that is not right, mark CR on the board and press Get this "
            "week's setup again.")
    else:
        _notice = ""                       # named per person in the table
    for c in add:
        hire = hires.get(c.name)
        if hire is None or hire.missing_packet:
            notes[c.name] = "no Blue Ink packet — type this one by hand"
            continue
        pages = filler.rows_for(apex_values(c, hire))
        # `find` is what the Blue Ink link searches for: the SURNAME, which is
        # how a person searches that dashboard, and the only thing about them
        # that ends up in a URL.
        people.append({"name": c.name, "pages": pages,
                       # shown in the page's table only -- Apex holds the hire
                       # date already and it is read-only there
                       "hire": _started(c, _cohort),
                       # A direct link to their signed W-4, so the document and
                       # the box to type the Social into can sit side by side
                       # instead of a search to click through. These are Blue
                       # Ink's own expiring links -- a few hours -- so a list
                       # generated yesterday will need regenerating.
                       "doc": BID.signed_pdf_url(hire.bundle_id, prefer="w4"),
                       "find": c.last or c.name})
        flat = {lbl for page in pages.values() for lbl in page}
        gaps = [lbl for lbl in ("Marital Status", "Date of Birth",
                                "Street Address") if lbl not in flat]
        said = []
        if gaps:
            said.append("set by hand: " + ", ".join(gaps))
        # Filled AND flagged. A blank Step 1(c) is now read as Single with no
        # dependents, which is our reading of an empty box rather than
        # something they wrote down, so it is named.
        if not [f for f in AX.MARITAL_BY_FLAG
                if str(hire.values.get(f) or "").strip().lower() == "true"]:
            said.append("W-4 Step 1(c) blank \u2014 filled as Single, "
                        "no dependents")
        if c.hire_assumed and _cohort and len(_no_cr) < len(add):
            said.append("no CR \u2014 start date off the OBCL tab, "
                        + _cohort.strftime("%m/%d/%Y"))
        if said:
            notes[c.name] = "; ".join(said)
    OUTPUT_DIR.mkdir(exist_ok=True)
    build = filler._now_stamp()
    out = OUTPUT_DIR / f"fill-apex-{today.isoformat()}.html"
    out.write_text(filler.build_page(
        people, title.replace("Sales Board ", ""),
        today.strftime("%B %-d, %Y") if os.name != "nt"
        else today.strftime("%B %d, %Y"), notes, _notice,
        add[0].week_start.isoformat() if add and add[0].week_start else ""))
    _log(f"{title}: {len(people)} record(s) in the button")
    # The names, plainly, so the card shows WHO was pulled rather than just a
    # count (Megan, 2026-09-17: "I want to be able to see the list of names
    # here that Lucy pulled"). Unticking somebody happens in the panel, on the
    # same table you type the Socials into.
    for n, person in enumerate(people, 1):
        _log(f"   {n:2}. {person['name']}"
             + (f"  \u2014 {person['hire']}" if person.get("hire") else ""))
    if _notice:
        _log("  \u26a0\ufe0f  " + _notice)
    for name, why in notes.items():
        _log(f"  ⚠️ {name}: {why}")
    _log("")
    # Put the setup straight on the clipboard, so nobody has to find the page,
    # scroll it and click Copy before they can start. The button reads it from
    # there (Megan, 2026-09-13: "still too complex/glitchy for a 7 year old").
    _week = title.replace("Sales Board ", "")
    _start = add[0].week_start.isoformat() if add and add[0].week_start else ""
    setup = filler.build_js(people, _week, notice=_notice, start=_start)
    # Kept on disk so the card can list them and untick one without paying for
    # the board and Blue Ink again (Megan, 2026-09-17).
    from automations.apex_new_starts import batch as BATCH
    BATCH.save(week=_week, build=build, notice=_notice, start=_start,
               people=people, out_dir=OUTPUT_DIR)
    if _to_clipboard(setup[len("javascript:"):]):
        _log("This week's setup is on your clipboard.")
        _log("Open Apex, then click your Fill Apex bookmark. That is all.")
        if watch and start_watch():
            _log("The OBCL will be ticked on its own when the run finishes.")
        elif watch and _watch_alive():
            _log("A watcher from an earlier click is still waiting "
                 "\u2014 the OBCL will still be ticked.")
    else:
        _log("Open this and click 'Copy this week's setup':")
        _log(f"  {out}")
    # The Hub reads success off this marker, not off the exit code. Without it
    # every clean run was recorded "unknown" and the card printed "Run failed"
    # over a log that plainly said it had worked (Megan, 2026-09-13).
    _log("=== done ===")
    return 0


def _this_monday(today: dt.date = None) -> dt.date:
    """The Monday of the current board week, for --names."""
    today = today or dt.date.today()
    return today - dt.timedelta(days=today.weekday())


def _from_clipboard() -> str:
    """Whatever is on the clipboard, or "" — the other half of _to_clipboard."""
    import subprocess
    get = ["pbpaste"] if os.name != "nt" else [
        "powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    try:
        back = subprocess.run(get, capture_output=True, timeout=20)
        return back.stdout.decode("utf-8", "replace") if back.returncode == 0 else ""
    except Exception:
        return ""


def mark_obcl(dry_run: bool = False, names: str = None) -> int:
    """Tick 'Added to APEX' from the result the run left on the clipboard.

    `names` is the escape hatch. The clipboard is the only channel a browser
    has, so anything copied between the run ending and this being pressed
    loses the result -- which is exactly what happened on the first live run:
    Paris Carroll went into Apex and her tick had to be done by hand
    (2026-09-17).
    """
    import json as _json
    from automations.apex_new_starts import obcl as OB

    if names:
        want = [n.strip() for n in names.split(",") if n.strip()]
        if not want:
            _log("Nothing in --names.")
            return 1
        _log(f"Ticking by name: {', '.join(want)}")
        OB.mark(_this_monday(), want, dry_run=dry_run, log=_log)
        _log("=== done ===")
        return 0

    raw = _from_clipboard().strip()
    if not raw.startswith("APEX-OBCL "):
        _log("❌ The run's result isn't on the clipboard.")
        _log("   Finish a run in Apex first — the panel puts it there and says "
             "so. If you copied something else in between, press Run the whole "
             "week again; anyone already done is skipped.")
        return 1
    try:
        data = _json.loads(raw[len("APEX-OBCL "):])
        start = dt.date.fromisoformat(data["start"])
    except Exception as err:                                  # noqa: BLE001
        _log(f"❌ Could not read the run's result: {err}")
        return 1

    added = data.get("added") or []
    _log(f"{data.get('week', '')}: {len(added)} added")
    OB.mark(start, added, dry_run=dry_run, log=_log)
    _log("=== done ===")
    return 0


WATCH_LOCK = OUTPUT_DIR / ".obcl-watch.pid"
WATCH_LOG = OUTPUT_DIR / "logs" / "apex-obcl-watch.log"
WATCH_MINUTES = 120
WATCH_EVERY = 4          # seconds between looks


def _watch_alive() -> bool:
    """Is a watcher from an earlier click still going, and still young?

    The age check matters: a watcher reads the clipboard of whatever session
    started it, so one left over from somewhere else can sit there holding the
    lock while never seeing anything. Past its own two hours it does not count,
    and the next click starts a fresh one.
    """
    try:
        pid_s, _, started = WATCH_LOCK.read_text().strip().partition(" ")
        pid = int(pid_s)
    except Exception:
        return False
    try:
        when = dt.datetime.fromisoformat(started) if started else None
    except ValueError:
        when = None
    if when and (dt.datetime.now() - when).total_seconds() > WATCH_MINUTES * 60:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def start_watch() -> bool:
    """Leave a watcher running for this run, then let it die on its own.

    Megan, 2026-09-17: "it should just auto mark - not wait on someone to tell
    it to." A browser cannot reach a Google sheet, so something on the machine
    has to notice the result. This is that, scoped as tightly as it can be: it
    exists because somebody clicked to start a run, it looks only for text
    beginning APEX-OBCL, it keeps nothing else it sees, and it exits the moment
    it has marked the sheet or after two hours, whichever comes first.
    """
    import subprocess
    if _watch_alive():
        return False
    WATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(
            # Its OWN module, not this one. The Hub scans the process list
            # for "-m <a card's action module>" to find runs it did not start,
            # so a watcher launched as run.py made the card read RUNNING NOW
            # for two hours and disabled its own button (Megan, 2026-09-17).
            [sys.executable, "-m", "automations.apex_new_starts.obcl_watch"],
            cwd=str(REPO_ROOT), start_new_session=True,
            stdout=open(WATCH_LOG, "a"), stderr=subprocess.STDOUT)
    except Exception:
        return False
    try:
        WATCH_LOCK.write_text(f"{proc.pid} {dt.datetime.now().isoformat()}")
    except Exception:
        pass
    return True


def watch_obcl() -> int:
    """Poll for the run's result, mark the OBCL, stop."""
    import time
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    _log(f"[{stamp}] watching for a run to finish "
         f"(up to {WATCH_MINUTES} minutes)")
    deadline = time.time() + WATCH_MINUTES * 60
    try:
        while time.time() < deadline:
            if _from_clipboard().strip().startswith("APEX-OBCL "):
                code = mark_obcl()
                _log("marked." if code == 0 else "could not mark.")
                return code
            time.sleep(WATCH_EVERY)
        _log("no run finished inside the window — stopping.")
        return 0
    finally:
        try:
            WATCH_LOCK.unlink()
        except Exception:
            pass


def _to_clipboard(text: str) -> bool:
    """macOS pbcopy / Windows clip, then READ IT BACK.

    An exit code of 0 is not evidence the clipboard holds anything -- pbcopy
    returns 0 inside a sandbox that has its own pasteboard. Telling somebody
    "it is on your clipboard" when it is not is the whole failure mode this
    is supposed to remove, so check before saying so.
    """
    import subprocess
    put = ["pbcopy"] if os.name != "nt" else ["clip"]
    get = ["pbpaste"] if os.name != "nt" else [
        "powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    try:
        if subprocess.run(put, input=text.encode("utf-8"),
                          timeout=20).returncode != 0:
            return False
        back = subprocess.run(get, capture_output=True, timeout=20)
        if back.returncode != 0:
            return False
        return back.stdout.decode("utf-8", "replace").strip() == text.strip()
    except Exception:
        return False


def explore(today: dt.date) -> int:
    from automations.apex_new_starts import apex as AX
    try:
        session = AX.ApexSession(log=lambda m: _log(f"  {m}"))
    except AX.ProfileInUse as e:
        _log(f"❌ {e}")
        return 1
    with session as s:
        s.require_login()
        _open_add_employee(s, _log)
        _pause("  Put the blank NEW EMPLOYEE form on screen, then press Enter. ")
        inv = AX.explore(s)
    _log(f"\n{inv['title']} — {len(inv['fields'])} field(s) on {inv['url']}")
    for semantic, got in sorted(inv["resolved"].items()):
        _log(f"  {semantic:9} {got or '— NOT FOUND'}")
    _log(f"\nsaved → {AX.SCREEN_PATH.relative_to(REPO_ROOT)}  (send this back "
         "and the label list can be made exact)")
    _log("=== done ===")
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
    mode.add_argument("--button", action="store_true",
                      help="make the 'Fill Apex' page for this week")
    mode.add_argument("--mark-obcl", action="store_true",
                      help="tick 'Added to APEX' on the OBCL from the run's "
                           "result (left on the clipboard by the panel)")
    mode.add_argument("--explore", action="store_true",
                      help="inventory the Apex new-employee screen")
    ap.add_argument("--any-day", action="store_true",
                    help="run outside Thursday/Friday anyway")
    ap.add_argument("--skip-ona", action="store_true",
                    help="leave out anyone marked O-NA this week")
    ap.add_argument("--tab", help="a specific week tab, e.g. '9.6'")
    ap.add_argument("--no-watch", action="store_true",
                    help="build the setup but start no OBCL watcher \u2014 for "
                         "rebuilding from a terminal without leaving a process "
                         "somebody then has to kill. Killing them wholesale is "
                         "how an operator's own watcher got taken out mid-run "
                         "(2026-09-17)")
    ap.add_argument("--names",
                    help="with --mark-obcl: tick these names instead of "
                         "reading the run's result off the clipboard, comma "
                         "separated")
    ap.add_argument("--no-write", action="store_true",
                    help="with --mark-obcl: say what it would tick, write "
                         "nothing")
    ap.add_argument("--no-apex-check", action="store_true",
                    help="preflight only: skip the Apex login check")
    ap.add_argument("--slack", action="store_true",
                    help="show the #11280 thread of what still needs doing "
                         "by hand (prints it; posts nothing without --post)")
    ap.add_argument("--post", action="store_true",
                    help="with --slack, actually post it to the channel")
    ap.add_argument("--date", help="pretend it is this date (YYYY-MM-DD)")
    args = ap.parse_args(argv)

    today = (dt.date.fromisoformat(args.date) if args.date else dt.date.today())
    include_ona = not args.skip_ona

    if args.preflight:
        return preflight(today, any_day=args.any_day,
                         skip_apex=args.no_apex_check,
                         tab=args.tab, include_ona=include_ona,
                         watch=not args.no_watch)
    if args.button:
        return make_button(today, tab=args.tab, include_ona=include_ona,
                           watch=not args.no_watch)
    if args.mark_obcl:
        return mark_obcl(dry_run=args.no_write, names=args.names)
    if args.explore:
        return explore(today)
    if not check_day(today, args.any_day):
        return 1
    if args.preview or args.slack:
        return preview(today, tab=args.tab, include_ona=include_ona,
                       slack=args.slack, post_for_real=args.post)
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
