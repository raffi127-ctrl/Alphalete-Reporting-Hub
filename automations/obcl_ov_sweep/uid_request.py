"""Why a rep's AT&T UID is outstanding — READ ONLY. Nothing here presses.

THIS STARTED AS A PRESS AND IS NOT ONE. On 2026-11-15 the plan was "request
the UID the way we owner-submit", and the press was written gated, because
nobody had seen that section expanded. Megan then sent two screenshots of it,
and they settle it: THERE IS NO BUTTON. The section expands to prose in both
states, in OwnerVille's own words --

  REQUIRED ACTION
      "Sales Rep has not submitted ATTUID information. Form is available by
       logging into Candidate Roadmap Portal"

  COMPLETED
      "Candidate has submitted their information for an ATTUID. The request
       for the ATTUID will be sent to AT&T once the rep has been activated
       for SaraPlus. ATTUID may take up to 30 days to return from AT&T."

So the UID is not something an owner presses at all. THE REP SUBMITS IT
THEMSELVES, on a form in the Candidate Roadmap Portal that only they can log
into, and the send to AT&T then fires off SaraPlus activation rather than off
anybody's click. That puts it with the quizzes and the headshot: a step only
the new start can do, which belongs to the nudge, not to a press.

WHAT IS STILL WORTH READING, and why this module survived. A blank UID cell
today means one of three completely different things, and the board cannot
tell them apart:

    the rep has not filled the portal form        -> chase the REP
    they have, and SaraPlus activation is pending -> chase the ACTIVATION
    both done, AT&T has not answered yet          -> wait, up to 30 days

Only the first is anybody's to act on. `reason_one` returns OwnerVille's own
sentence so the difference is visible, which is the whole input a UID nudge
needs. It opens the section and reads it. It clicks nothing else and saves
nothing, ever.
"""
from __future__ import annotations

from automations.digi_docs import ownerville as ov
from automations.obcl_ov_sweep import owner_submit as OS

SECTION = "AT&T UID REQUEST"

# This section's own vocabulary, on top of Owner Submit's. Passed IN rather
# than appended to the shared tuple: Owner Submit has been live since 22
# September, and a word added there changes which sections `blockers` believes
# it has seen.
STATES = tuple(OS.STATES) + ("REQUESTED", "SUBMITTED", "ORDERED", "RECEIVED",
                             "ACTIVE", "ISSUED")

# Whose move it is, matched against OwnerVille's own sentence. Order matters:
# the first hit wins, and "has not submitted" must be tested before the
# "has submitted" that is a substring of nothing but reads similarly.
WHOSE_MOVE = (
    ("has not submitted", "the rep — the ATTUID form is theirs, in the "
                          "Candidate Roadmap Portal"),
    ("Candidate Roadmap Portal", "the rep — the ATTUID form is theirs, in the "
                                 "Candidate Roadmap Portal"),
    ("once the rep has been activated for SaraPlus",
     "SaraPlus activation — the rep has submitted; the request goes to AT&T "
     "when they are activated"),
    ("may take up to 30 days", "AT&T — submitted and sent, up to 30 days to "
                               "come back"),
)
NOBODY_SAID = "unknown — OwnerVille said nothing this run"


def _states(modal) -> dict:
    return OS.section_states(modal, states=STATES)


def _open_section(modal, page) -> None:
    """Click this section open ONCE, with no marker chase.

    `ov._expand` takes the text it should wait for and, when that text never
    appears, works through the chevron and then every plausible toggle on the
    row -- and a second toggle on an OPEN section CLOSES it. The marker here is
    the section's own label, which is on the modal whether it is open or shut,
    so the label is clicked, the wait returns at once, and nothing else is
    touched.
    """
    ov._expand(modal, SECTION, page, reveals=SECTION, verbose=False)


def _body(modal) -> str:
    """The section's own paragraph, as one line, or ''."""
    for row in ov._status_rows(modal, SECTION):
        try:
            if not row.is_visible():
                continue
            txt = " ".join((row.inner_text(timeout=3000) or "").split())
        except Exception:                                   # noqa: BLE001
            continue
        if txt:
            return txt
    return ""


def whose_move(said: str) -> str:
    """Who has to do something next, off OwnerVille's own sentence.

    Never guesses. A sentence this does not recognise answers NOBODY_SAID,
    because an invented owner for a step is how somebody gets chased for a
    thing that was never theirs.
    """
    low = (said or "").lower()
    for needle, answer in WHOSE_MOVE:
        if needle.lower() in low:
            return answer
    return NOBODY_SAID


def reason_one(page, name: str, *, campaign: str = "") -> tuple:
    """(state, said, whose) for one person's AT&T UID section. READ ONLY.

    `state` is the chip (COMPLETED / REQUIRED ACTION / ...), `said` is the
    paragraph OwnerVille prints under it, `whose` is who has to move next.
    """
    try:
        modal, matched = ov.open_set_status(page, name, verbose=False,
                                            campaign=campaign)
    except Exception as e:                                  # noqa: BLE001
        return "", "could not open %s: %s" % (name, type(e).__name__), ""
    state = _states(modal).get(SECTION, "")
    try:
        _open_section(modal, page)
    except Exception as e:                                  # noqa: BLE001
        return state, "%s: section would not open (%s)" % (matched,
                                                           type(e).__name__), ""
    said = _body(modal)
    return state, "%s: %s" % (matched, said or "(nothing printed)"), \
        whose_move(said)
