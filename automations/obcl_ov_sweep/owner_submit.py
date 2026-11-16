"""Owner-submit a ready new start in OwnerVille (Megan 2026-09-22).

The click path, as Megan gave it:
    Onboard > View Progress > search name > Edit (Set Status form) >
    OWNER SUBMIT section (only available once every other section is
    completed) > tick "I confirm that this statement is accurate and true.
    Submit for Badging." > Save Changes > re-search the name and CONFIRM the
    step reads "Review in Progress" > only then tick Owner Submit on the OBCL.

THIS IS AN ATTESTATION TO THE CAMPAIGN, and there is no unsubmit: the box
states Alphalete "has reviewed a criminal history background check for this
individual and confirmed that it passes". So:
  * every other Set Status section must read COMPLETED first (Badge and SARA
    Plus come after the submit and are not required) — BACKGROUND CHECK above
    all;
  * a box that is ALREADY ticked is never clicked (clicking the label toggles
    it, which would un-submit);
  * success is only what the page says afterwards — "REVIEW IN PROGRESS" on a
    fresh re-open — never the click itself.
"""
from __future__ import annotations

from automations.digi_docs import ownerville as ov

CONFIRM_TEXT = "I confirm that this statement is accurate and true"
# What OwnerVille shows TODAY in that section: a checkbox labelled "Submit",
# with the old sentence gone (2026-11-16). Matched EXACTLY -- see _confirm_box.
SUBMIT_LABEL = "Submit"
# The one required section a machine may finish by itself -- see
# _complete_service. Everything else that is not COMPLETED needs a person.
SERVICE_SECTION = "SERVICE"
SUBMITTED_STATES = ("REVIEW IN PROGRESS", "APPROVED", "COMPLETED")
# The sections that must read COMPLETED before a submit. An EXPLICIT list, not
# "everything except a few": an unsubmitted person's Owner Submit row carries
# the words "NOT SUBMITTED", which the old "every other line is a section" rule
# read as a section named NOT SUBMITTED and refused on (Marqoun Holland,
# 2026-09-22 — he was fully complete). SUPPLEMENT is left out for the same
# reason it is left out of the readiness check: not everyone gets one.
REQUIRED = ("LOGIN CREATED", "ONBOARDING DOCUMENTS", "BACKGROUND CHECK",
            "DRUG TEST", "FTC DIRECTV COMPLIANCE TRAINING",
            "AT&T PROTECTIVE ADVANTAGE COURSE", "AT&T BROADBAND FACTS",
            "AT&T PROTECTING CPNI", "AT&T COMPLIANCE",
            "2024 CONSENT DECREE MANUAL", "UPLOAD DOCUMENTS",
            "AT&T UID REQUEST", "SERVICE")
OTHER_SECTIONS = ("OWNER SUBMIT", "BADGE", "SARA PLUS", "SUPPLEMENT")
# "NOT SUBMITTED" is Owner Submit's own wording for "nobody has submitted yet".
STATES = ("COMPLETED", "REQUIRED ACTION", "PENDING", "REVIEW IN PROGRESS",
          "OPTIONAL", "APPROVED", "DENIED", "REJECTED", "IN PROGRESS",
          "NOT STARTED", "NOT SUBMITTED")


def _section(line: str):
    """The known section this line names, or None. Prefix match so the dash in
    "AT&T COMPLIANCE – 2023" and the "/SPI" tail can't miss."""
    up = " ".join((line or "").upper().split())
    for known in REQUIRED + OTHER_SECTIONS:
        if up.startswith(known):
            return known
    return None


def section_states(modal, states: tuple = STATES) -> dict:
    """{SECTION: STATE} off the Set Status modal's own text. A section is its
    label line; the next state word belongs to it. Lines that are neither
    (headings, the attestation paragraph, "Review is in progress.") are
    ignored, which is what keeps "NOT SUBMITTED" from becoming a section.

    `states` is the vocabulary of words that count as a state, and it defaults
    to this module's own. A caller reading a DIFFERENT section can widen it --
    uid_request does, because the UID row has wording of its own -- without
    changing what Owner Submit recognises. That matters: this press has been
    live since 22 September, and a word added to the shared vocabulary would
    change which sections `blockers` thinks it has seen.
    """
    out, current = {}, None
    for ln in (modal.inner_text() or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        sec = _section(ln)
        if sec:
            current = sec
            continue
        up = " ".join(ln.upper().split())
        if up in states and current and current not in out:
            out[current] = up
    return out


def blockers(states: dict) -> list:
    """Required sections that don't read COMPLETED — including any the modal
    never showed, which is not the same as done."""
    out = []
    for sec in REQUIRED:
        got = states.get(sec)
        if got != "COMPLETED":
            out.append(f"{sec}={got or 'not shown'}")
    return out


def _confirm_box(modal):
    """The confirm checkbox INPUT in the Owner Submit section, or None.

    TWO WORDINGS, because OwnerVille changed this one under us (2026-11-16).
    It used to be a label carrying a whole sentence -- "I confirm that this
    statement is accurate and true" -- and is now a plain checkbox labelled
    "Submit". Nothing announced the change; what it looked like from here was
    "no confirm box in Owner Submit" on Sergio Bouquett and then Patricia
    Yanez, while the day's post read "0 New Lucy Owner Submitted" both times.
    It was never about those two people: Lucy could not submit ANYBODY.

    The old sentence is still tried FIRST and kept, not replaced. It costs one
    lookup, and if some office or campaign still renders the old attestation
    this keeps working there rather than trading one broken wording for
    another.

    "SUBMIT" IS MATCHED EXACTLY, and that matters more than it looks. The
    modal's own section heading is "OWNER SUBMIT" and its footer button is
    "Save Changes"; a loose contains-match would find the heading, which is
    always present whether the section is open or shut, and the run would
    believe it had found an attestation it had not. `exact=True` matches the
    label's own text and neither of those.
    """
    # COUNTED, NOT WAITED ON. The old sentence is gone from every rep's modal
    # now, so a wait here is four seconds burnt per person before the real
    # lookup -- two minutes across a thirty-rep sweep, spent proving a negative.
    lab = None
    try:
        old_lab = modal.locator("label", has_text=CONFIRM_TEXT).first
        if old_lab.count():
            lab = old_lab
    except Exception:                                       # noqa: BLE001
        lab = None
    if lab is None:
        try:
            lab = modal.get_by_text(SUBMIT_LABEL, exact=True).first
            lab.wait_for(state="attached", timeout=4000)
        except Exception:                                   # noqa: BLE001
            return None, None
    box = lab.locator("input[type='checkbox']").first
    if not box.count():
        fid = lab.get_attribute("for") or ""
        box = modal.locator(f"input[type='checkbox'][id='{fid}']").first \
            if fid else modal.locator("input[type='checkbox']").filter(
                has=lab).first
    if not box.count():
        # The new control puts the input BESIDE its text rather than wrapping
        # it, so walk out one level and look there. Scoped to the label's own
        # parent, never the whole modal: other sections carry checkboxes too,
        # and this one is an attestation that cannot be undone.
        try:
            box = lab.locator("xpath=..").locator(
                "input[type='checkbox']").first
        except Exception:                                   # noqa: BLE001
            box = None
    return lab, (box if (box is not None and box.count()) else None)


def _complete_service(page, modal, name: str, *, campaign: str = ""):
    """Pick the office's service and SAVE, then re-read the modal's states.

    Megan, 2026-11-16: *"res service isn't being checked - we built it where
    Lucy is supposed to check it and save."* It IS built -- `tick_attestations`
    does it -- but only on the digi docs SEND path. A rep whose bundle went out
    before that existed, or whose send died after the bundle was created, keeps
    SERVICE on REQUIRED ACTION forever, and this sweep could only ever refuse
    them. Refusing is right when something needs a person; SERVICE needs
    nobody, so the sweep does it and carries on.

    IT IS NOT AN ATTESTATION. It is which service the rep sells, and the
    office's answer is the same every time -- unlike the drug-screen boxes,
    which assert something about a person and stay on the send path where they
    are logged per rep.

    Returns the states as they read AFTER the save, from a fresh open: the
    click is not the evidence, the page is. On any failure it returns None and
    the caller refuses exactly as it did before.
    """
    try:
        ov._expand(modal, SERVICE_SECTION, page, reveals=ov.config.SERVICE_RADIO,
                   verbose=False)
        # EXACT: the section offers RES-ATT and RES-ATT-OOF, and a fragment
        # matches both.
        if not ov._tick_one(modal, ov.config.SERVICE_RADIO, dry_run=False,
                            exact=True):
            return None
        ov._click_any(modal, "Save Changes", page=page)
        page.wait_for_timeout(3000)
    except Exception:                                       # noqa: BLE001
        return None
    try:
        modal2, _ = ov.open_set_status(page, name, verbose=False,
                                       campaign=campaign)
    except Exception:                                       # noqa: BLE001
        return None
    return section_states(modal2), modal2


def submit_one(page, name: str, *, dry_run: bool = True,
               campaign: str = "") -> tuple:
    """(outcome, detail). outcome: 'submitted' | 'would submit' | 'already' |
    'refused'. Only 'submitted' and 'already' mean OwnerVille shows it done.

    `campaign` is the OwnerVille campaign to look the person up on, and
    defaults to Alphalete's. An ICD's new start is on the office's own
    campaign, so an ICD caller passes its `ov_program` -- and it is passed to
    BOTH opens, the confirming re-open included: confirming on a different
    campaign would be reading a different roster.
    """
    try:
        modal, matched = ov.open_set_status(page, name, verbose=False,
                                           campaign=campaign)
    except Exception as e:                                  # noqa: BLE001
        return "refused", f"could not open {name}: {type(e).__name__}: {e}"
    st = section_states(modal)
    os_state = st.get("OWNER SUBMIT", "")
    if os_state in SUBMITTED_STATES:
        return "already", f"{matched}: Owner Submit already {os_state}"
    bad = blockers(st)
    service_caught_up = False
    # SERVICE IS OURS TO FINISH, and only SERVICE. If it is the one thing in
    # the way, pick it, save, and read the page again -- a sweep that refused
    # on a radio nobody has to think about is a sweep that leaves people
    # unsubmitted for days (Megan, 2026-11-16).
    if bad and all(b.startswith("%s=" % SERVICE_SECTION) for b in bad) \
            and not dry_run:
        fixed = _complete_service(page, modal, name, campaign=campaign)
        if fixed is not None:
            st, modal = fixed
            bad = blockers(st)
            # SAY IT, EVERY TIME. SERVICE belongs to the digi docs SEND
            # (Megan, 2026-11-16: "when we send the digi docs is when the
            # service is supposed to be checked"); this is a catch-up for
            # people whose send missed it, not a second owner of the step.
            # A catch-up that stayed quiet would let the send path rot --
            # the sweep would paper over it person by person and the only
            # sign would be that it never stopped doing so.
            service_caught_up = True
            os_state = st.get("OWNER SUBMIT", "")
            if os_state in SUBMITTED_STATES:
                return "already", f"{matched}: Owner Submit already {os_state}"
    if bad:
        return "refused", f"{matched}: not every section is done — " \
                          f"{', '.join(bad)}"
    note = (" (SERVICE was still open — the digi docs send should have "
            "ticked it)" if service_caught_up else "")
    if st.get("BACKGROUND CHECK") != "COMPLETED":
        return "refused", f"{matched}: background check is not COMPLETED"
    # OPEN THE SECTION, THEN LOOK FOR THE BOX -- not the other way round.
    # `_expand` waits for a TEXT marker to prove it opened, and that marker was
    # the old attestation sentence, which OwnerVille deleted (2026-11-16). It
    # does not raise when the marker never shows; it prints and returns. So the
    # run sailed past a section it had not confirmed open and then reported the
    # thing it could not find, which read like a missing control rather than a
    # changed one.
    #
    # The box itself is the only honest proof, so it is what we check. And if
    # it is not there, the section is TOGGLED ONCE and checked again: a row
    # that was already open is closed by the first click, and one click more is
    # the difference between "no confirm box" and a submit.
    try:
        ov._expand(modal, "OWNER SUBMIT", page, reveals=CONFIRM_TEXT[:24],
                   verbose=False)
    except Exception:                                       # noqa: BLE001
        pass
    lab, box = _confirm_box(modal)
    if lab is None:
        try:
            for row in ov._status_rows(modal, "OWNER SUBMIT"):
                if row.is_visible():
                    row.click(timeout=6000)
                    break
            page.wait_for_timeout(1200)
        except Exception:                                   # noqa: BLE001
            pass
        lab, box = _confirm_box(modal)
    if lab is None:
        return "refused", f"{matched}: no confirm box in Owner Submit " \
                          f"(looked for {CONFIRM_TEXT[:28]!r} and an exact " \
                          f"{SUBMIT_LABEL!r})"
    try:
        already_ticked = bool(box and box.is_checked())
    except Exception:                                       # noqa: BLE001
        already_ticked = False
    if dry_run:
        return "would submit", f"{matched}: all sections COMPLETED, confirm " \
                               f"box {'already ticked' if already_ticked else 'found'}"
    if not already_ticked:
        for attempt in ("normal", "scrolled", "forced"):
            try:
                if attempt == "scrolled":
                    lab.scroll_into_view_if_needed(timeout=5000)
                (box or lab).click(timeout=10000, force=(attempt == "forced"))
                break
            except Exception:                               # noqa: BLE001
                continue
        try:
            if box is not None and not box.is_checked():
                return "refused", f"{matched}: confirm box would not tick"
        except Exception:                                   # noqa: BLE001
            pass
    try:
        ov._click_any(modal, "Save Changes", page=page)
        page.wait_for_timeout(3000)
    except Exception as e:                                  # noqa: BLE001
        return "refused", f"{matched}: Save Changes failed ({type(e).__name__})"
    # CONFIRM on a fresh open — the click is not the evidence, the page is.
    try:
        modal2, _ = ov.open_set_status(page, name, verbose=False,
                                       campaign=campaign)
        after = section_states(modal2).get("OWNER SUBMIT", "")
    except Exception as e:                                  # noqa: BLE001
        return "refused", f"{matched}: saved, but could not re-open to " \
                          f"confirm ({type(e).__name__}) — CHECK BY HAND"
    if after in SUBMITTED_STATES:
        return "submitted", f"{matched}: Owner Submit now {after}{note}"
    return "refused", f"{matched}: saved, but Owner Submit reads " \
                      f"{after or 'nothing'} — CHECK BY HAND"
