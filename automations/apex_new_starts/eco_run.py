"""New starts -> Apex, on the office's OWN computer.

Megan, 2026-11-06: "what if the ICDs relay machine also just logs into apex and
blueink -- the admin is just saying the task should run and who to run it for?"

The admin holds neither login. This machine holds both: that office's Blue Ink
key and an Apex session its owner signed into by hand (`icd_alerts.apex_signin`,
the same rule as box_signin -- no password is ever typed by Lucy). So the admin
presses a button, the relay carries one fact -- WHICH WEEK -- and everything
else happens here.

    admin    -> relay   "apex_week, week of 2026-11-02"      (admin session)
    here     <- relay   that job, handed out once            (office key)
    here     -> relay   who went in, who needs a hand        (office key)

WHO IS IN THE WEEK IS DECIDED HERE, NOT BY THE ADMIN. The job carries a date
and nothing else. This machine reads its own training calendar
(`office_admin.fdot` -- Show Up = Yes, Monday to Saturday, pooled) so a stale
or edited list cannot be posted in from outside. The same reasoning as the
account-number guard on background checks.

THE SOCIAL. From 2026-11-06 this machine may hold one, which Megan decided
after noting that the operator already previews the signed tax document and
copies the number out by hand. It is asked for only when this is actually going
to type it (`live`), it arrives wrapped as a `Secret`, it is never written down
and it cannot reach the result: `json.dumps` refuses a Secret, so a mistake
here fails loudly rather than posting a Social to a Google Sheet. A dry run
never asks for one at all.

WHAT THIS DOES AND DOES NOT DO YET. The whole pipeline up to the typing is
here and testable: roster -> Blue Ink -> per-person values -> what is ready and
what is missing. The typing itself calls the existing Apex path, which has only
ever been driven with somebody watching, so `live=True` is deliberately gated
and the default is a dry run that reports exactly what it would do.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from automations.apex_new_starts import blueink_data as BID

KIND = "apex_week"


@dataclass
class Starter:
    """One person off the training calendar, shaped the way `apex_values`
    expects a board Candidate. Separate from board.Candidate on purpose: this
    one comes from a calendar and has no sales-board row, no trainer and no
    roll -- inventing those to satisfy a constructor would be inventing data.
    """
    name: str
    email: str = ""
    phone: str = ""
    gender: str = ""
    hire_date: Optional[dt.date] = None
    source: str = "training calendar"


def starters(rows: List[Dict], day: Optional[dt.date] = None) -> List[Starter]:
    """fdot rows -> Starters. The training date IS the start date."""
    out = []
    for r in rows:
        name = ("%s %s" % (r.get("first_name", ""), r.get("last_name", ""))).strip()
        if not name:
            continue
        out.append(Starter(name=name, email=r.get("email", ""),
                           phone=r.get("phone", ""),
                           hire_date=r.get("started") or day))
    return out


def plan(people: List[Starter], hires: Dict[str, BID.NewHire],
         log=print) -> Dict:
    """Who can go in, and why anybody cannot -- without touching Apex.

    Returns {ready: [(Starter, values)], blocked: [{name, why}]}. Nothing is
    invented: a gap is reported and the person is held back, never filled with
    a placeholder that lands on a payroll record.
    """
    # values, not run: run.py imports the sales board and so Google Sheets,
    # and an office Mac reads a calendar, not a board.
    from automations.apex_new_starts import values as V

    ready, blocked = [], []
    for p in people:
        hire = hires.get(p.name)
        if hire is None or hire.missing_packet:
            blocked.append({"name": p.name,
                            "why": "no signed Blue Ink packet — type this one by hand"})
            continue
        values = V.apex_values(p, hire)
        gaps = [lbl for lbl in ("dob", "address1", "city", "zip")
                if not values.get(lbl)]
        if gaps:
            blocked.append({"name": p.name,
                            "why": "their packet is missing " + ", ".join(gaps)})
            continue
        ready.append((p, values))
    log("  %d ready, %d held back" % (len(ready), len(blocked)))
    return {"ready": ready, "blocked": blocked}


def _result(week_start: dt.date, *, status: str, added=(), blocked=(),
            error: str = "", counted: int = 0, live: bool = False) -> Dict:
    """The job's answer. Plain JSON -- names and reasons, never a number.

    Built in one place so there is one thing to read when asking "could a
    Social end up on the relay?". It cannot: nothing here comes from `ssn`,
    and a Secret would make json.dumps raise on the way out.
    """
    out = {"status": status, "week_start": week_start.isoformat(),
           "counted": counted, "added": list(added),
           "needs_hand": [dict(b) for b in blocked],
           "mode": "live" if live else "dry"}
    if error:
        out["error"] = error
    return out


def run_week(week_start: dt.date, *, office_appstream: str, office_key: str = "",
             live: bool = False, log=print) -> Dict:
    """The whole job. Returns a result dict; raises nothing the caller must
    catch for correctness (office_jobs also guards, belt and braces)."""
    from automations.office_admin import fdot

    monday = week_start - dt.timedelta(days=week_start.weekday())
    try:
        from automations.applicant_tracker.applicantstream import session
        with session() as app:
            rows = fdot.read_week(app, office_appstream, monday, log=log)
    except Exception as e:  # noqa: BLE001
        # A calendar that cannot be read is NOT an empty week. Saying "0 new
        # starts" here would quietly leave real people off payroll.
        return _result(monday, status="error", live=live,
                       error="could not read the training calendar: %s: %s"
                             % (type(e).__name__, str(e)[:200]))

    people = starters(rows, day=monday)
    if not people:
        return _result(monday, status="none", live=live, counted=0)

    # ONLY PEOPLE STILL ON THE OBCL (Megan, 2026-11-11: "you should only add
    # those then NOT removed from the OBCL"). The calendar says who showed up
    # for training; the board says who is still going through onboarding, and
    # between the two somebody quits, no-shows or fails a check. An Apex record
    # is a payroll record with no undo, so the board's removals win.
    try:
        gone = _removed_on_the_board(office_key, monday, log=log)
    except Exception as e:  # noqa: BLE001
        # A board that cannot be read is NOT a board with nobody removed.
        # Carrying on here would put somebody the ICD removed onto payroll.
        return _result(monday, status="error", live=live, counted=len(people),
                       error="could not read the onboarding board, so who was "
                             "removed is unknown: %s: %s"
                             % (type(e).__name__, str(e)[:200]))
    if gone:
        from automations.icd_onboarding import board as _B
        kept = [p for p in people if _B._fold(p.name) not in gone]
        log("  %d removed on the board -- not going to Apex (%d left)"
            % (len(people) - len(kept), len(kept)))
        people = kept
        if not people:
            return _result(monday, status="none", live=live, counted=0)

    # The Social is asked for ONLY when this run is going to type it.
    try:
        hires = BID.for_people(people, keep_ssn=live)
    except Exception as e:  # noqa: BLE001
        return _result(monday, status="error", live=live, counted=len(people),
                       error="Blue Ink: %s: %s" % (type(e).__name__, str(e)[:200]))

    got = plan(people, hires, log=log)
    if not live:
        return _result(monday, status="dry_run", live=False, counted=len(people),
                       added=[p.name for p, _ in got["ready"]],
                       blocked=got["blocked"])

    added, blocked = [], list(got["blocked"])
    for person, values in got["ready"]:
        try:
            fill_one(person, values, hires.get(person.name), log=log)
            added.append(person.name)
        except Exception as e:  # noqa: BLE001
            # One person Apex will not take does not stop the rest -- the same
            # rule the browser run follows. Exception text only; a field VALUE
            # is never quoted into a result that goes to the relay.
            blocked.append({"name": person.name,
                            "why": "Apex refused it (%s)" % type(e).__name__})
            log("  %s: %s" % (person.name, type(e).__name__))
    _tell_the_board(office_key, monday, added, log=log)
    return _result(monday, status="filled", live=True, counted=len(people),
                   added=added, blocked=blocked)


def _removed_on_the_board(office_key: str, monday: dt.date,
                          log=print) -> set:
    """Folded names the office's board says are OFF for this week.

    An office with no board yet has nobody removed -- that is a real answer,
    not a missing one, so it returns empty rather than raising. Anything that
    goes WRONG while reading a board that does exist raises, because "I could
    not look" must never be mistaken for "nobody was removed".
    """
    from automations.icd_onboarding import board as B
    from automations.icd_onboarding import fillers as F
    from automations.icd_onboarding import sheet as S
    if not office_key:
        return set()
    ws = S.open_board(F.workbook_for(office_key), create=False)
    if ws is None:
        log("  (no onboarding board for %s yet -- nobody removed)" % office_key)
        return set()
    rows = B.for_week(S.rows_of(S._values(ws)), monday)
    gone = set()
    for r in rows:
        if str(r.get(B.TERMINATED_AT) or "").strip():
            why = str(r.get(B.REMOVED_WHY) or "").strip() or "removed"
            name = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
            log("    off the board: %s (%s)" % (name, why))
            gone.add(B._fold(name))
    return gone


def _tell_the_board(office_key: str, monday: dt.date, added, log=print) -> None:
    """Tick 'Added to APEX' for everyone this run actually saved.

    The run knows who it saved at the moment it saves them, so it says so
    rather than something else working it out afterwards — the same shape as
    the contact sync ticking 'Contact Added' (Megan, 2026-11-09).

    NEVER fails the run. The payroll records are already saved by this point;
    raising here would report a failure for work that succeeded, and send
    somebody looking for people who are in fact in Apex. A board that did not
    get ticked is a visible gap on the board, which is the right place for it.
    """
    if not office_key or not added:
        return
    try:
        from automations.icd_onboarding import fillers as F
        F.tick(office_key, monday, "apex", added, dry_run=False, log=log)
    except Exception as e:  # noqa: BLE001
        log("  (the board was not ticked: %s: %s — the records ARE saved)"
            % (type(e).__name__, str(e)[:120]))


# The create form, by ng-model rather than by label. Read off the live page
# 2026-11-08 -- see resources/apex-form-controls.md, which is the only reason
# any of this is not guesswork.
#
# A plain text box takes the value. A "dropdown" is TWO HALVES: a widget the
# person clicks and a separate input carrying the chosen id, which is what the
# form submits -- so its model name ends in ID and typing a LABEL into it puts
# a word where an id belongs. Those are driven through the widget.
BY_MODEL = {
    "first":         "$ctrl.user.FirstName",
    "middle":        "$ctrl.user.MiddleName",
    "last":          "$ctrl.user.LastName",
    "username":      "$ctrl.userName",
    "account_email": "$ctrl.user.EmailAddress",
}

# label -> the id-carrying input beside the widget. Set through the widget.
BY_WIDGET_ID = {
    "position":      "$ctrl.employmentRecord.JobTitleID",
    "pay_frequency": "$ctrl.employmentRecord.PayFrequencyID",
    "pay_basis":     "$ctrl.employmentRecord.BasisOfPayID",
    "pay_state":     "$ctrl.stateWorkingIn",
    "department":    "$ctrl.employmentRecord.CompensationProfileID",
}

# Kendo widgets, driven through their own API.
KENDO = {"hire_date": "k-datepicker", "rate": "k-numerictextbox"}

# Sales Rep is a radio on $ctrl.roleID, value 11 (read off the live form).
ROLE_MODEL, ROLE_VALUE = "$ctrl.roleID", "11"

# NOTHING may write these. The first emails a real person; the second sits
# directly under Rate of Pay and is the wrong box for $10/hr.
NEVER = ("$ctrl.sendUserPassword", "$ctrl.employmentRecord.Salary")


FILL_JS = r"""(spec) => {
  /* Proven against the live form 2026-11-08 -- resources/apex-form-controls.md.
     Every control is driven through its OWN widget API, because AngularJS
     debug info is off in production: angular.element(el).scope() is undefined
     and there is no $apply to reach for. */
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const $ = window.jQuery;
  const done = [], missed = [];

  const setText = (model, val) => {
    const el = document.querySelector('[ng-model="' + model + '"]');
    if (!el) { missed.push(model + ' (no control)'); return; }
    el.value = val;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    done.push(model.split('.').pop());
  };

  const dropFor = idSuffix => {
    const idEl = [...document.querySelectorAll('input[ng-model]')]
        .find(e => (e.getAttribute('ng-model') || '').endsWith(idSuffix));
    if (!idEl) return null;
    const grp = idEl.closest('.form-group');
    const sel = grp && grp.querySelector('select');
    return (sel && $) ? {sel, w: $(sel).data('kendoDropDownList'), idEl} : null;
  };

  const setDrop = (idSuffix, wantText) => {
    const d = dropFor(idSuffix);
    if (!d || !d.w) { missed.push(idSuffix + ' (no widget)'); return; }
    const opts = [...d.sel.options].map(o => norm(o.text));
    const want = norm(wantText).toLowerCase();
    let i = opts.findIndex(t => t.toLowerCase() === want);
    if (i < 0) i = opts.findIndex(t => t.toLowerCase().indexOf(want) === 0);
    if (i < 0) {
      /* Name every option. A dropdown handed something it does not have stays
         on 'Select' with no error anywhere -- the silent failure this whole
         report keeps meeting. */
      missed.push(idSuffix + ' has no "' + wantText + '" -- it offers: ' +
                  opts.filter(Boolean).join(' | '));
      return;
    }
    d.w.select(i);
    d.w.trigger('change');
    done.push(idSuffix.replace(/ID$/, '') + '=' + opts[i]);
  };

  const widget = (cls, kind) => $('.' + cls + ' input').toArray()
      .map(el => $(el).data(kind)).find(Boolean);

  for (const [m, v] of Object.entries(spec.text || {})) setText(m, v);
  for (const [k, v] of Object.entries(spec.drops || {})) setDrop(k, v);

  if (spec.hire_date) {
    const dp = widget('k-datepicker', 'kendoDatePicker');
    if (dp) { dp.value(new Date(spec.hire_date)); dp.trigger('change');
              done.push('Hire Date'); }
    else missed.push('Hire Date (no datepicker)');
  }
  if (spec.rate) {
    const nb = widget('k-numerictextbox', 'kendoNumericTextBox');
    if (nb) { nb.value(Number(spec.rate)); nb.trigger('change');
              done.push('Rate of Pay'); }
    else missed.push('Rate of Pay (no numeric box)');
  }
  if (spec.role_value) {
    const r = [...document.querySelectorAll('input[type=radio][ng-model="$ctrl.roleID"]')]
        .find(x => x.value === String(spec.role_value));
    if (r) { r.click(); done.push('Role'); }
    else missed.push('Role (no radio with value ' + spec.role_value + ')');
  }

  /* The password-reset box DEFAULTS TO TICKED on a fresh form: saving would
     email the person. Always set deliberately, never left as found. */
  const pw = document.querySelector('[ng-model="$ctrl.sendUserPassword"]');
  if (pw && pw.checked !== !!spec.email_password_reset) {
    pw.click();
    done.push('password reset ' + (spec.email_password_reset ? 'ON' : 'OFF'));
  }

  /* What the page itself still objects to. This is the honest check: reading
     .value on a dropdown's hidden ID input shows '' even when it IS set. */
  const errors = [...new Set([...document.querySelectorAll('.text-danger, ng-message')]
      .filter(e => e.offsetParent).map(e => norm(e.innerText)).filter(Boolean))];
  const salary = document.querySelector('[ng-model="$ctrl.employmentRecord.Salary"]');
  return {done, missed, errors,
          salaryTouched: !!(salary && salary.value),
          passwordResetTicked: pw ? pw.checked : null};
}"""


def fill_spec(person: Starter, values: Dict) -> Dict:
    """What FILL_JS should put where, for one person. Pure -- no browser."""
    text = {model: values[key] for key, model in BY_MODEL.items() if values.get(key)}
    drops = {BY_WIDGET_ID[k].split(".")[-1]: values[k]
             for k in BY_WIDGET_ID if values.get(k)}
    return {
        "text": text,
        "drops": drops,
        "hire_date": person.hire_date.isoformat() if person.hire_date else "",
        "rate": values.get("rate", ""),
        "role_value": ROLE_VALUE,
        # Deliberate, because the box defaults to ticked. These people are
        # created FOR payroll, not to be invited to sign in, and an unexpected
        # "reset your password" email to a brand new rep is a support call.
        "email_password_reset": False,
    }


def fill_one(person: Starter, values: Dict, hire, log=print, *, page=None,
             save: bool = False) -> Dict:
    """Fill one person into the Apex form that is already on screen.

    The only function here that touches Apex, so there is one place to read
    when asking what this machine does to a payroll record.

    FILLING is proven (2026-11-08, filled live and every validation error
    cleared). SAVING is not: nothing has yet pressed Save, and a half-right
    save lands on a real person. So `save` stays off unless somebody has
    watched one go through and set APEX_FILL_PROVEN=1.
    """
    import os
    if page is None:
        raise RuntimeError("fill_one needs the Apex page to fill.")
    got = page.evaluate(FILL_JS, fill_spec(person, values))
    for m in got.get("missed") or []:
        log("    missed: %s" % m)
    if got.get("salaryTouched"):
        raise RuntimeError("Salary was written -- that is the wrong box for an "
                           "hourly rate. Nothing saved.")
    if got.get("errors"):
        raise RuntimeError("Apex still objects: %s" % "; ".join(got["errors"][:4]))
    if not save:
        log("    filled, NOT saved (%d fields)" % len(got.get("done") or []))
        return got
    if not os.environ.get("APEX_FILL_PROVEN"):
        raise RuntimeError(
            "filled, but saving has never been watched end to end. Look at the "
            "screen, press Save by hand once, then set APEX_FILL_PROVEN=1.")
    raise NotImplementedError(
        "the Save step is the one thing still unproven -- it wants its "
        "supervised first run.")


def main(argv=None) -> int:
    """Read-only by default.

        python -m automations.apex_new_starts.eco_run --office 11280
        python -m automations.apex_new_starts.eco_run --office 11280 --week 2026-11-02
    """
    import argparse
    import json
    ap = argparse.ArgumentParser(description="New starts -> Apex, on this office's computer.")
    ap.add_argument("--office", required=True, help="ApplicantStream office id")
    ap.add_argument("--week", default=None, help="YYYY-MM-DD in the week to run")
    args = ap.parse_args(argv)
    start = dt.date.fromisoformat(args.week) if args.week else dt.date.today()
    res = run_week(start, office_appstream=args.office, live=False)
    print(json.dumps(res, indent=2))
    return 0 if res.get("status") in ("dry_run", "none") else 1


if __name__ == "__main__":
    raise SystemExit(main())
