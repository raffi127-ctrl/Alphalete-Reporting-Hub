"""Run the bookmarklet's own code from Python, in a driven Apex page.

Megan, 2026-11-10: *"we need it to do both like it does now for raf — look at
pending and complete if existing or create if not on there yet."*

`filler.py` ALREADY DOES BOTH, and has been doing Raf's weeks since September:
`runPerson` completes the three tabs of somebody on Pending, `addMissing`
creates the ones Apex has never heard of, behind an All Employees check so a
create never lands on an existing payroll record. What it cannot do is run
without a person pasting a bookmarklet.

`eco_run` is the other end -- headless, per office, on the ICD's own machine --
and it only ever learned to fill the create form. So the gap is not "what
should it do"; it is "that logic is in a browser and this is Python".

THIS LOADS THAT LOGIC RATHER THAN RE-IMPLEMENTING IT. `_JS` is an ordinary
script that installs its entry points on `window`, so a driven page can
evaluate it and then call them. Writing a third filler against a page this
session cannot see is exactly how the first two came to disagree.

WHAT IS DELIBERATELY NOT HERE: any decision about who is in the week, any
Social, and any Save of its own. The script saves as it always has; this only
starts it and reads back what it said.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from automations.apex_new_starts import filler as F

# Installed by the script on load. Checked by name rather than assumed, because
# a script that half-evaluates leaves some of these and not others, and calling
# a missing one reads as "Apex refused it".
ENTRY_POINTS = ("__ansAddMissing", "__ansOpen", "__ansDoPage", "__ansRoster",
                "__ansRunPerson", "__ansExistsAnywhere", "__ansGoSpa")


def script(people: Optional[List[Dict]] = None, week: str = "") -> str:
    """The bookmarklet's body, as plain evaluatable JavaScript.

    NOT `build_js`: that minifies to one line and wraps it in `javascript:` for
    an href, and `_guard` rejects HTML entities that only matter inside one.
    Evaluated directly, neither applies -- and keeping the newlines means a
    stack trace from it still names a line.
    """
    return F._JS % {
        "data": json.dumps(people, separators=(",", ":")) if people is not None else "null",
        "week": str(week).replace("'", ""),
        "build": F._now_stamp().replace("'", ""),
        "notice": "null",
        "start": "",
        "built_at": str(int(F._now_ms())),
        "role": json.dumps(F.SECURITY_ROLE_LABEL.lower()),
    }


def load(page, people: Optional[List[Dict]] = None, week: str = "",
         log=print) -> List[str]:
    """Evaluate the script in `page`; return the entry points that appeared.

    Raises nothing on a partial load -- the caller decides, because "three of
    four" is a different problem from "none", and a missing one must never be
    called and read back as Apex refusing something.
    """
    page.evaluate(script(people, week))
    got = page.evaluate(
        "(names) => names.filter(n => typeof window[n] !== 'undefined')",
        list(ENTRY_POINTS))
    missing = [n for n in ENTRY_POINTS if n not in got]
    if missing:
        log("  the Apex script loaded only partly — missing %s"
            % ", ".join(missing))
    else:
        log("  Apex script loaded (%d entry points)" % len(got))
    return list(got)


def ready(page) -> bool:
    """Every entry point is there."""
    try:
        got = page.evaluate(
            "(names) => names.filter(n => typeof window[n] !== 'undefined')",
            list(ENTRY_POINTS))
    except Exception:          # noqa: BLE001
        return False
    return len(got) == len(ENTRY_POINTS)


def _plain(value) -> str:
    """The ONE place a Secret is unwrapped. Both the engine path and the
    driven path come through here, so `reveal()` stays countable: the wrapper
    is worth nothing the moment it is called in two places that each think
    they are the only one."""
    return (value.reveal() if hasattr(value, "reveal") else str(value or ""))


def hand_over(page, *, genders=None, socials=None, log=print) -> dict:
    """Put the two things only a PERSON ever supplied into the driven page.

    The engine reads a Gender out of `window.__ansGender` and a Social out of
    `window.__ansSSN`, keyed by its own `norm(name)`. In the extension a person
    types both into the panel. Driven, nobody is sitting there, so they have to
    arrive another way -- Gender off the office's onboarding board, the Social
    out of the signed Blue Ink packet.

    NOTHING IS LOGGED BUT COUNTS. A Social reaches this page and no further: it
    is written straight into the map the engine reads and never returned,
    echoed or put in a message. Unwrapping goes through `_plain`, the one
    `reveal()` call site in this module, which is the point of the wrapper.

    Returns {"genders": n, "socials": n} -- how many landed, never which.
    """
    pairs_g = {str(k): str(v) for k, v in (genders or {}).items() if str(v or "").strip()}
    pairs_s = {}
    for k, v in (socials or {}).items():
        raw = _plain(v)
        digits = "".join(c for c in raw if c.isdigit())
        # Nine digits or nothing. A short one would be typed into a payroll
        # record as a real Social and Apex would take it.
        if len(digits) == 9:
            pairs_s[str(k)] = digits
    page.evaluate(
        """([g, s]) => {
             const norm = x => (x || '').replace(/\\s+/g, ' ').trim().toLowerCase();
             window.__ansGender = window.__ansGender || {};
             window.__ansSSN = window.__ansSSN || {};
             for (const k in g) window.__ansGender[norm(k)] = g[k];
             for (const k in s) window.__ansSSN[norm(k)] = s[k];
           }""",
        [pairs_g, pairs_s])
    log("  handed the page %d gender(s) and %d Social(s)"
        % (len(pairs_g), len(pairs_s)))
    return {"genders": len(pairs_g), "socials": len(pairs_s)}


# What a person needs from Apex, decided BEFORE anything is typed.
COMPLETE = "complete"      # already on Pending — fill the three tabs
ADD = "add"                # Apex has never heard of them — create the record
BY_HAND = "by_hand"        # in Apex but not on Pending, or we could not tell


def to_roster(page, log=print) -> bool:
    """Get to Roster -> Employees, the way the engine does.

    EVERY SIGNED-IN APEX SESSION LANDS ON THE CHANGE-PASSWORD PAGE, and that
    page has no roster on it -- a triage run straight from there was told the
    page offers "log off, support, feedback" and correctly refused everybody
    (2026-11-11). A page.goto redirects back to it, which is why this moves
    through the app's own router instead of the address bar.
    """
    # Already there.
    if "/roster" in (page.url or "").lower():
        return True

    # 1. The app's own router, which only exists INSIDE the Angular app. From
    #    the change-password page there is no injector to reach, so this
    #    quietly returns false there rather than erroring (2026-11-11).
    try:
        if page.evaluate("async () => await window.__ansGoSpa('/roster')"):
            page.wait_for_timeout(1200)
            return True
    except Exception:          # noqa: BLE001
        pass

    # 2. THE LEFT-HAND NAV. Apex lands every session on an ASP.NET Identity
    #    page that is not the Angular app at all -- no router to call, and a
    #    typed URL redirects straight back to it. The nav link is a real link
    #    and the only way across, which is why the instructions have always
    #    said to use it.
    try:
        went = page.evaluate(r"""() => {
            const want = [...document.querySelectorAll('a[href]')];
            const byHref = want.find(a => /[/]roster\b/i.test(a.getAttribute('href') || ''));
            const byText = want.find(a =>
                (a.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase() === 'employees');
            const hit = byHref || byText;
            if (!hit) return '';
            hit.click();
            return hit.getAttribute('href') || 'clicked';
        }""")
    except Exception as e:      # noqa: BLE001
        log("  could not reach the roster: %s" % type(e).__name__)
        return False
    if not went:
        log("  no Roster link on %s" % (page.url or "?"))
        return False
    try:
        page.wait_for_url("**/roster**", timeout=20000)
    except Exception:          # noqa: BLE001
        page.wait_for_timeout(2500)
    if "/roster" not in (page.url or "").lower():
        log("  the Roster link did not land: still on %s" % (page.url or "?"))
        return False
    page.wait_for_timeout(1200)
    return True


def keep_loaded(page, people=None, week: str = "", log=print) -> bool:
    """Put the engine back if the page has moved out from under it.

    CROSSING FROM THE IDENTITY PAGE INTO THE APP IS A FULL PAGE LOAD. Apex
    lands every session on /Identity/Account/Manage/ChangePassword, which is
    not the Angular app, and the only way across is its nav link -- a real
    link, so everything on `window` goes with it, this script included. The
    first complete rehearsal reached the roster, lost the engine on the way,
    and then could not open anybody's record (2026-11-11).

    Idempotent and cheap: it checks first and only re-evaluates when something
    is actually missing.
    """
    if ready(page):
        return True
    load(page, people, week, log=log)
    return ready(page)


def triage(page, people, log=print) -> Dict[str, dict]:
    """{name: {"need": COMPLETE|ADD|BY_HAND, "why": str}} for the whole week.

    Megan, 2026-11-11: "Lucy Eco Machine needs to be able to know if they need
    added or if they just need the user profile completed because they're
    already on the pending. So we have to build it to recognize either."

    Both of this week's checks landed on somebody ALREADY on Pending (David
    Flores, Victoria Newsom) -- an ICD's people arrive there by themselves once
    they are in OwnerVille, so completing is the common case and creating is
    the rare one. Guessing from a failed run gets that backwards.

    THE ORDER MATTERS. Pending first, because that is the cheap in-page
    lookup; All Employees only for the ones it did not find, because that one
    clicks a tab and waits. And a person who is in Apex but NOT on Pending is
    neither: creating them duplicates a real payroll record and completing
    them has nowhere to start, so they are named for a person.

    "COULD NOT TELL" IS NEVER "NOT THERE". The engine returns a string when it
    cannot read the All Employees tab, and that string becomes BY_HAND.
    """
    out: Dict[str, dict] = {}
    for p in people or []:
        name = str((p or {}).get("name") or "").strip()
        if not name:
            continue
        try:
            found = page.evaluate(
                "async (p) => { const id = await window.__ansOpen(p);"
                " return id ? String(id) : ''; }", p)
        except Exception as e:      # noqa: BLE001
            out[name] = {"need": BY_HAND,
                         "why": "could not look on Pending (%s)" % type(e).__name__}
            continue
        if found:
            # KEEP THE ID. Completing somebody means going to
            # /employees/<id>/edit/..., so throwing it away here means looking
            # them up all over again -- or, worse, filling whatever page
            # happens to be showing (2026-11-11: the first complete rehearsal
            # filled nothing, on the roster).
            out[name] = {"need": COMPLETE, "why": "on Pending", "id": found}
            continue
        try:
            there = page.evaluate(
                "async (p) => await window.__ansExistsAnywhere(p)", p)
        except Exception as e:      # noqa: BLE001
            out[name] = {"need": BY_HAND,
                         "why": "could not check All Employees (%s)" % type(e).__name__}
            continue
        if isinstance(there, str):
            out[name] = {"need": BY_HAND, "why": there[:160]}
        elif there:
            out[name] = {"need": BY_HAND,
                         "why": "in Apex but not on Pending — find them on "
                                "All Employees"}
        else:
            out[name] = {"need": ADD, "why": "not in Apex at all"}
    tally = {}
    for v in out.values():
        tally[v["need"]] = tally.get(v["need"], 0) + 1
    log("  triage: %s" % (", ".join("%d to %s" % (n, k)
                                    for k, n in sorted(tally.items())) or "nobody"))
    return out


def set_dropdown(page, label: str, value: str, log=print) -> bool:
    """Set one of Apex's dropdowns with a REAL browser click.

    THE ENGINE CANNOT DO THIS ANY MORE, and that is the whole reason this
    exists. Since the Beta rewrite its in-page clicks do nothing at all to
    these widgets: a probe on 2026-11-12 drove Position, Basis of Pay and Pay
    Frequency both ways on the same live record -- the engine's synthetic
    click left the box showing nothing, and a driver click showed the right
    value every time. Browsers mark JavaScript-made events untrusted, and
    whatever Apex now binds these to ignores them.

    So a bookmarklet can never fill these fields again. Only something driving
    the browser from outside can, which is this.

    The hidden ...ID stays empty for a moment afterwards -- Apex writes it on
    blur or submit -- so this checks what the widget DISPLAYS, not the id.
    """
    box = page.evaluate(
        """(L) => { const el = window.__ansFieldFor(L);
             if (!el) return '';
             const sp = el.parentElement.querySelector('.k-dropdown, .k-widget');
             if (!sp) return '';
             sp.setAttribute('data-ans-pick', '1');
             return el.id || el.name || 'x'; }""", label)
    if not box:
        # Never silent. A failure that prints nothing is indistinguishable
        # from not having run at all, which cost a whole live run to notice.
        log("    %s: no box or no dropdown beside it" % label)
        return False
    try:
        page.click("[data-ans-pick='1']", timeout=5000)
        page.wait_for_timeout(700)
        # the row, by its exact words
        try:
            page.click("ul.k-list li:text-is(%r)" % value, timeout=4000)
        except Exception:      # noqa: BLE001
            page.click("li:text-is(%r)" % value, timeout=3000)
        page.wait_for_timeout(700)
    except Exception as e:     # noqa: BLE001
        log("    %s: could not pick %r (%s)" % (label, value, type(e).__name__))
        page.evaluate("() => document.querySelectorAll('[data-ans-pick]')"
                      ".forEach(e => e.removeAttribute('data-ans-pick'))")
        return False
    shown = page.evaluate(
        """(L) => { const el = window.__ansFieldFor(L);
             const sp = el && el.parentElement.querySelector('.k-dropdown, .k-widget');
             return sp ? (sp.innerText || '').replace(/\\s+/g, ' ').trim() : ''; }""",
        label)
    page.evaluate("() => document.querySelectorAll('[data-ans-pick]')"
                  ".forEach(e => e.removeAttribute('data-ans-pick'))")
    ok = bool(shown) and value.lower() in shown.lower()
    if not ok:
        log("    %s: clicked, but it shows %r" % (label, shown))
    return ok


def set_dropdowns(page, pairs, log=print) -> dict:
    """{label: value} -> {"set": [...], "missed": [...]}."""
    done, missed = [], []
    for label, value in (pairs or {}).items():
        if not str(value or "").strip():
            continue
        (done if set_dropdown(page, label, value, log=log) else missed).append(label)
    log("    set by click: %s%s"
        % (", ".join(done) or "nothing",
           ("  |  could not: " + ", ".join(missed)) if missed else ""))
    return {"set": done, "missed": missed}


def type_into(page, label: str, value: str, log=print) -> bool:
    """Type into a box with real keystrokes.

    Rate of Pay is a Kendo numeric widget and ignores a JavaScript-set value
    exactly as the dropdowns ignore a JavaScript click: the engine reported it
    filled and Apex said "Rate of Pay is required" on save (2026-11-12).
    Typed through the driver, the keystrokes are trusted and it takes.
    """
    # THE BOX A PERSON TYPES IN, not the one the form submits. A Kendo
    # numeric widget is a visible input over a hidden one, and fieldFor hands
    # back the hidden one -- which the driver rightly refuses to type into,
    # because it is invisible (TimeoutError, 2026-11-12).
    found = page.evaluate(
        """(L) => { const el = window.__ansFieldFor(L);
             if (!el) return '';
             let box = el;
             if (el.type === 'hidden' || !el.offsetParent) {
               const w = el.parentElement;
               const vis = w ? [...w.querySelectorAll('input')]
                 .filter(i => i.offsetParent && i.type !== 'hidden') : [];
               if (vis.length) box = vis[0];
             }
             if (!box.offsetParent) return '';
             box.setAttribute('data-ans-type', '1');
             return box.id || box.name || 'x'; }""", label)
    if not found:
        log("    %s: no box" % label)
        return False
    try:
        page.fill("[data-ans-type='1']", "")
        page.type("[data-ans-type='1']", str(value), delay=40)
        page.evaluate("""() => { const e = document.querySelector('[data-ans-type]');
              if (e) e.dispatchEvent(new Event('blur', {bubbles: true})); }""")
        page.wait_for_timeout(500)
        got = page.evaluate("() => { const e = document.querySelector('[data-ans-type]');"
                            " return e ? (e.value || '') : ''; }")
    except Exception as e:     # noqa: BLE001
        log("    %s: could not type (%s)" % (label, type(e).__name__))
        got = ""
    page.evaluate("() => document.querySelectorAll('[data-ans-type]')"
                  ".forEach(e => e.removeAttribute('data-ans-type'))")
    ok = bool(str(got).strip())
    log("    %s: typed %r -> %r%s" % (label, value, got, "" if ok else "  STILL EMPTY"))
    return ok


def wait_for_field(page, label: str, *, seconds: int = 25, people=None,
                   log=print) -> bool:
    """Wait until the engine can actually FIND a named box on this page.

    Waiting for "Loading ... data" to disappear is not enough: the employment
    tab clears that message before its fields exist, so a run that had just
    filled everything correctly found nothing at all on the next attempt
    (2026-11-12). The only honest ready signal is the box itself.

    Re-loads the engine as it goes, because the thing that most often makes
    fieldFor return nothing is the script having gone with a page load.
    """
    for i in range(max(1, seconds * 2)):
        if not ready(page):
            load(page, people, "", log=lambda *a: None)
        try:
            if page.evaluate("(L) => !!window.__ansFieldFor(L)", label):
                if i:
                    log("    (%s appeared after %.1fs)" % (label, i * 0.5))
                return True
        except Exception:      # noqa: BLE001 — mid-navigation; try again
            pass
        page.wait_for_timeout(500)
    log("    %s never appeared on %s" % (label, page.url or "?"))
    return False


# --------------------------------------------------------------- by NAME
# The tax tab cannot be driven by label: Apex puts "Fed. Tax Exempt" on the
# Marital Status box and gives the two Social boxes no label at all. Their
# `name` attributes are clean, so these take a name instead (2026-11-12).

_MARK = "data-ans-box"


def _mark_by_name(page, name: str) -> str:
    """Tag the element with this name, and hand back the one a person uses.

    A Kendo widget is a visible box over a hidden one; the hidden one is what
    submits and the visible one is what you type into or click.
    """
    return page.evaluate(
        """([n, mark]) => {
             document.querySelectorAll('[' + mark + ']')
               .forEach(e => e.removeAttribute(mark));
             const el = document.querySelector('[name="' + n + '"]')
                      || document.getElementById(n);
             if (!el) return '';
             let box = el;
             if (el.type === 'hidden' || !el.offsetParent) {
               const w = el.parentElement;
               const vis = w ? [...w.querySelectorAll('input')]
                 .filter(i => i.offsetParent && i.type !== 'hidden') : [];
               if (vis.length) box = vis[0];
             }
             box.setAttribute(mark, '1');
             const sp = el.parentElement
               ? el.parentElement.querySelector('.k-dropdown, .k-widget') : null;
             if (sp) sp.setAttribute(mark + '-widget', '1');
             return box.offsetParent ? 'visible' : 'hidden';
           }""", [name, _MARK])


def set_dropdown_by_name(page, name: str, value: str, log=print) -> bool:
    """Pick `value` in the dropdown whose input is called `name`."""
    if not _mark_by_name(page, name):
        log("    %s: no box" % name)
        return False
    try:
        page.click("[%s-widget]" % _MARK, timeout=5000)
        page.wait_for_timeout(700)
        try:
            page.click("ul.k-list li:text-is(%r)" % value, timeout=4000)
        except Exception:      # noqa: BLE001
            page.click("li:text-is(%r)" % value, timeout=3000)
        page.wait_for_timeout(600)
    except Exception as e:     # noqa: BLE001
        log("    %s: could not pick %r (%s)" % (name, value, type(e).__name__))
        return False
    shown = page.evaluate(
        "(m) => { const e = document.querySelector('[' + m + '-widget]');"
        " return e ? (e.innerText || '').replace(/\\s+/g, ' ').trim() : ''; }", _MARK)
    ok = bool(shown) and value.lower() in shown.lower()
    if not ok:
        log("    %s: clicked, shows %r" % (name, shown))
    return ok


def type_by_name(page, name: str, value, log=print, *, secret: bool = False) -> bool:
    """Type into the box called `name`, with real keystrokes.

    `secret` keeps the value out of the log -- it is a Social, and the whole
    point of the Secret wrapper is that it never reaches a terminal.
    """
    raw = _plain(value)
    if not raw:
        return False
    if not _mark_by_name(page, name):
        log("    %s: no box" % name)
        return False
    try:
        page.fill("[%s]" % _MARK, "")
        page.type("[%s]" % _MARK, raw, delay=30)
        page.evaluate("(m) => { const e = document.querySelector('[' + m + ']');"
                      " if (e) e.dispatchEvent(new Event('blur', {bubbles: true})); }",
                      _MARK)
        page.wait_for_timeout(400)
        got = page.evaluate("(m) => { const e = document.querySelector('[' + m + ']');"
                            " return e ? (e.value || '') : ''; }", _MARK)
    except Exception as e:     # noqa: BLE001
        log("    %s: could not type (%s)" % (name, type(e).__name__))
        return False
    ok = bool(str(got).strip())
    log("    %s: %s" % (name, "set" if ok else "STILL EMPTY")
        if secret else "    %s: %r -> %r" % (name, raw, got))
    return ok


def password_email_off(page, log=print) -> None:
    """Untick "Override the user's password with a temporary password".

    It moved to the profile tab in the rewrite and it is the same hazard as
    the create form's: saving with it on emails the person. Set, never left
    as found.
    """
    state = page.evaluate(
        """() => {
             const lab = [...document.querySelectorAll('label')]
               .find(l => /override .*password/i.test(l.innerText || ''));
             if (!lab) return 'absent';
             const box = lab.querySelector('input[type=checkbox]')
               || (lab.htmlFor ? document.getElementById(lab.htmlFor) : null)
               || (lab.parentElement
                   ? lab.parentElement.querySelector('input[type=checkbox]') : null);
             if (!box) return 'no box';
             if (!box.checked) return 'already off';
             box.setAttribute('data-ans-pw', '1');
             return 'ON';
           }""")
    if state == "ON":
        # A DRIVER CLICK, not box.click(). The rewrite's controls ignore
        # events JavaScript makes -- that is the whole finding of 2026-11-12 --
        # and this is the one tick whose state emails a real person.
        try:
            page.click("[data-ans-pw]", timeout=4000)
            page.wait_for_timeout(300)
        except Exception as e:     # noqa: BLE001
            log("    password email: STILL ON -- could not untick (%s)"
                % type(e).__name__)
            return
        still = page.evaluate(
            "() => { const b = document.querySelector('[data-ans-pw]');"
            " return b ? !!b.checked : false; }")
        state = "STILL ON -- do not save" if still else "was ON, now off"
    log("    password email: %s" % state)


# What each tab holds, as Apex names it now. Read off a live record on
# 2026-11-12 (resources/apex-after-the-beta-rewrite.md). Labels for the
# employment tab, NAMES for the other two -- see the note above.
PROFILE_TEXT = (("FirstName", "first"), ("MiddleName", "middle"),
                ("LastName", "last"), ("EmailAddress", "account_email"),
                ("BirthDay", "dob"), ("StreetLine1", "address1"),
                ("AptNum", "apt"), ("StreetLine2", "address2"),
                ("City", "city"), ("PostalCode", "zip"),
                ("PhoneNumber", "home_phone"))
PROFILE_PICKS = (("Gender_input", "gender"), ("StateProvinceID", "state"),
                 ("CountryID", "country"))
TAX_PICKS = (("MaritalStatus_input", "marital_status"),
             ("StateToBeTaxedIn_input", "tax_state"))
# Claim Dependants has NO name attribute, so it is the one field on the tax
# tab that has to go by label -- and Apex refuses the tab without it. Apex
# spells it with an A, which is why filler.LABEL_FOR does too.
TAX_BY_LABEL = (("Claim Dependants", "claim_dependents"),)

# Every key the three tabs can fill, so a caller can say what it is NOT
# filling. Checked against filler.PAGE_OF by the tests -- the two maps
# disagreeing is how a value would quietly stop being typed.
FILLS = (tuple(k for _n, k in PROFILE_TEXT + PROFILE_PICKS)
         + tuple(k for _n, k in TAX_PICKS)
         + tuple(k for _l, k in TAX_BY_LABEL))


# The starred boxes. Apex refuses the tab when one of these is blank, and the
# refusal names only the first -- so a run that is missing three of them looks
# like three separate failures. Reported up front instead.
PROFILE_REQUIRED = ("first", "last", "account_email", "dob", "gender",
                    "address1", "city", "state", "zip", "country")
TAX_REQUIRED = ("marital_status", "claim_dependents", "tax_state")


def absent(values, required) -> list:
    """Which starred boxes this person has no value for."""
    return [k for k in required if not str(values.get(k) or "").strip()]


def fill_profile(page, values, log=print) -> dict:
    """The User Profile & Account tab. Never presses Save."""
    set_, miss = [], []
    for name, key in PROFILE_PICKS:
        v = values.get(key)
        if v and set_dropdown_by_name(page, name, v, log=log):
            set_.append(name)
        elif v:
            miss.append(name)
    for name, key in PROFILE_TEXT:
        v = values.get(key)
        if v and type_by_name(page, name, v, log=log):
            set_.append(name)
        elif v:
            miss.append(name)
    gaps = absent(values, PROFILE_REQUIRED)
    if gaps:
        log("    NO VALUE FOR (Apex requires these): %s" % ", ".join(gaps))
    # ALWAYS, and last: a save with this on emails the person.
    password_email_off(page, log=log)
    return {"set": set_, "missed": miss, "absent": gaps}


def fill_tax(page, values, social=None, log=print) -> dict:
    """The Tax & Bank Information tab, Social included. Never presses Save.

    The Social is typed and never logged -- `type_by_name(secret=True)` says
    only whether a box took it.
    """
    set_, miss = [], []
    for name, key in TAX_PICKS:
        v = values.get(key)
        if v and set_dropdown_by_name(page, name, v, log=log):
            set_.append(name)
        elif v:
            miss.append(name)
    for label, key in TAX_BY_LABEL:
        v = values.get(key)
        if v and type_into(page, label, v, log=log):
            set_.append(label)
        elif v:
            miss.append(label)
    if social is not None:
        ok1 = type_by_name(page, "SSN", social, log=log, secret=True)
        ok2 = type_by_name(page, "ConfirmSSN", social, log=log, secret=True)
        (set_ if (ok1 and ok2) else miss).append("Social")
    gaps = absent(values, TAX_REQUIRED)
    if gaps:
        log("    NO VALUE FOR (Apex requires these): %s" % ", ".join(gaps))
    return {"set": set_, "missed": miss, "absent": gaps}


def wait_for_field_named(page, name: str, *, seconds: int = 25, people=None,
                         log=print) -> bool:
    """wait_for_field, by `name` rather than by label.

    The profile and tax tabs are full page loads of their own, and each one
    clears "Loading ... data" before its boxes exist -- the same trap the
    employment tab set. Neither tab can be waited on by label (Apex labels
    its tax fields wrongly), so this waits on the name attribute.
    """
    for i in range(max(1, seconds * 2)):
        if not ready(page):
            load(page, people, "", log=lambda *a: None)
        try:
            if page.evaluate(
                    "(n) => !!document.querySelector('[name=\"' + n + '\"]')",
                    name):
                if i:
                    log("    (%s appeared after %.1fs)" % (name, i * 0.5))
                return True
        except Exception:      # noqa: BLE001 — mid-navigation; try again
            pass
        page.wait_for_timeout(500)
    log("    %s never appeared on %s" % (name, page.url or "?"))
    return False


# ------------------------------------------------- all three tabs, in order
TABS = (
    # (what to call it, the path, the box that proves the tab is ready)
    ("employment record", "employment-record", None),
    ("user profile", "user-profile", "Gender_input"),
    ("tax & bank", "bank-info", "MaritalStatus_input"),
)


def go_tab(page, apex_id, path: str, *, people=None, log=print) -> bool:
    """Move to one of an employee's three tabs, and come back loaded.

    EVERY TAB IS A FULL PAGE LOAD, so the injected script goes with it and has
    to be put back on the other side -- and `page.goto` is no use here: Apex
    lands every session on its change-password page and a typed URL redirects
    straight back to it. The way across is the app's own navigation.
    """
    where = "/employees/%s/edit/%s" % (apex_id, path)
    if where in (page.url or ""):
        return keep_loaded(page, people, "", log=lambda *a: None)
    keep_loaded(page, people, "", log=lambda *a: None)
    try:
        page.evaluate("async (p) => await window.__ansGoSpa(p)", where)
    except Exception as e:     # noqa: BLE001
        log("    could not navigate to %s (%s)" % (path, type(e).__name__))
        return False
    page.wait_for_timeout(1500)
    if where not in (page.url or ""):
        log("    did not land on %s (sitting on %s)" % (path, page.url))
        return False
    return keep_loaded(page, people, "", log=lambda *a: None)


def fill_employment(page, who, log=print) -> dict:
    """The employment record. Never presses Save.

    The dropdowns are set from HERE, by real click, because the engine's
    in-page clicks do nothing to them since the Beta rewrite. The engine then
    fills the plain text boxes, which it has never had trouble with.
    """
    pages = who.get("pages") or {}
    labels = pages.get("employment") or {}
    picks = {k: v for k, v in labels.items()
             if k in ("Position", "Basis of Pay", "Pay Frequency",
                      "State Working In", "Department")}
    set_, miss = [], []
    if picks:
        got = set_dropdowns(page, picks, log=log)
        set_ += list(got.get("set") or [])
        miss += list(got.get("missed") or [])
    # Rate of Pay is a numeric widget and ignores a JS-set value the same way:
    # it read as filled and Apex refused the save for a missing rate.
    rate = labels.get("Rate of Pay")
    if rate:
        (set_ if type_into(page, "Rate of Pay", rate, log=log)
         else miss).append("Rate of Pay")
    # THE TEXT BOXES ONLY. The engine's in-page clicks cannot fill these
    # dropdowns on the Beta rewrite, and asking it about them afterwards gets
    # a false "missed" for all five -- the hidden ...ID is empty until Apex
    # writes it at submit. The display is what was checked above, by the code
    # that actually set them.
    text_only = dict(who)
    text_only["pages"] = dict(pages)
    text_only["pages"]["employment"] = {
        k: v for k, v in labels.items() if k not in picks and k != "Rate of Pay"}
    engine = page.evaluate(
        "async (p) => await window.__ansDoPage(p, 'employment')",
        text_only) or {}
    set_ += list(engine.get("done") or [])
    miss += list(engine.get("miss") or [])
    return {"set": set_, "missed": miss, "absent": []}


def complete_person(page, who, apex_id, *, values=None, social=None,
                    save=None, log=print) -> dict:
    """Walk one person's three tabs, filling each. SAVING IS THE CALLER'S.

    `save` is called as save(tab, result) after each tab is filled and must
    return True to carry on. It gets that tab's result rather than having to
    wait for the return value, so a caller can report what Apex will refuse
    BEFORE the person presses Save. Passing None fills every tab and presses
    nothing, which is what the supervised rehearsal wants.

    Returns {tab: {"set": [...], "missed": [...], "absent": [...]}} for the
    tabs it reached. A tab that is absent from the result was never filled --
    silence is not a save, here either.
    """
    values = values or who.get("_values") or {}
    out = {}
    for tab, path, prove in TABS:
        if not go_tab(page, apex_id, path, people=[who], log=log):
            log("  could not open the %s tab -- stopping." % tab)
            break
        log("  %s:" % tab)
        if prove is None:
            if not wait_for_field(page, "Position", people=[who], log=log):
                log("  the %s tab never finished loading -- nothing typed." % tab)
                break
        elif not wait_for_field_named(page, prove, people=[who], log=log):
            log("  the %s tab never finished loading -- nothing typed." % tab)
            break
        if tab.startswith("employment"):
            got = fill_employment(page, who, log=log)
        elif tab.startswith("user"):
            got = fill_profile(page, values, log=log)
        else:
            got = fill_tax(page, values, social, log=log)
        log("    set: %s" % (", ".join(got["set"]) or "nothing"))
        if got["missed"]:
            log("    NOT set: %s" % ", ".join(got["missed"]))
        out[tab] = got
        if save is not None and not save(tab, got):
            break
    return out
