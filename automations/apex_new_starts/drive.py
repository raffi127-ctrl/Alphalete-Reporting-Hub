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


def hand_over(page, *, genders=None, socials=None, log=print) -> dict:
    """Put the two things only a PERSON ever supplied into the driven page.

    The engine reads a Gender out of `window.__ansGender` and a Social out of
    `window.__ansSSN`, keyed by its own `norm(name)`. In the extension a person
    types both into the panel. Driven, nobody is sitting there, so they have to
    arrive another way -- Gender off the office's onboarding board, the Social
    out of the signed Blue Ink packet.

    NOTHING IS LOGGED BUT COUNTS. A Social reaches this page and no further: it
    is written straight into the map the engine reads and never returned,
    echoed or put in a message. `Secret.reveal()` is called here and nowhere
    else in this module, which is the point of the wrapper.

    Returns {"genders": n, "socials": n} -- how many landed, never which.
    """
    pairs_g = {str(k): str(v) for k, v in (genders or {}).items() if str(v or "").strip()}
    pairs_s = {}
    for k, v in (socials or {}).items():
        raw = v.reveal() if hasattr(v, "reveal") else str(v or "")
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
