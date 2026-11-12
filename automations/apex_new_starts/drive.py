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
ENTRY_POINTS = ("__ansAddMissing", "__ansOpen", "__ansDoPage", "__ansRoster")


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
            out[name] = {"need": COMPLETE, "why": "on Pending"}
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
