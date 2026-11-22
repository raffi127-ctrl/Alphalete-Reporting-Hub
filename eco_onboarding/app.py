"""LucyECO Onboarding enrolment — an office answers once, for everything.

A per-office link, same shape as `pay_structure/` and `document_builder/`: the
owner opens it, answers, and the answers land on the `Office Settings` tab that
Sterling, the onboarding board and the Apex fill all read.

SEPARATE FROM THE LUCYECO INSTALL SIGN-UP (`icd_signup/`), on purpose
(Megan, 2026-11-19). That form is about getting their computer running; this
one is about the facts their onboarding needs -- where the job is, what they
pay, and what goes on a payroll record.

    streamlit run eco_onboarding/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations.eco_onboarding import settings as S     # noqa: E402
from automations.eco_onboarding import store             # noqa: E402

st.set_page_config(page_title="LucyECO Onboarding", page_icon="📋")


# BOTH READS ARE CACHED. Opening the sheet takes a couple of MINUTES on a cold
# client, and Streamlit re-runs this whole file on every keystroke that
# commits -- so without this the owner picks their office and waits two
# minutes, then answers a question and waits again. They would close the tab,
# and rightly.
#
# Short TTLs rather than none: the office list changes when somebody is
# enrolled, and a row changes when somebody saves. Five minutes is longer than
# anybody takes to fill this in and shorter than they would wait to see a new
# office appear.
@st.cache_data(ttl=300, show_spinner="Loading your offices…")
def _offices():
    return store.offices()


@st.cache_data(ttl=300, show_spinner="Loading your office's answers…")
def _current(office_key: str):
    return store.read(office_key)


def _ask_channel(q: S.Question, current: str) -> str:
    """The Channel ID box, plus the one check worth doing while they are here.

    A channel NAME typed where an id belongs is accepted by every plain text
    box and then fails hours later when Lucy tries to post (Joseph Logan,
    2026-09-11). This box refuses one as it is typed, and then asks Slack
    whether Lucy is actually in the room -- because "right id, Lucy not
    invited" looks exactly the same until the first post does not appear.
    """
    from automations.shared import onboarding_ui as UI
    if current:
        st.caption("Currently: `%s`" % current)
    got = UI.channel_id_input(q.label, key="eco_" + q.field, help=q.help)
    if not got:
        # Keep what they already answered rather than blanking it by leaving
        # the box alone: row_for drops empty fields, so this is only about
        # what the page shows back.
        return current
    try:
        res = UI.check_channel(channel_id=got)
        st.caption(UI.lucy_line(res))
    except Exception as exc:                                # noqa: BLE001
        # Never block the save on it. The answer is still the answer, and an
        # unreachable Slack is our problem, not the owner's.
        st.caption("Could not check whether Lucy is in that channel (%s). "
                   "The ID is saved either way." % type(exc).__name__)
    return got


def _ask(q: S.Question, current: str):
    """One question, one input. No syntax, no multi-answer boxes."""
    key = "eco_" + q.field
    if q.kind == "channel":
        return _ask_channel(q, current)
    if q.choices:
        options = list(q.choices)
        start = current or q.default
        index = options.index(start) if start in options else 0
        # A REQUIRED QUESTION WITH NO ANSWER YET STARTS BLANK, so a default
        # cannot be submitted as though somebody chose it. That is the whole
        # point of asking: Texas was the default before, on every office.
        if q.required and not current:
            options = [""] + options
            index = 0
        return st.selectbox(q.label, options, index=index, key=key,
                            help=q.help or None)
    return st.text_input(q.label, value=current or q.default, key=key,
                         help=q.help or None)


st.title("LucyECO Onboarding")
st.caption("Your office's answers, asked once. Everything below goes to your "
           "onboarding board, your background checks and your payroll records.")

# PICK, DO NOT TYPE. A typed key that does not match makes a SECOND row for
# an office that already has one, and nothing downstream would ever read it.
# It also means the form works without pressing Enter -- a text box does not
# rerun Streamlit until it commits, so the first version looked like it did
# nothing when somebody typed and waited.
NEW = "+ My office isn't listed"
known = _offices()
if known:
    picked = st.selectbox("Your office", [""] + known + [NEW], key="eco_pick")
else:
    st.warning("Could not read the office list — type your key instead.")
    picked = NEW

if picked == NEW:
    office = st.text_input(
        "Your office key", key="eco_office",
        help="The short name for your office, like 'raf' or 'vincent'. "
             "Press Enter when you have typed it.").strip()
else:
    office = picked.strip()

if not office:
    st.info("Choose your office to begin.")
    st.stop()

try:
    current = _current(office)
except Exception as exc:                                   # noqa: BLE001
    st.error("Could not read Office Settings: %s" % exc)
    st.stop()

if current:
    st.success("Found your office. Anything already answered is filled in "
               "below — change what has changed.")
else:
    st.warning("No row for %r yet. Submitting will create one." % office)

answers = {}

st.subheader("Where the job is")
st.caption("Sterling puts this on every background check invite.")
for q in S.STERLING:
    answers[q.field] = _ask(q, current.get(q.column, ""))

st.subheader("One setting on your screen")
st.caption("We cannot set this one for you.")
for q in S.CALENDAR:
    answers[q.field] = _ask(q, current.get(q.column, ""))

st.subheader("Your onboarding")
for q in S.BOARD:
    answers[q.field] = _ask(q, current.get(q.column, ""))

st.subheader("Your documents")
for q in S.BLUE_INK_BUNDLE:
    answers[q.field] = _ask(q, current.get(q.column, ""))

st.subheader("Payroll")
st.caption("These go on a real payroll record, so we ask rather than assume.")
for q in S.PAY_STATES:
    answers[q.field] = _ask(q, current.get(q.column, ""))

st.subheader("Your OBCL update")
st.caption("The picture of where every new start has got to, posted again "
           "each time it changes.")
_obcl_to = _ask(S.OBCL_UPDATE[0], current.get(S.COL_OBCL_TO, ""))
answers["obcl_to"] = _obcl_to
# ONLY THE ONE THAT GOES WITH THE ANSWER. Showing both leaves an unused box
# filled in, and a stale channel somebody once typed is indistinguishable
# from a chosen one the next time anybody reads the row.
if _obcl_to == S.OBCL_SLACK:
    answers["obcl_channel"] = _ask(S.OBCL_UPDATE[1],
                                   current.get(S.COL_OBCL_CHANNEL, ""))
elif _obcl_to == S.OBCL_TEXT:
    answers["obcl_group"] = _ask(S.OBCL_UPDATE[2],
                                 current.get(S.COL_OBCL_GROUP, ""))

st.subheader("Your Daily Update")
st.caption("Where Lucy posts the write-up of each day's second rounds. "
           "Until you give us a channel it goes to a holding room, and it "
           "stays there until Megan switches your office on.")
for q in S.DAILY_UPDATE:
    answers[q.field] = _ask(q, current.get(q.column, ""))

# THE SIX THAT USUALLY MATCH, behind one tick. Asking every office to retype
# answers that are the same for almost all of them is how a form stops being
# filled in honestly.
already = any(current.get(q.column, "").strip() and
              current.get(q.column, "").strip() != q.default for q in S.JOB)
standard = st.checkbox(
    "The rest of our pay setup is the standard one",
    value=not already, key="eco_standard",
    help="Sales Rep · Commissions · Weekly · 400 Sales · United States · "
         "Sales Rep role. Untick if any of those are different for you.")
if standard:
    answers.update(S.STANDARD)
    st.caption(" · ".join("%s: %s" % (q.label, S.STANDARD[q.field])
                          for q in S.JOB))
else:
    for q in S.JOB:
        answers[q.field] = _ask(q, current.get(q.column, ""))

who = st.text_input("Your name", key="eco_who",
                    help="So we know who to ask if something looks off.").strip()

if st.button("Save my answers", type="primary"):
    trouble = S.problems(answers)
    if not who:
        trouble.append("Your name")
    if trouble:
        st.error("Still needed:\n\n" + "\n".join("- " + t for t in trouble))
    else:
        row = S.row_for(answers, who, store.stamp())
        try:
            ok, said = store.save(office, row, dry_run=False)
        except Exception as exc:                            # noqa: BLE001
            st.error("Could not save: %s" % exc)
        else:
            if ok:
                # The row just changed, so the cached copy is now a lie.
                _current.clear()
                _offices.clear()
                st.success("Saved. Your onboarding board will use these from "
                           "its next run.")
                st.caption(said)
            else:
                st.error(said)
