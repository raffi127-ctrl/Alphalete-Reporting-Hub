"""The OwnerVille half: add a rep, then generate their document bundle.

Built on the paths headshots/ov_upload.py already proved on this exact page —
the campaign walk, the short-probe DataTables search, the Show All widen, the
Edit -> "<Name> - Set Status" modal, and _click_any's every-shape clicking. Those
are imported rather than re-written: they carry a year of live-run scar tissue
(the whole-name search that filters to zero, the radio whose label isn't its own
node, the DataTable that re-renders under the first read) and a second copy
would have to learn all of it again.

THE RULE THIS FILE ENCODES: nothing submits until a control literally says
"Generate Document". Three buttons on the way look like the submit and are not.
`Generate Bundle` reveals the bundle dropdown; choosing the bundle reveals the
commission checkboxes; `Get Documents for Selected Bundle` opens the
per-document form. So every step WAITS for its own control to appear rather
than assuming a static form — that shape is exactly what produces an automation
clicking a control that is not there yet and reporting success.

Verified: nothing here has met a live page. The structure and the guards are
settled; the selectors want a Lucy 3 dry run. Each step logs what it saw, so
the first run says which selector missed rather than only that something timed
out.
"""
from __future__ import annotations

from pathlib import Path

from automations.digi_docs import config
from automations.headshots.ov_upload import (   # proven on this same page
    _campaign_select, _click_any, _rep_row, _search_box, _search_probes,
    _show_all, find_rep,
)

PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / config.BROWSER_PROFILE_DIRNAME)


class Refused(RuntimeError):
    """We stopped on purpose. Never a crash — a refusal names its reason so the
    run's summary can say who was skipped and why."""


def session(*, headless: bool = True, verbose: bool = True):
    """Our OWN browser profile, never a shared one. The headshots tick drives
    OwnerVille on this same box whenever photos are in the thread, and the
    2026-08-19 profile-lock wedge is what separate profiles prevent."""
    from automations.shared.tableau_patchright import ownerville_session
    return ownerville_session(headless=headless, verbose=verbose,
                              profile_dir=PROFILE_DIR)


# --- phase 2: add the reps ------------------------------------------------

def add_sales_rep(page, name: str, *, dry_run: bool = True,
                  verbose: bool = True) -> str:
    """`+ Add Sales Rep` on View Progress. Returns 'added' | 'exists' | 'dry'.

    NO TEAM IS SELECTED (Megan 2026-08-25). That dropdown sits between the
    employee picker and the Activate Now box — both of which we DO touch — so it
    reads like a required field and is precisely the one an automation would
    helpfully fill in. Activate Now is checked by default; leave it alone too.
    """
    row, _campaign, _matched = find_rep(page, name, verbose=False)
    if row is not None:
        if verbose:
            print(f"  {name}: already in OwnerVille")
        return "exists"
    if dry_run:
        if verbose:
            print(f"  {name}: WOULD add")
        return "dry"

    _click_any(page, "Add Sales Rep", page=page)
    modal = page.locator("div[role='dialog'], .modal:visible").filter(
        has_text="Add Sales Rep").first
    modal.wait_for(state="visible", timeout=20000)

    # The employee picker is the FIRST visible select in the modal; the team
    # picker is the second and stays on '-Select a Team-'.
    picker = modal.locator("select:visible").first
    picker.wait_for(state="visible", timeout=15000)
    _select_person(picker, name)

    _click_any(modal, "Add", page=page)
    page.wait_for_load_state("networkidle")
    if verbose:
        print(f"  {name}: added")
    return "added"


def _select_person(picker, name: str) -> None:
    """Pick the employee by the closest option label.

    OV spells names its own way, so match on the last name plus a first-name
    prefix rather than the exact string — the same reason find_rep probes short.
    Two options that both match is a REFUSAL, never a guess: adding the wrong
    person is the start of mailing them somebody else's contract.
    """
    options = [o.strip() for o in picker.locator("option").all_inner_texts()]
    parts = [p for p in name.split() if p]
    last = parts[-1].lower() if parts else ""
    first4 = parts[0][:4].lower() if len(parts) > 1 else ""
    hits = [o for o in options
            if last and last in o.lower() and (not first4 or first4 in o.lower())]
    if not hits:
        raise Refused(f"{name}: not in the Add Sales Rep employee list")
    if len(hits) > 1:
        raise Refused(f"{name}: {len(hits)} employees match ({hits[:3]}) — "
                      "refusing to guess")
    picker.select_option(label=hits[0])


# --- phase 3: generate the bundle ----------------------------------------

def open_set_status(page, name: str, *, verbose: bool = True):
    """Search the rep, click Edit, return (modal, matched_name).

    find_rep does the campaign walk, the short probes and the Show All widen —
    a just-added rep is often outside the default 3-week activation window,
    which is exactly the case that widen exists for.
    """
    row, campaign, matched = find_rep(page, name, verbose=verbose)
    if row is None:
        raise Refused(f"{name}: not found in OwnerVille (tried {campaign})")
    _click_any(row, "Edit", page=page)
    modal = page.locator("div[role='dialog'], .modal:visible").filter(
        has_text="Set Status").first
    modal.wait_for(state="visible", timeout=20000)
    return modal, matched


def _row_state(modal, label: str) -> str:
    """The state chip on one Set Status row: 'COMPLETED' / 'REQUIRED ACTION' /
    'PENDING', or '' when the row or its chip isn't found."""
    row = modal.locator("div,li,tr").filter(has_text=label).first
    try:
        row.wait_for(state="visible", timeout=8000)
    except Exception:
        return ""
    txt = (row.inner_text(timeout=4000) or "").upper()
    for state in ("REQUIRED ACTION", "COMPLETED", "PENDING"):
        if state in txt:
            return state
    return ""


def docs_still_owed(modal) -> bool:
    """Is ONBOARDING DOCUMENTS still REQUIRED ACTION?

    OwnerVille refuses a second generate for the same rep, so this is NOT what
    prevents a double-send — the platform is. It keeps a re-run QUIET (a batch
    re-run would otherwise walk every already-done rep through the whole
    click-path to collect a refusal) and keeps that refusal MEANINGFUL: if we
    only generate for reps we believe still need it, a "won't allow" means our
    picture is wrong and is worth saying out loud.
    """
    return _row_state(modal, config.DOCS_ROW) == config.DOCS_NEEDED_STATE


def open_docs_portal(page, modal):
    """Expand ONBOARDING DOCUMENTS → gray `Access Digital Doc Portal`.

    It opens a NEW TAB, so the click is wrapped in expect_page(): the click
    returns before the page exists, and patchright's evaluate runs in an
    isolated world, so any "read the current page" shortcut quietly reads the
    OLD tab.
    """
    _expand(modal, config.DOCS_ROW, page)
    with page.context.expect_page(timeout=30000) as popup:
        _click_any(modal, "Access Digital Doc Portal", page=page)
    tab = popup.value
    tab.wait_for_load_state("domcontentloaded", timeout=60000)
    return tab


def _expand(modal, label: str, page, *, reveals: str = "",
            verbose: bool = True) -> None:
    """Open one collapsible Set Status section and WAIT for its contents.

    Two traps, both hit on the first Lucy 3 probe (2026-08-25):

    `filter(has_text=...).first` matches the OUTERMOST element containing the
    text -- and since the whole modal contains it, that is the modal. Clicking
    that expands nothing, and the probe then reported the portal button simply
    absent. `.last` is the innermost match, which is the row itself.

    And the click has to be FOLLOWED by a wait. These sections render their
    contents on expand, so looking immediately finds nothing even when the
    click worked -- the same reveal-one-control-at-a-time shape as the document
    form, in a different place.
    """
    rows = modal.locator("div,li,tr").filter(has_text=label)
    target = rows.last if rows.count() else modal.get_by_text(label).first
    target.scroll_into_view_if_needed(timeout=8000)
    target.click(timeout=10000)
    marker = reveals or "Access Digital Doc Portal"
    try:
        modal.get_by_text(marker, exact=False).first.wait_for(
            state="visible", timeout=8000)
        return
    except Exception:
        pass
    # Some rows only respond on the chevron, not the label. Try the last
    # clickable thing on the row before giving up.
    if verbose:
        print(f"    ({label}: label click didn't reveal — trying the chevron)")
    try:
        target.locator("svg,i,button,span").last.click(timeout=6000)
        modal.get_by_text(marker, exact=False).first.wait_for(
            state="visible", timeout=8000)
    except Exception:
        if verbose:
            print(f"    ({label}: still not expanded — the caller will say "
                  f"what it could not find)")


def _pick_typeahead(tab, wanted: str, *, expect_single: bool) -> None:
    """Select Bundle. A typeahead, not a <select> — select_option never touches
    it, so: click it open, type, then click the option.

    REFUSAL: under this bundle type the list holds exactly ONE real option
    besides the placeholder. If it ever holds more, the campaign or the plan
    changed, and taking row one of a list that quietly grew is how somebody gets
    mailed the wrong contract. Stop instead.
    """
    box = tab.locator("input[type='search']:visible, "
                      ".select2-search__field, [role='combobox']").first
    tab.locator("text=-Select a Bundle-").first.click(timeout=15000)
    box.wait_for(state="visible", timeout=10000)

    opts = [o.strip() for o in
            tab.locator("li[role='option'], .select2-results__option"
                        ).all_inner_texts()]
    real = [o for o in opts if o and not o.lower().startswith("-select")]
    if expect_single and len(real) > 1:
        raise Refused(
            f"Select Bundle offers {len(real)} options ({real[:4]}), expected "
            f"only {wanted!r} — the campaign or the plan changed. Refusing "
            "rather than picking one.")
    if wanted not in real:
        raise Refused(f"Select Bundle has no {wanted!r} (saw {real[:4]})")

    box.press_sequentially(wanted[:12], delay=40)
    tab.wait_for_timeout(600)
    tab.locator("li[role='option'], .select2-results__option").filter(
        has_text=wanted).first.click(timeout=10000)


def _required_fields_filled(tab) -> tuple:
    """(ok, empties). Every required input on the per-document form must carry
    a value before we submit.

    Megan: "I don't think anything is hand typed" — they pre-fill. But that is a
    belief about a form nobody has watched populate itself, and being wrong
    means a contract mailed with a blank employee name on it. One read turns a
    bet into a refusal.
    """
    empties = []
    fields = tab.locator("input[required]:visible, "
                         "input[aria-required='true']:visible")
    for i in range(fields.count()):
        f = fields.nth(i)
        if not (f.input_value(timeout=3000) or "").strip():
            empties.append(f.get_attribute("name") or f"field #{i + 1}")
    return (not empties), empties


def generate_bundle(tab, name: str, *, dry_run: bool = True,
                    verbose: bool = True) -> str:
    """The reveal chain. Each step waits for the control the previous revealed.

    bundle type -> `Generate Bundle` -> Select Bundle -> commission boxes ->
    `Get Documents for Selected Bundle` -> verify -> `Generate Document`.

    Only that last click sends anything, and it cannot be undone.
    """
    # 1. Bundle Type. Same for every new start right now; a wireless or retail
    #    office will want a different one, which is why it is a constant.
    tab.get_by_text(config.BUNDLE_TYPE, exact=False).first.click(timeout=20000)

    # 2. Reveals the bundle dropdown — it does NOT generate anything.
    _click_any(tab, "Generate Bundle", page=tab)
    tab.locator("text=-Select a Bundle-").first.wait_for(
        state="visible", timeout=20000)

    # 3. Reveals the commission checkboxes.
    _pick_typeahead(tab, config.BUNDLE,
                    expect_single=config.BUNDLE_EXPECT_SINGLE_OPTION)

    # 4. Tick ours, leave the others strictly alone.
    for label in config.COMMISSION_BUNDLES_TICK:
        box = tab.locator("label", has_text=label).first
        box.wait_for(state="visible", timeout=20000)
        box.click(timeout=10000)

    # 5. Opens the long per-document form. Still not the submit.
    _click_any(tab, "Get Documents for Selected Bundle", page=tab)
    tab.wait_for_load_state("networkidle", timeout=60000)

    # 6. Refuse rather than submit a half-filled contract.
    ok, empties = _required_fields_filled(tab)
    if not ok:
        raise Refused(f"{name}: {len(empties)} required field(s) empty on the "
                      f"document form ({empties[:3]}) — not submitting")

    if dry_run:
        if verbose:
            print(f"  {name}: form ready, required fields filled — STOPPING "
                  "(dry run)")
        return "dry"

    # 7. The only irreversible step in the whole run.
    btn = tab.get_by_role("button", name="Generate Document", exact=False).first
    btn.scroll_into_view_if_needed(timeout=10000)
    btn.click(timeout=20000)
    tab.wait_for_load_state("networkidle", timeout=90000)
    return "generated"


def confirm_generated(tab, name: str) -> bool:
    """Banner: "Successfully Added Document(s) for <Name>". OwnerVille emails
    the bundle from here — generating IS the send, there is no separate step."""
    try:
        tab.get_by_text("Successfully Added Document", exact=False).first \
           .wait_for(state="visible", timeout=30000)
        return True
    except Exception:
        return False


def tick_attestations(page, modal, *, dry_run: bool = True,
                      verbose: bool = True) -> list:
    """BACKGROUND CHECK (1 box), DRUG TEST (2), SERVICE -> RES-ATT, Save Changes.

    Returns the labels actually ticked, and the caller logs them per rep. That
    log is the point: the second drug-test box states the company HAS REVIEWED
    the drug screen and confirmed it passes — an assertion to AT&T, not a status
    flag. Megan's call (2026-08-25) is to tick it, so we do what the hand
    process does; recording which reps we asserted it for is what keeps it
    auditable rather than invisible.
    """
    ticked = []
    for section, labels in ((config.DOCS_ROW.replace("ONBOARDING DOCUMENTS",
                                                     "BACKGROUND CHECK"),
                             config.BG_CHECK_TICK),
                            ("DRUG TEST", config.DRUG_TEST_TICK)):
        _expand(modal, section, page, reveals=labels[0][:28])
        for frag in labels:
            box = modal.locator("label", has_text=frag).first
            box.wait_for(state="visible", timeout=15000)
            if not dry_run:
                box.click(timeout=10000)
            ticked.append(frag)

    _expand(modal, "SERVICE", page, reveals=config.SERVICE_RADIO)
    radio = modal.locator("label", has_text=config.SERVICE_RADIO).first
    radio.wait_for(state="visible", timeout=15000)
    if not dry_run:
        radio.click(timeout=10000)
        _click_any(modal, "Save Changes", page=page)
        page.wait_for_load_state("networkidle")
    ticked.append(config.SERVICE_RADIO)
    if verbose:
        print(f"  attestations {'WOULD be' if dry_run else ''} ticked: "
              f"{len(ticked)}")
    return ticked
