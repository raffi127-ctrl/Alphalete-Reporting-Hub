"""Request the AT&T UID in OwnerVille (Megan, 2026-11-15: "do 1 and 2").

    Onboard > View Progress > search name > Edit (Set Status form) >
    AT&T UID REQUEST section > press its request control > Save Changes >
    re-open and CONFIRM the section no longer reads REQUIRED ACTION.

WHY THIS IS A SEPARATE PRESS AND NOT PART OF THE SWEEP. The sweep READS
whether a UID has been requested and ticks the board off it. Nothing has ever
pressed it, so it is the last step before Owner Submit that a person still has
to remember -- and a forgotten UID is what holds a finished new start out of
Owner Submit, which is the thing the whole board exists to stop happening.

IT SHIPS GATED, AND HERE IS THE HONEST REASON. Owner Submit was built from
Megan's own click path and a screenshot of the modal. This one was not: NOBODY
HAS SHOWN ME THIS SECTION EXPANDED. So the control is not hardcoded from a
guess at the markup -- it is SEARCHED FOR, it must be the only candidate in
the section, and anything else is a refusal that prints what the section does
contain (the `_dump_controls` lesson of 2026-08-25: a log that can only say a
selector missed costs another round). `describe_one` is the read-only half:
one supervised run says what is actually there, and only then does
config.UID_REQUEST_LIVE go True.

WHAT MUST NEVER HAPPEN HERE
  * pressing twice. A UID request goes to AT&T; a second one is a second
    request against the same person. So a section that reads ANYTHING other
    than "not started yet" is left alone, and an unrecognised word counts as
    "leave it alone", never as "go ahead".
  * pressing before the person is real. OwnerVille's own prerequisites gate
    it (LOGIN CREATED and ONBOARDING DOCUMENTS), because a UID minted against
    a half-made record is not something we can take back.
  * believing the click. Success is what the page says on a FRESH re-open,
    exactly as Owner Submit does it.
"""
from __future__ import annotations

from automations.digi_docs import ownerville as ov
from automations.obcl_ov_sweep import owner_submit as OS

SECTION = "AT&T UID REQUEST"

# This section's own vocabulary, on top of Owner Submit's. The View Progress
# TABLE renders a requested UID as a green "Requested" pill (ov_table's
# docstring), so the modal may well word it that way too -- and a word this
# module does not know must never read as "not done".
STATES = tuple(OS.STATES) + ("REQUESTED", "SUBMITTED", "ORDERED", "RECEIVED",
                             "ACTIVE", "ISSUED")

# The only state that means "nobody has requested one yet". Deliberately a
# single word rather than "anything except done": every other word, known or
# unknown, leaves the section alone.
TODO_STATE = "REQUIRED ACTION"

# What OwnerVille needs before a UID can be requested. SHORT on purpose: this
# is not the Owner Submit gate, which needs everything. A UID is requested
# early -- it is itself one of Owner Submit's prerequisites -- so demanding the
# quizzes here would mean no UID ever got requested until after it was needed.
REQUIRED = ("LOGIN CREATED", "ONBOARDING DOCUMENTS")

# Words a request control might be labelled with, longest first so "Request
# UID" wins over a bare "Request" that is part of it.
WORDS = ("Request AT&T UID", "Request UID", "Submit UID Request",
         "Request Now", "Send Request", "Request")


def _open_section(modal, page) -> None:
    """Click this section open ONCE, with no marker chase.

    `ov._expand` takes the text it should wait for and, when that text never
    appears, works through the chevron and then every plausible toggle on the
    row. That is right for a section whose contents are known -- and WRONG
    here, because a second toggle on an open section CLOSES it, and this is a
    section nobody has shown me. So the marker is the section's own label,
    which is on the modal whether it is open or shut: the label is clicked,
    the wait returns at once, and nothing else is touched.

    Whether it actually opened is then answered by `controls` rather than
    assumed -- an empty list is a refusal that prints what it saw.
    """
    ov._expand(modal, SECTION, page, reveals=SECTION, verbose=False)


def _states(modal) -> dict:
    return OS.section_states(modal, states=STATES)


def blockers(states: dict) -> list:
    """Required sections that don't read COMPLETED — including any the modal
    never showed, which is not the same as done."""
    return ["%s=%s" % (sec, states.get(sec) or "not shown")
            for sec in REQUIRED if states.get(sec) != "COMPLETED"]


def _section_node(modal):
    """The innermost VISIBLE element that is this section, or None.

    Same ordering trap as everywhere else on this modal: `.first` is the
    outermost match, which is the modal itself, so walk innermost outwards.
    """
    for row in ov._status_rows(modal, SECTION):
        try:
            if row.is_visible():
                return row
        except Exception:                                   # noqa: BLE001
            continue
    return None


def controls(node) -> list:
    """Every clickable thing inside the section, as short label strings.

    This is the read a refusal prints. It is also what `describe_one` returns,
    so one supervised run answers what the control is actually called instead
    of another round of guessing at the markup.
    """
    out = []
    if node is None:
        return out
    try:
        bits = node.locator("button, a, input[type='button'], "
                            "input[type='submit']")
        for i in range(min(bits.count(), 20)):
            one = bits.nth(i)
            try:
                txt = (one.inner_text(timeout=1500) or "").strip()
            except Exception:                               # noqa: BLE001
                txt = ""
            if not txt:
                txt = (one.get_attribute("value") or "").strip()
            if txt:
                out.append(" ".join(txt.split())[:48])
    except Exception:                                       # noqa: BLE001
        pass
    return out


def _request_control(node):
    """(label, locator) for the ONE control that requests a UID, or (None, []).

    Exactly one candidate or nothing. Two controls that both look like a
    request is the case where a guess presses the wrong one, and on this
    section the wrong press reaches AT&T.
    """
    seen = controls(node)
    hits = [lab for word in WORDS for lab in seen
            if word.lower() in lab.lower()]
    uniq = list(dict.fromkeys(hits))
    if len(uniq) != 1:
        return None, seen
    return uniq[0], seen


def describe_one(page, name: str, *, campaign: str = "") -> tuple:
    """(detail, controls) — READ ONLY. What this person's UID section says and
    what it offers. Presses nothing, saves nothing, and is how the control
    gets confirmed before config.UID_REQUEST_LIVE is flipped."""
    try:
        modal, matched = ov.open_set_status(page, name, verbose=False,
                                            campaign=campaign)
    except Exception as e:                                  # noqa: BLE001
        return "could not open %s: %s" % (name, type(e).__name__), []
    st = _states(modal)
    try:
        _open_section(modal, page)
    except Exception as e:                                  # noqa: BLE001
        return "%s: %s would not open (%s)" % (matched, SECTION,
                                               type(e).__name__), []
    seen = controls(_section_node(modal))
    return ("%s: %s reads %s; required %s" %
            (matched, SECTION, st.get(SECTION) or "nothing",
             ", ".join("%s=%s" % (s, st.get(s) or "not shown")
                       for s in REQUIRED)), seen)


def request_one(page, name: str, *, dry_run: bool = True,
                campaign: str = "") -> tuple:
    """(outcome, detail). outcome: 'requested' | 'would request' | 'already' |
    'refused'. Only 'requested' and 'already' mean OwnerVille shows it done."""
    try:
        modal, matched = ov.open_set_status(page, name, verbose=False,
                                            campaign=campaign)
    except Exception as e:                                  # noqa: BLE001
        return "refused", "could not open %s: %s: %s" % (name,
                                                         type(e).__name__, e)
    st = _states(modal)
    state = st.get(SECTION, "")
    if not state:
        # Unread is never "not done" -- the board's own rule. A section we
        # could not read is the one case where pressing would be a guess.
        return "refused", "%s: %s could not be read — left alone" % (matched,
                                                                     SECTION)
    if state != TODO_STATE:
        return "already", "%s: %s already %s" % (matched, SECTION, state)
    bad = blockers(st)
    if bad:
        return "refused", "%s: not ready for a UID yet — %s" % (
            matched, ", ".join(bad))
    try:
        _open_section(modal, page)
    except Exception as e:                                  # noqa: BLE001
        return "refused", "%s: %s would not open (%s)" % (matched, SECTION,
                                                          type(e).__name__)
    node = _section_node(modal)
    label, seen = _request_control(node)
    if label is None:
        return "refused", ("%s: no single request control in %s — it offers "
                           "%s. Nothing pressed." %
                           (matched, SECTION, seen or "nothing clickable"))
    if dry_run:
        return "would request", "%s: %s is %s and offers %r" % (
            matched, SECTION, state, label)
    try:
        ov._click_any(node, label, page=page)
    except Exception as e:                                  # noqa: BLE001
        return "refused", "%s: %r would not click (%s)" % (matched, label,
                                                           type(e).__name__)
    try:
        ov._click_any(modal, "Save Changes", page=page)
        page.wait_for_timeout(3000)
    except Exception as e:                                  # noqa: BLE001
        return "refused", "%s: Save Changes failed (%s)" % (matched,
                                                            type(e).__name__)
    # CONFIRM on a fresh open. OwnerVille's Save is a plain submit, so an
    # invalid form produces no request, no error and nothing on screen.
    try:
        modal2, _ = ov.open_set_status(page, name, verbose=False,
                                       campaign=campaign)
        after = _states(modal2).get(SECTION, "")
    except Exception as e:                                  # noqa: BLE001
        return "refused", ("%s: saved, but could not re-open to confirm (%s) "
                           "— CHECK BY HAND" % (matched, type(e).__name__))
    if after and after != TODO_STATE:
        return "requested", "%s: %s now %s" % (matched, SECTION, after)
    return "refused", ("%s: saved, but %s still reads %s — CHECK BY HAND" %
                       (matched, SECTION, after or "nothing"))
