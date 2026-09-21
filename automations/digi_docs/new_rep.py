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
import datetime as dt
import html

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
    # _search_rows yields (row, href) PAIRS, not rows — see find_rep_row,
    # which unpacks them the same way. Passing the pair through as a row threw
    # AttributeError inside _row_fields, and it only surfaced on the
    # VERIFICATION read after a save: before that the search matched nothing,
    # so the loop body never ran and the bug stayed invisible through two live
    # attempts.
    for row, _href in ovn._search_rows(page, want):
        fields = ovn._row_fields(page, row, cols)
        if _norm_email(fields.get("email")) == want:
            return fields
    return None


def _name_key(s: str) -> str:
    return " ".join(ovn.norm(s or "").split())


def _plain_prefix(word: str) -> str:
    """The word up to its first letter that is not plain a-z (accents,
    apostrophes, hyphens)."""
    out = ""
    for ch in word or "":
        if not ("a" <= ch.lower() <= "z"):
            break
        out += ch
    return out


def find_by_name(page, cols: dict, first: str, last: str) -> list:
    """Every rep row whose first AND last name equal these, ignoring case,
    accents and spacing. Used only to REFUSE a create -- never to decide
    someone is present or to send them anything (see create).

    Searches the SURNAME alone: the table search matches its rendered text,
    and a full name typed as one term filters to nothing (ov_name_sync)."""
    f, l = _name_key(first), _name_key(last)
    if not (f and l):
        return []
    hits = []
    # One word of the surname, the longest: "Al Mutlaq" typed whole can filter
    # to nothing for the same reason a full name does. The table search does
    # not fold accents, and the accent can be on EITHER side -- "Quinones" on
    # the board, "Quiñones" in OwnerVille -- so when the whole word finds
    # nobody, look again on its first three plain letters. The exact
    # comparison below does the deciding either way.
    word = _plain_prefix(max(last.split(), key=len))
    terms = [t for t in (word, word[:3]) if len(t) >= 3]
    for term in dict.fromkeys(terms):
        for row, _href in ovn._search_rows(page, term):
            fields = ovn._row_fields(page, row, cols)
            rf = _name_key(fields.get("first"))
            rl = _name_key(fields.get("last"))
            if not (rf or rl):
                parts = _name_key(fields.get("full")).split()
                rf, rl = ((parts[0], " ".join(parts[1:]))
                          if len(parts) >= 2 else ("", ""))
            if rf == f and rl == l:
                hits.append(fields)
        if hits:
            break
    return hits


# The New Sales Rep form's text boxes, by the names bg_check_sync proved live
# on this page (ov_name_sync: "whose name boxes are `fname` and `lname`").
# Ordered: the first selector that exists wins.
FIELDS = (
    ("first name", ("input[name='fname']:visible", "input#fname:visible")),
    ("last name", ("input[name='lname']:visible", "input#lname:visible")),
    ("email", ("input[name='email']:visible", "input#email:visible")),
    ("confirm email", ("input[name='confirmEmail']:visible",
                       "input#confirmEmail:visible")),
    # `cellphone`, NOT `phone` (--dump-form, 2026-09-14). Two live attempts
    # died on the obvious guess. The form's own dump is the only reason this
    # line is right, and the fallbacks are there for the day OwnerVille
    # renames it -- not as a substitute for asking.
    ("phone", ("input[name='cellphone']:visible", "input#cellphone:visible",
               "input[name='phone']:visible")),
)


def _field(page, selectors):
    """The first of these selectors that is actually on the page, or None."""
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count():
                return loc
        except Exception:                                   # noqa: BLE001
            continue
    return None


def _fill(page, selectors, value, label, who):
    """Type into one box, RE-RESOLVED at the moment we type.

    The first live creation died on `Locator.fill: Timeout 30000ms exceeded`
    (2026-09-14). The handles came from a scan of every visible input taken
    when the form opened, and `nth(i)` into that collection stops pointing at
    the same element the moment the form's own scripts finish wiring
    themselves up -- the Start Date picker alone re-renders its neighbours.
    Resolving by name at the point of use is the fix, and a 15s cap turns a
    wedged box into a named failure instead of half a minute of silence.
    """
    box = _field(page, selectors)
    if box is None:
        raise Refused(f"{who} could not be created in OwnerVille — the New "
                      f"Sales Rep form has no {label} box. Add them by hand "
                      f"under Sales Reps → + Add Sales Rep.")
    try:
        box.fill(value, timeout=15000)
    except Exception as e:                                  # noqa: BLE001
        raise Refused(f"{who} could not be created in OwnerVille — the form's "
                      f"{label} box would not accept text "
                      f"({type(e).__name__}). Add them by hand under Sales "
                      f"Reps → + Add Sales Rep.")


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

    # SAME NAME, DIFFERENT EMAIL IS NOT "ABSENT" (2026-09-21). Jaylen Anthony
    # was already in OwnerVille under another email, the email lookup correctly
    # found nobody with the board's address, and this created him a second
    # time -- two rows on View Progress, the send refused as ambiguous, and
    # Megan deleted the copy by hand. The email rule stays: a name match is
    # never used to SEND or to call someone present. It is used only to STOP,
    # because a second record is the one mistake a person has to clean up.
    namesakes = find_by_name(page, cols, first, last)
    if namesakes:
        mails = sorted({(r.get("email") or "no email").strip()
                        for r in namesakes})
        raise Refused(
            f"{who} was not created: OwnerVille already has "
            f"{len(namesakes)} record(s) with this name ({', '.join(mails)}) "
            f"but none with {email}. If that is them, correct the email on "
            f"the board or in OwnerVille so the two match; if it is a "
            f"different person, add them by hand under Sales Reps → + Add "
            f"Sales Rep.")

    first_in, last_in = _open_form(page, rqst, verbose=verbose)
    if dry_run:
        # Prove the whole path without writing: every field and box the live
        # run would touch has to be FINDABLE now, or the dry run is worthless.
        # CHECK WHAT THE LIVE RUN WOULD TOUCH -- ALL of it. The first dry
        # run passed while only looking at the checkboxes, and the live run
        # that followed died on a text box. A dry run that skips half the
        # form is worth exactly as much as no dry run.
        absent = [lbl for lbl, sels in FIELDS if _field(page, sels) is None]
        absent += [b for b in ("Over 18", NEW_ROLE, ACCOUNT_TYPE)
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

    values = (first, last, email, email, phone)
    for (label, sels), value in zip(FIELDS, values):
        _fill(page, sels, value, label, who)

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
    # THREE LOOKS, NOT ONE (2026-09-21). Faith Moss was the first create of the
    # day: the save worked (record 9505694, visible in OwnerVille minutes
    # later), but the one search right after it found nothing, so the run
    # posted "add them by hand" -- an instruction that, followed, makes a
    # duplicate. A new record can take a few seconds to reach the list.
    made = None
    for wait_ms in (0, 5000, 15000):
        if wait_ms:
            page.wait_for_timeout(wait_ms)
        ovn.open_rep_list(page, verbose=False)
        cols = ovn._columns(page)
        made = find_by_email(page, cols, email)
        if made:
            break
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


def _parse_date(s: str):
    """'9/21', '9/21/26' or an ISO date. Month/day assumes the coming year's
    chart, which is what somebody typing 9/21 in September means."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m/%d"):
        try:
            d = dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if fmt == "%m/%d":
            d = d.replace(year=dt.date.today().year)
        return d
    raise SystemExit(f"cannot read a date out of {s!r} — try 9/21 or 2026-09-21")


def _dump_form() -> int:
    """Print every input on the New Sales Rep form, and stop.

    Guessing field names is what cost the first two live attempts: `phone`
    seemed obvious and the form does not have it. The page will say what its
    boxes are called if we ask it, and asking is free — it opens the form,
    reads, and clicks Cancel.
    """
    rqst_page = ovn.session(headless=True)
    with rqst_page as page:
        rqst = ovn.open_rep_list(page)
        _open_form(page, rqst)
        rows = page.evaluate("""() => [...document.querySelectorAll(
            'input, select, textarea')]
            .filter(e => e.offsetParent !== null)
            .map(e => ({tag: e.tagName.toLowerCase(), type: e.type || '',
                        name: e.name || '', id: e.id || '',
                        ph: e.placeholder || '',
                        label: (document.querySelector(
                            'label[for="' + e.id + '"]') || {}).innerText || ''
                       }))""")
        print(f"\n{len(rows)} visible field(s) on the New Sales Rep form:\n")
        for r in rows:
            print("  %-9s %-10s name=%-18s id=%-18s label=%r" % (
                r["tag"], r["type"], r["name"] or "-", r["id"] or "-",
                (r["label"] or r["ph"] or "").strip()[:34]))
        _cancel(page)
    return 0


def main(argv=None) -> int:
    from automations.digi_docs import roster, run as _run

    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="actually create. Without it, nothing is written.")
    ap.add_argument("--only", default="",
                    help="one person by name, for the first live proof.")
    ap.add_argument("--date", default="",
                    help="chart date (default: today's chart).")
    ap.add_argument("--dump-form", action="store_true",
                    help="open the New Sales Rep form, print every input it "
                         "has, and stop. Reads only; creates nobody.")
    args = ap.parse_args(argv)

    if args.dump_form:
        return _dump_form()

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
