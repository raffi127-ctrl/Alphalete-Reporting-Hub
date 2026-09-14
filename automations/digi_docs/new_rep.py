"""Create a Sales Rep in OwnerVille, for somebody who is not in it yet.

Run:  lucy --machine "Lucy 3" rerun digi_docs_new_reps                (dry)
      lucy --machine "Lucy 3" rerun digi_docs_new_reps --only "Billy Garvin"
      ... --live                                              (actually creates)

WHY (Megan 2026-09-14: "you need to be able to learn how to add the missing
people from OV so that you can fully send to everyone on time for next week").

Fifteen of forty-eight new starts were not in OwnerVille's employee directory
that Monday. `ownerville.add_sales_rep` could not help: it puts an EXISTING
employee onto a campaign, and the picker it uses only ever offers people who
already exist. Nothing in this codebase could create the person.

TWO DIFFERENT PAGES WITH THE SAME BUTTON NAME, which is the trap here:

  View Progress (p=201) → "Add Sales Rep"  = put an existing employee on a
                                             campaign. What we already do.
  Sales Reps    (p=20)  → "+ Add Sales Rep" = create a person who does not
                                             exist. What this does.

WE LOOK PEOPLE UP BY EMAIL, NEVER BY NAME. The whole of 2026-09-14 was name
matching failing: 'juli' opened both Juliet and Julian, 'Billy' never matched
'William', and a fuzzy search offered 'Alysia Garcia' for 'Billy Garvin'. The
rep list carries every rep's email and the OBCL carries the same address, so
the join is an exact string on both sides — and here it matters more than
anywhere, because getting it wrong does not mis-send a document, it creates a
SECOND record for a person who already has one. Same lesson bg_check_sync
learned on this exact page (see ov_name_sync's "WE FIND PEOPLE BY EMAIL").

SAFETY. Dry by default. A person with no email is refused, never created on a
name. An existing record is never touched. And the form's own validation is
read before submitting, so we do not click Add into a page that is already
objecting.
"""
from __future__ import annotations

import argparse

from automations.bg_check_sync import ov_name_sync as ovn

# What Megan circled on the New Sales Rep form (2026-09-14). NOT
# ov_name_sync.DEFAULT_ROLE, which is "Entry Level" — that is the fallback for
# an EXISTING profile that somehow has no role at all. A new D2D start is a
# Sales Rep on a Door 2 Door account, and the two are asked for separately.
NEW_ROLE = "Sales Rep"
ACCOUNT_TYPE = "Door 2 Door"


class Refused(RuntimeError):
    """We will not create this person, and here is why."""


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def find_by_email(page, cols: dict, email: str):
    """The rep row whose email is exactly this one, or None.

    Exact, lowercased, whole-string. No surname fallback and no fuzzy anything:
    the question "does this person already exist" has to be answered yes or no,
    and a maybe here means either a duplicate human in the directory or a new
    start who never gets created.
    """
    want = _norm_email(email)
    if not want:
        return None
    for row in ovn._search_rows(page, want):
        fields = ovn._row_fields(page, row, cols)
        if _norm_email(fields.get("email")) == want:
            return fields
    return None


def _find_labelled(page, text: str):
    """The checkbox whose visible label reads `text`, or None. Reads only.

    Shared with the dry run on purpose: a dry run that does not look for the
    very boxes the live run will tick proves nothing about whether the live
    run would work.
    """
    # THE REQUIRED-FIELD ASTERISK IS PART OF THE LABEL (2026-09-14, found by
    # the dry run before it could cost a Monday). The form renders "Over 18 *",
    # and an exact match against "over 18" never hits it — so the first live
    # pass would have refused every single person with "the form has no
    # ['Over 18'] box". Strip trailing punctuation on BOTH sides: the asterisk
    # marks a field as required, it does not name a different box.
    return page.evaluate("""(want) => {
        const norm = s => (s || '').replace(/\\s+/g, ' ')
            .replace(/[\\s*:†]+$/, '').trim().toLowerCase();
        const boxes = [...document.querySelectorAll(
            'input[type=checkbox], input[type=radio]')];
        for (const el of boxes) {
            let lab = (el.dataset && el.dataset.label) || '';
            if (!lab && el.id) {
                const l = document.querySelector('label[for="' + el.id + '"]');
                if (l) lab = l.innerText;
            }
            if (!lab && el.closest('label')) lab = el.closest('label').innerText;
            if (norm(lab) === norm(want)) {
                return {id: el.id || '', checked: !!el.checked};
            }
        }
        return null;
    }""", text)


def _tick_labelled(page, text: str, *, verbose: bool = True) -> None:
    """Tick the checkbox whose visible label reads `text`.

    By LABEL, not by id: the role boxes carry generated ids and a data-label,
    the account-type box is a plain input inside its label, and neither id is
    ours to depend on. The label is what the form shows a human, and what
    Megan pointed at.
    """
    found = _find_labelled(page, text)
    if not found and text == "Over 18":
        # bg_check_sync has driven this box by id on the profile form since
        # 2026-08-26. Worth trying before giving up on a label.
        try:
            state = page.evaluate(
                f"() => {{ const b = document.querySelector('#{ovn.OVER_18_ID}');"
                f" return b ? {{id: '{ovn.OVER_18_ID}', checked: !!b.checked}}"
                f" : null; }}")
        except Exception:                                   # noqa: BLE001
            state = None
        found = state
    if not found:
        raise Refused(f"no {text!r} box on the New Sales Rep form — the form "
                      f"changed, and guessing which box it became is how "
                      f"somebody gets created as the wrong kind of rep")
    if found.get("checked"):
        return
    box_id = found.get("id")
    if box_id:
        label = page.locator(f"label[for='{box_id}']")
        try:
            if label.count():
                label.first.click()
            else:
                page.locator(f"#{box_id}").check(force=True)
        except Exception:                                   # noqa: BLE001
            page.locator(f"#{box_id}").check(force=True)
    else:
        page.get_by_text(text, exact=True).first.click()
    page.wait_for_timeout(250)
    if verbose:
        print(f"    ticked: {text}")


def _open_form(page, rqst: str, *, verbose: bool = True):
    """Click '+ Add Sales Rep' on the rep list and wait for the empty form."""
    btn = page.get_by_role("link", name="Add Sales Rep")
    if not btn.count():
        btn = page.get_by_role("button", name="Add Sales Rep")
    if not btn.count():
        raise Refused("no '+ Add Sales Rep' button on the Sales Reps page")
    btn.first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:                                       # noqa: BLE001
        pass
    first_in, last_in = ovn._name_inputs(page)
    if first_in is None or last_in is None:
        raise Refused("clicked Add Sales Rep but no New Sales Rep form "
                      "appeared (no first/last name boxes)")
    if verbose:
        print("  New Sales Rep form open")
    return first_in, last_in


def create(page, person, *, dry_run: bool = True, verbose: bool = True) -> str:
    """'exists' | 'created' | 'dry' — put this person in OwnerVille.

    `person` needs .first, .last, .email, .phone (a blueink_docs NewStart, or
    anything shaped like one).
    """
    first = (getattr(person, "first", "") or "").strip()
    last = (getattr(person, "last", "") or "").strip()
    email = (getattr(person, "email", "") or "").strip()
    phone = (getattr(person, "phone", "") or "").strip()
    who = f"{first} {last}".strip()

    # NO EMAIL, NO CREATION. The form requires it, the directory is keyed on
    # it, and a rep created without one can never be matched again — so the
    # next run would create them a second time.
    if not (first and last):
        raise Refused(f"{who or '(a blank row)'} has no full name on the "
                      f"chart, so OwnerVille cannot create them. Fix the name "
                      f"on the board and they will be picked up next pass.")
    if not email:
        raise Refused(f"{who} has no email on the chart, so OwnerVille "
                      f"cannot create them. Add their email to the board and "
                      f"they will be picked up on the next pass.")
    if not phone:
        raise Refused(f"{who} has no phone number on the chart, so "
                      f"OwnerVille cannot create them. Add it to the board and "
                      f"they will be picked up on the next pass.")

    rqst = ovn.open_rep_list(page, verbose=verbose)
    cols = ovn._columns(page)
    existing = find_by_email(page, cols, email)
    if existing:
        if verbose:
            print(f"  {who}: already in OwnerVille as "
                  f"{existing.get('full') or existing.get('email')!r}")
        return "exists"

    first_in, last_in = _open_form(page, rqst, verbose=verbose)
    if dry_run:
        # Prove the whole path without writing: every field and box the live
        # run would touch has to be FINDABLE now, or the dry run is worthless.
        absent = [b for b in ("Over 18", NEW_ROLE, ACCOUNT_TYPE)
                  if _find_labelled(page, b) is None]
        if absent:
            _cancel(page)
            raise Refused(f"{who}: the form has no {absent} box(es) — a live "
                          f"run would refuse here, so this dry run does too")
        if verbose:
            print(f"  {who}: WOULD create — {email} · {phone} · "
                  f"{NEW_ROLE} · {ACCOUNT_TYPE} · Over 18")
        _cancel(page)
        return "dry"

    first_in.fill(first)
    last_in.fill(last)
    page.locator("input[name='email']:visible").first.fill(email)
    confirm = page.locator(
        "#confirmEmail:visible, input[name='confirmEmail']:visible").first
    if confirm.count():
        confirm.fill(email)
    page.locator("input[name='phone']:visible").first.fill(phone)

    _tick_labelled(page, "Over 18", verbose=verbose)
    _tick_labelled(page, NEW_ROLE, verbose=verbose)
    _tick_labelled(page, ACCOUNT_TYPE, verbose=verbose)

    # READ THE FORM'S OWN OBJECTIONS BEFORE CLICKING ADD. ov_name_sync learned
    # this on the same page: a save that fails validation does not error, it
    # simply does nothing, and the run reports success it never had.
    bad = ovn._complaints(page)
    if bad:
        _cancel(page)
        raise Refused(f"{who} could not be created in OwnerVille — the "
                      f"form would not accept them ({'; '.join(bad)}). Add "
                      f"them by hand under Sales Reps → + Add Sales Rep.")

    add = page.get_by_role("button", name="Add")
    if not add.count():
        _cancel(page)
        raise Refused(f"{who}: no Add button on the form")
    add.first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:                                       # noqa: BLE001
        pass

    # PROVE IT. Clicking Add is not evidence; the row is. Same reason the
    # Digi Docs day went wrong in the first place -- a step that "ran" is not
    # a step that landed.
    ovn.open_rep_list(page, verbose=False)
    cols = ovn._columns(page)
    made = find_by_email(page, cols, email)
    if not made:
        bad = ovn._complaints(page)
        raise Refused(f"{who} could not be created in OwnerVille — we "
                      f"filled the form and saved, but no record for {email} "
                      f"appeared. Add them by hand under Sales Reps → + Add "
                      f"Sales Rep."
                      + (f" (the form said: {'; '.join(bad)})" if bad else ""))
    if verbose:
        print(f"  ✓ {who}: created (id {made.get('id', '?')})")
    return "created"


def _cancel(page) -> None:
    try:
        btn = page.get_by_role("button", name="Cancel")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(400)
    except Exception:                                       # noqa: BLE001
        pass


def main(argv=None) -> int:
    from automations.digi_docs import roster, run as _run

    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="actually create. Without it, nothing is written.")
    ap.add_argument("--only", default="",
                    help="one person by name, for the first live proof.")
    ap.add_argument("--date", default="",
                    help="chart date (default: today's chart).")
    args = ap.parse_args(argv)

    from automations.digi_docs.preflight import _parse_date
    ws, values = _run._open_tab(None)
    cands = roster.to_send(roster.candidates(values, ws.title))
    want = _parse_date(args.date)
    cohort = roster.starting_today(cands, today=want) if want \
        else roster.starting_today(cands)
    if args.only:
        cohort = [c for c in cohort
                  if c.name.lower() == args.only.strip().lower()]
        if not cohort:
            print(f"nobody called {args.only!r} on this chart")
            return 1
    if not cohort:
        print("no chart for that date — nothing to do")
        return 0

    print(f"{ws.title}: {len(cohort)} person(s) "
          f"({'LIVE' if args.live else 'DRY RUN'})\n")
    made, exists, refused, would = [], [], [], []
    with ovn.session(headless=True) as page:
        for c in cohort:
            try:
                out = create(page, c.person, dry_run=not args.live)
            except (Refused, ovn.Refused) as e:             # noqa: PERF203
                print(f"  ⛔ {e}")
                refused.append(str(e))
                continue
            except Exception as e:                          # noqa: BLE001
                print(f"  ⛔ {c.name}: {type(e).__name__}: {str(e)[:120]}")
                refused.append(f"{c.name}: {type(e).__name__}")
                continue
            if out == "exists":
                exists.append(c.name)
            elif out == "dry":
                would.append(c.name)
            else:
                made.append(c.name)

    # A DRY RUN CREATES NOBODY, AND MUST NOT SAY IT DID (2026-09-14). The first
    # clean dry run reported "created 1" for a pass whose only action was
    # opening a form and clicking Cancel — the exact shape of false success
    # this report spent a whole day being bitten by.
    if would:
        print(f"\nwould create {len(would)} · already there {len(exists)} · "
              f"refused {len(refused)}   (DRY RUN — nobody was created)")
    else:
        print(f"\ncreated {len(made)} · already there {len(exists)} · "
              f"refused {len(refused)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
