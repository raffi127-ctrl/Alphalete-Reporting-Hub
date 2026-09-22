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
SUBMITTED_STATES = ("REVIEW IN PROGRESS", "APPROVED", "COMPLETED")
# Sections that come AFTER the submit, or are optional — not required.
NOT_REQUIRED = ("OWNER SUBMIT", "BADGE", "SARA PLUS")
STATES = ("COMPLETED", "REQUIRED ACTION", "PENDING", "REVIEW IN PROGRESS",
          "OPTIONAL", "APPROVED", "DENIED", "REJECTED", "IN PROGRESS",
          "NOT STARTED")


def section_states(modal) -> dict:
    """{SECTION LABEL: STATE} read off the Set Status modal's own text, where
    each section is its label line followed by its chip line."""
    lines = [x.strip() for x in (modal.inner_text() or "").splitlines()
             if x.strip()]
    out, last = {}, None
    for ln in lines:
        up = ln.upper()
        if up in STATES:
            if last and last not in out:
                out[last] = up
        else:
            last = up
    return out


def blockers(states: dict) -> list:
    """Sections that must be COMPLETED before a submit and aren't."""
    return [f"{k}={v}" for k, v in states.items()
            if k not in NOT_REQUIRED and v != "COMPLETED"]


def _confirm_box(modal):
    """The confirm checkbox INPUT in the Owner Submit section, or None."""
    lab = modal.locator("label", has_text=CONFIRM_TEXT).first
    try:
        lab.wait_for(state="attached", timeout=8000)
    except Exception:                                       # noqa: BLE001
        return None, None
    box = lab.locator("input[type='checkbox']").first
    if not box.count():
        fid = lab.get_attribute("for") or ""
        box = modal.locator(f"input[type='checkbox'][id='{fid}']").first \
            if fid else modal.locator("input[type='checkbox']").filter(
                has=lab).first
    return lab, (box if box.count() else None)


def submit_one(page, name: str, *, dry_run: bool = True) -> tuple:
    """(outcome, detail). outcome: 'submitted' | 'would submit' | 'already' |
    'refused'. Only 'submitted' and 'already' mean OwnerVille shows it done."""
    try:
        modal, matched = ov.open_set_status(page, name, verbose=False)
    except Exception as e:                                  # noqa: BLE001
        return "refused", f"could not open {name}: {type(e).__name__}: {e}"
    st = section_states(modal)
    os_state = st.get("OWNER SUBMIT", "")
    if os_state in SUBMITTED_STATES:
        return "already", f"{matched}: Owner Submit already {os_state}"
    bad = blockers(st)
    if bad:
        return "refused", f"{matched}: not every section is done — " \
                          f"{', '.join(bad)}"
    if st.get("BACKGROUND CHECK") != "COMPLETED":
        return "refused", f"{matched}: background check is not COMPLETED"
    try:
        ov._expand(modal, "OWNER SUBMIT", page, reveals=CONFIRM_TEXT[:24])
    except Exception as e:                                  # noqa: BLE001
        return "refused", f"{matched}: Owner Submit section would not open " \
                          f"({type(e).__name__})"
    lab, box = _confirm_box(modal)
    if lab is None:
        return "refused", f"{matched}: no confirm box in Owner Submit"
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
        modal2, _ = ov.open_set_status(page, name, verbose=False)
        after = section_states(modal2).get("OWNER SUBMIT", "")
    except Exception as e:                                  # noqa: BLE001
        return "refused", f"{matched}: saved, but could not re-open to " \
                          f"confirm ({type(e).__name__}) — CHECK BY HAND"
    if after in SUBMITTED_STATES:
        return "submitted", f"{matched}: Owner Submit now {after}"
    return "refused", f"{matched}: saved, but Owner Submit reads " \
                      f"{after or 'nothing'} — CHECK BY HAND"
