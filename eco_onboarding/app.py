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


def _ask(q: S.Question, current: str):
    """One question, one input. No syntax, no multi-answer boxes."""
    key = "eco_" + q.field
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
known = store.offices()
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
    current = store.read(office)
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

st.subheader("Your onboarding")
for q in S.BOARD:
    answers[q.field] = _ask(q, current.get(q.column, ""))

st.subheader("Payroll")
st.caption("These go on a real payroll record, so we ask rather than assume.")
for q in S.PAY_STATES:
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
                st.success("Saved. Your onboarding board will use these from "
                           "its next run.")
                st.caption(said)
            else:
                st.error(said)
