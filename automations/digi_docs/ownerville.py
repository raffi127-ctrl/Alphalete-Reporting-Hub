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

import re

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
                  verbose: bool = True, employee_id: str | None = None,
                  known_absent: bool = False) -> str:
    """`+ Add Sales Rep` on View Progress. Returns 'added' | 'exists' | 'dry'.

    ADDING MAILS THEM (Megan 2026-08-31). OwnerVille sends the new start their
    onboarding email for the campaign they land on, so every path in here is a
    send with no unsend — which is why the campaign is chosen explicitly below
    and why `known_absent` is gated the way it is.

    NO TEAM IS SELECTED (Megan 2026-08-25). That dropdown sits between the
    employee picker and the Activate Now box — both of which we DO touch — so it
    reads like a required field and is precisely the one an automation would
    helpfully fill in. Activate Now is checked by default; leave it alone too.

    `known_absent` skips the per-person find_rep because a roster_snapshot has
    already answered it for the whole cohort. ONLY pass it for a name read as
    missing from a roster that PROVED it was complete — a partial read reports
    real people as absent, and absent-when-wrong now means a duplicate welcome
    email. OwnerVille's own picker is the backstop (it does not offer someone
    already on the campaign), but it is a backstop, not the plan.
    """
    if not known_absent:
        row, _campaign, _matched = find_rep(page, name, verbose=False)
        if row is not None:
            if verbose:
                print(f"  {name}: already in OwnerVille")
            return "exists"
    if dry_run:
        if verbose:
            print(f"  {name}: WOULD add")
        return "dry"

    # ADD ON THE RIGHT CAMPAIGN, EXPLICITLY. Whatever the page is showing is
    # wherever find_rep's walk ENDED, which is the last option in the dropdown
    # — "Water - Primo / RSW B2B". A morning of new starts went in under it
    # before anyone noticed (2026-08-31), and the campaign is not cosmetic: the
    # bundle list is per campaign, so the wrong one means the wrong contract.
    _select_campaign(page, config.ADD_CAMPAIGN, verbose=verbose)
    _click_any(page, "Add Sales Rep", page=page)
    modal = page.locator("div[role='dialog'], .modal:visible").filter(
        has_text="Add Sales Rep").first
    modal.wait_for(state="visible", timeout=20000)

    # The employee picker is the FIRST visible select in the modal; the team
    # picker is the second and stays on '-Select a Team-'.
    picker = modal.locator("select:visible").first
    picker.wait_for(state="visible", timeout=15000)
    _select_person(picker, name, employee_id=employee_id)

    _click_any(modal, "Add", page=page)
    page.wait_for_load_state("networkidle")
    if verbose:
        print(f"  {name}: added")
    return "added"


# --- the whole roster in one read (moved here from roster_check 2026-08-31) ---
# The add used to run a WHOLE-SITE SEARCH per person just to answer "is this
# person already here?" — reload View Progress, walk every campaign twice,
# type probes at 40ms a key. ~2 minutes each, so 54 people was 90 minutes of
# searching to do 54 modals, and two runs died on their timeout partway with
# the sends coming.
#
# Ask once instead. But the FIRST version of this read one page per campaign
# and called 24 rows a roster, which reported 29 real people as missing — so
# it now proves it read everything by comparing against DataTables' own "of N
# entries", and says so. An unproven roster is worth nothing here: since
# adding a rep MAILS them their onboarding email, "absent" being wrong is a
# duplicate welcome to a real person, not just noise.


def _norm_row(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def snapshot(page, *, verbose: bool = True) -> tuple:
    """(rows, complete) — every row on View Progress, and whether we PROVED it.

    2026-08-31, twice. The first version read `tbody tr` once per campaign and
    got 24, 1, 24 — page sizes, not rosters — and on that it reported 29 of 52
    people "not in OwnerVille", including two the add pass had logged as added
    the same morning. The second version tried to widen the length menu and walk
    Next, and reported the same 49 rows, so the pagination guess was wrong too.

    Guessing at pagination markup is what failed both times. So stop guessing
    and ask the table: DataTables prints "Showing 1 to 24 of 61 entries", and
    that N is the truth about how many rows exist. If what we read does not
    reach it, this run says INCOMPLETE and the caller must not claim anybody is
    missing — an under-read roster names real people as absent and invites
    adding them twice.
    """
    from automations.b2b_dispositions.capture import capture_rqst
    from automations.headshots.ov_upload import (
        VIEW_PROGRESS_P, _campaign_select, _show_all,
    )
    rqst = capture_rqst(page)
    page.set_default_navigation_timeout(90000)
    page.goto(f"https://v2.ownerville.com/index.cfm?p={VIEW_PROGRESS_P}"
              f"&rqst={rqst}", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:                       # noqa: BLE001
        pass
    sel = _campaign_select(page)
    rows_seen, complete = set(), True
    for opt in sel.locator("option").all_inner_texts():
        label = opt.strip()
        if not label:
            continue
        sel.select_option(label=label)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:                   # noqa: BLE001
            pass
        _show_all(page)
        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:                   # noqa: BLE001
            pass
        before = len(rows_seen)
        read = _read_pages(page, rows_seen)
        claimed = _entries_total(page)
        ok = claimed is None or read >= claimed
        complete = complete and ok
        if verbose:
            says = "?" if claimed is None else str(claimed)
            print(f"  {label}: read {read}, table says {says}"
                  f"{'' if ok else '  ⛔ INCOMPLETE'}"
                  f"  (+{len(rows_seen) - before} new)", flush=True)
    return rows_seen, complete


def _entries_total(page):
    """The N in DataTables' "Showing 1 to 24 of N entries". None if unreadable —
    unreadable is not zero, and the caller treats it as "cannot prove"."""
    try:
        txt = page.locator("div[id$='_info'], .dataTables_info").first.inner_text(
            timeout=4000)
    except Exception:                       # noqa: BLE001
        return None
    m = re.search(r"of\s+([\d,]+)\s+entries", txt or "", re.I)
    return int(m.group(1).replace(",", "")) if m else None


def _read_pages(page, rows_seen: set) -> int:
    """Read the visible page, then every following one. Returns rows READ (not
    unique), so it can be compared against the table's own entry count."""
    read = 0
    for _ in range(60):                     # backstop, never a real page count
        rows = page.locator("tbody tr")
        n = rows.count()
        for i in range(n):
            try:
                rows_seen.add(_norm_row(rows.nth(i).inner_text(timeout=2000)))
                read += 1
            except Exception:               # noqa: BLE001
                continue
        nxt = page.locator("a:has-text('Next'):visible, "
                           "li.next:visible a, a.paginate_button.next:visible"
                           ).first
        try:
            if not nxt.count():
                break
            klass = (nxt.get_attribute("class") or "") + " " + (
                nxt.evaluate("e => e.parentElement ? e.parentElement.className : ''")
                or "")
            if "disabled" in klass.lower():
                break
            nxt.click()
            page.wait_for_timeout(900)
        except Exception:                   # noqa: BLE001
            break
    return read


def present(rows_seen: set, name: str) -> bool:
    """Every part of the name somewhere in one row, in order, whitespace-loose —
    the same shape ov_upload._rep_row matches with."""
    parts = [re.escape(p) for p in name.split() if p]
    if not parts:
        return False
    pat = re.compile(r"\s+".join(parts), re.I)
    return any(pat.search(r) for r in rows_seen)

def _select_campaign(page, want: str, *, verbose: bool = True) -> str:
    """Put the campaign dropdown on `want` and wait for the table to reload.

    Refuses unless exactly one option matches. Adding on the wrong campaign is
    silent — the rep lands somewhere real, just not where their contract lives —
    so this must never fall back to whatever is already selected."""
    sel = _campaign_select(page)
    options = [o.strip() for o in sel.locator("option").all_inner_texts()
               if o.strip()]
    hits = [o for o in options if want.lower() in o.lower()]
    if len(hits) != 1:
        raise Refused(f"campaign {want!r} matched {len(hits)} of "
                      f"{len(options)} options ({options[:6]}) — refusing to "
                      f"add on a campaign we cannot name exactly")
    sel.select_option(label=hits[0])
    try:
        page.wait_for_load_state("networkidle", timeout=60000)
    except Exception:                                       # noqa: BLE001
        pass
    if verbose:
        print(f"  campaign: {hits[0]}")
    return hits[0]


def _select_person(picker, name: str, *, employee_id: str | None = None) -> None:
    """Pick the employee by the closest option label, or by employee id.

    OV spells names its own way, so match on the last name plus a first-name
    prefix rather than the exact string — the same reason find_rep probes short.
    Two options that both match is a REFUSAL, never a guess: adding the wrong
    person is the start of mailing them somebody else's contract.

    THE NAME IS NOT ALWAYS ENOUGH (Megan 2026-08-31). The directory held two
    Nathan Sanchez — different people, different emails, four weeks apart in
    start date — and the dropdown renders both as the identical string "Nathan
    Sanchez". No amount of name matching separates those. `employee_id` is how
    a human answers the question the page cannot: it matches the option's VALUE
    (the id OV carries there) or an id shown in the label, and still refuses
    unless exactly one option matches. An id that matches nothing is a refusal
    too — never a silent fall back to the ambiguous name, which is the one
    outcome that could mail a contract to the wrong person.
    """
    opts = picker.locator("option")
    options = [o.strip() for o in opts.all_inner_texts()]
    values = []
    for i in range(len(options)):
        try:
            values.append((opts.nth(i).get_attribute("value") or "").strip())
        except Exception:                   # noqa: BLE001
            values.append("")

    if employee_id:
        eid = str(employee_id).strip()
        hits = [i for i, (lbl, val) in enumerate(zip(options, values))
                if eid == val or eid in re.findall(r"\d+", val)
                or eid in re.findall(r"\d+", lbl)]
        if not hits:
            raise Refused(f"{name}: employee id {eid} is not in the Add Sales "
                          f"Rep list (saw {len(options)} option(s))")
        if len(hits) > 1:
            raise Refused(f"{name}: employee id {eid} matched {len(hits)} "
                          f"options — refusing to guess")
        picker.select_option(index=hits[0])
        print(f"  {name}: picked employee id {eid}")
        return

    parts = [p for p in name.split() if p]
    last = parts[-1].lower() if parts else ""
    first4 = parts[0][:4].lower() if len(parts) > 1 else ""
    hits = [o for o in options
            if last and last in o.lower() and (not first4 or first4 in o.lower())]
    if not hits:
        raise Refused(f"{name}: not in the Add Sales Rep employee list")
    if len(hits) > 1:
        raise Refused(f"{name}: {len(hits)} employees match ({hits[:3]}) — "
                      "refusing to guess. Re-run scoped with the employee id "
                      f"from the OV directory: --only \"{name}\" "
                      f"--employee-id <id>")
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


_STATES = ("REQUIRED ACTION", "COMPLETED", "PENDING")


def _status_rows(modal, label: str):
    """Every element in the Set Status modal containing `label`, INNERMOST
    first.

    `filter(has_text=...)` returns DOM order, so ancestors come before
    descendants and `.first` is the outermost match -- which, since the whole
    modal contains the text, is the modal. That trap already cost this build
    one round in _expand; both callers now share this one ordering so it cannot
    be re-learned in a third place.
    """
    rows = modal.locator("div,li,tr").filter(has_text=label)
    try:
        n = rows.count()
    except Exception:                                       # noqa: BLE001
        return []
    return [rows.nth(i) for i in range(n - 1, -1, -1)]


def _row_state(modal, label: str, *, verbose: bool = True) -> str:
    """The state chip on ONE Set Status row: 'REQUIRED ACTION' / 'COMPLETED' /
    'PENDING', or '' when it can't be read.

    The row is identified by carrying EXACTLY ONE chip. Anything smaller than
    the row (the label's own span) carries none; anything larger carries
    several, because every other step has a chip too. Reading the outermost
    match instead -- the whole modal -- returns whichever chip appears first in
    it, which for a new rep is always REQUIRED ACTION whatever this row
    actually says. That is the 2026-08-25 probe's silent bug: docs_still_owed
    answered True for everyone, so reps who already HAD their documents were
    walked all the way to the portal, where OwnerVille offered no bundle and
    the run called it a refusal.
    """
    for row in _status_rows(modal, label):
        try:
            txt = (row.inner_text(timeout=3000) or "").upper()
        except Exception:                                   # noqa: BLE001
            continue
        counts = {s: txt.count(s) for s in _STATES}
        if sum(counts.values()) == 1:
            state = next(s for s, c in counts.items() if c)
            if verbose:
                print(f"    {label}: {state}")
            return state
    if verbose:
        print(f"    {label}: no state chip found")
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
    return docs_row_state(modal) == config.DOCS_NEEDED_STATE


def docs_row_state(modal) -> str:
    """The ONBOARDING DOCUMENTS chip, for a caller that wants to SAY it.

    Probe 6 (2026-08-25) read 23 of 29 reps as PENDING and 6 as REQUIRED
    ACTION, and the skip line called all 23 "already has documents". PENDING
    and COMPLETED are not the same claim -- one is a bundle out and unsigned,
    the other is done -- and the Monday reader of that log should not have to
    know which one the code meant."""
    return _row_state(modal, config.DOCS_ROW)


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

    Three traps, each one paid for by a probe run (2026-08-25):

    `filter(has_text=...).first` matches the OUTERMOST element containing the
    text -- and since the whole modal contains it, that is the modal. Clicking
    that expands nothing (run 3).

    `.last` is the innermost match, which is usually the row -- but on
    BACKGROUND CHECK it is a node inside the collapsed body, and the run died
    on it with "element is not visible / retrying scroll into view action"
    (run 5). So walk innermost outwards and take the first VISIBLE candidate
    rather than trusting either end of the list.

    And the click has to be FOLLOWED by a wait: these sections render their
    contents on expand, so looking immediately finds nothing even when the
    click worked.
    """
    marker = reveals or "Access Digital Doc Portal"
    target = None
    for row in _status_rows(modal, label):
        try:
            if row.is_visible():
                target = row
                break
        except Exception:                                   # noqa: BLE001
            continue
    if target is None:
        try:
            target = modal.get_by_text(label, exact=False).first
        except Exception:                                   # noqa: BLE001
            target = None
    if target is None:
        # SAY WHAT IS ACTUALLY THERE (2026-08-31). "DRUG TEST" stopped
        # expanding for every rep in the 12:04 run and the log could only
        # report that it had not — leaving the real section name unknowable
        # from the log, which is the one thing needed to fix it.
        try:
            seen = [t.strip()[:40] for t in
                    modal.locator("div,li,tr").all_inner_texts()[:40]
                    if t.strip() and len(t.strip()) < 60]
            print(f"    ({label}: not found. Sections visible: {seen[:12]})")
        except Exception:                                   # noqa: BLE001
            pass
        raise Refused(f"{label}: no such section in the Set Status modal")

    try:
        target.scroll_into_view_if_needed(timeout=8000)
    except Exception:                                       # noqa: BLE001
        # Not fatal on its own -- the click below may still land, and a section
        # already in view needs no scroll. Killing a 30-rep batch over it
        # (run 5) is the wrong trade.
        if verbose:
            print(f"    ({label}: couldn't scroll into view — clicking anyway)")
    try:
        target.click(timeout=10000)
    except Exception:                                       # noqa: BLE001
        if verbose:
            print(f"    ({label}: the row itself wasn't clickable)")
    try:
        modal.get_by_text(marker, exact=False).first.wait_for(
            state="visible", timeout=8000)
        return
    except Exception:                                       # noqa: BLE001
        pass
    # Some rows only respond on the chevron, not the label. Try the last
    # clickable thing on the row before giving up.
    if verbose:
        print(f"    ({label}: label click didn't reveal — trying the chevron)")
    try:
        target.locator("svg,i,button,span").last.click(timeout=6000)
        modal.get_by_text(marker, exact=False).first.wait_for(
            state="visible", timeout=8000)
        return
    except Exception:                                       # noqa: BLE001
        pass
    if _force_expand(modal, label, marker, verbose=verbose):
        return
    if verbose:
        print(f"    ({label}: still not expanded — the caller will say "
              f"what it could not find)")


def _revealed(modal, marker: str, ms: int = 2200) -> bool:
    try:
        modal.get_by_text(marker, exact=False).first.wait_for(
            state="visible", timeout=ms)
        return True
    except Exception:                                       # noqa: BLE001
        return False


def _force_expand(modal, label: str, marker: str, *,
                  verbose: bool = True) -> bool:
    """Last resort: work through every plausible toggle for this section.

    WHY (Megan 2026-08-31, "fix the drug test"). BACKGROUND CHECK opened on the
    first strategy all morning and DRUG TEST opened on none of them — the row
    was found, but `the row itself wasn't clickable`, the label click revealed
    nothing, and the chevron did not answer either. Every rep in two runs
    failed there, so nobody's attestation boxes got ticked.

    Guessing which single element is the real toggle is what failed three
    times. So stop guessing: walk the candidate rows innermost outwards and,
    for each, try a real click, a JS click (which ignores overlays and
    pointer-events, the usual reason a visible element "isn't clickable"), and
    the clickable descendants — checking after every attempt whether the
    section actually opened. Bounded and short-timeout throughout, so the worst
    case is a slow section rather than a hung batch.

    Also handles <details>, where there is no click to make at all: the section
    opens by setting the attribute.
    """
    tried = 0
    for row in list(_status_rows(modal, label))[:6]:
        # a <details> section opens by attribute, not by click
        try:
            row.evaluate("e => { const d = e.closest('details');"
                         "       if (d) d.open = true; }")
            if _revealed(modal, marker):
                if verbose:
                    print(f"    ({label}: opened as a <details>)")
                return True
        except Exception:                                   # noqa: BLE001
            pass
        for how, act in (
            ("force click", lambda r=row: r.click(timeout=4000, force=True)),
            ("js click", lambda r=row: r.evaluate("e => e.click()")),
        ):
            tried += 1
            try:
                act()
            except Exception:                               # noqa: BLE001
                continue
            if _revealed(modal, marker):
                if verbose:
                    print(f"    ({label}: opened on a {how})")
                return True
        for sel in ("button", "a", "[role='button']", "svg", "i", "span"):
            try:
                kids = row.locator(sel)
                for i in range(min(kids.count(), 3)):
                    tried += 1
                    try:
                        kids.nth(i).evaluate("e => e.click()")
                    except Exception:                       # noqa: BLE001
                        continue
                    if _revealed(modal, marker):
                        if verbose:
                            print(f"    ({label}: opened on a {sel} inside "
                                  f"the row)")
                        return True
            except Exception:                               # noqa: BLE001
                continue
    if verbose:
        print(f"    ({label}: {tried} toggle attempt(s), none opened it)")
    return False


def _choose_bundle_type(tab, label: str, *, verbose: bool = True) -> None:
    """Select the Bundle Type radio, then SAY whether it actually took.

    Prefer the INPUT associated with the label over the label's text: clicking
    text can land on a node that isn't wired to the control, leaving the radio
    unset -- and then `Generate Bundle` reveals nothing and step 2 gets blamed
    for step 1's failure.

    Run 4 (2026-08-25) is exactly that ambiguity: the log showed the click
    happening and the next control missing, with no way to tell which of the
    two had gone wrong. So the click is now followed by a read of the radio's
    checked state, and the answer goes in the log either way.
    """
    how = ""
    for name, attempt in (
            ("role=radio", lambda: tab.get_by_role("radio", name=label,
                                                   exact=False)),
            ("label>input", lambda: tab.locator("label", has_text=label
                                                ).locator("input[type='radio']")),
            ("label", lambda: tab.locator("label", has_text=label)),
            ("text", lambda: tab.get_by_text(label, exact=False))):
        try:
            loc = attempt().first
            loc.wait_for(state="visible", timeout=6000)
            loc.click(timeout=6000)
            how = name
            break
        except Exception:
            continue
    if not how:
        raise Refused(f"couldn't select bundle type {label!r}")
    if verbose:
        print(f"    bundle type via {how}: {_radio_state(tab, label)}")


def _radio_state(tab, label: str) -> str:
    """'CHECKED' / 'NOT checked' / 'unreadable' for the radio named `label`.

    The last two shapes _choose_bundle_type tries click TEXT, which can leave
    the radio untouched while the click itself reports success. This is the
    read that tells those apart."""
    for attempt in (
            lambda: tab.get_by_role("radio", name=label, exact=False),
            lambda: tab.locator("label", has_text=label
                                ).locator("input[type='radio']")):
        try:
            loc = attempt().first
            if loc.count():
                return "CHECKED" if loc.is_checked(timeout=3000) else "NOT checked"
        except Exception:
            continue
    return "unreadable"


_DUMP_JS = """() => {
  const vis = (el) => { const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0; };
  const cut = (s, n) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, n);
  const out = [];
  document.querySelectorAll('select').forEach((s) => {
    if (!vis(s)) return;
    const opts = Array.from(s.options).slice(0, 3)
                      .map((o) => cut(o.text, 20));
    const sel = (s.selectedIndex >= 0)
                ? cut(s.options[s.selectedIndex].text, 28) : '(none)';
    out.push('SEL ' + cut(s.name || s.id, 16) + ' n=' + s.options.length +
             ' SELECTED=' + sel + ' [' + opts.join(' / ') + ']');
  });
  document.querySelectorAll('input').forEach((i) => {
    if (i.type === 'hidden') return;
    const box = (i.type === 'radio' || i.type === 'checkbox');
    if (!vis(i) && !box) return;
    const lab = (i.labels && i.labels[0]) ? i.labels[0].innerText : '';
    out.push('IN ' + i.type + ' ' + cut(i.name || i.id, 16) +
             (box ? (i.checked ? ' CHECKED' : ' off') : '') +
             (vis(i) ? '' : ' offscreen') +
             ' "' + cut(box ? lab : i.value, 30) + '"');
  });
  document.querySelectorAll('button, input[type=submit], a.btn').forEach((b) => {
    if (!vis(b)) return;
    out.push('BTN "' + cut(b.innerText || b.value, 38) + '"');
  });
  return out;
}"""


def _dump_controls(tab, when: str, *, limit: int = 44) -> None:
    """Print every control this page renders, one short line each.

    This is the lesson of runs 3 and 4 (2026-08-25). Both failed the same way:
    the code decided a control was there, walked on, and timed out clicking a
    different one -- and the log could only name the selector that missed,
    never what the page actually contains. Two rounds went on guessing at the
    markup from that. One read ends it.

    Lines are prefixed `PG|<nn>|` and deliberately SHORT. The mini's result
    cell holds ~470 characters, so this gets read back a slice at a time
    (`lucy logtail <log> 'PG|0'`, then `'PG|1'`, ...); long lines would cost a
    whole round trip each.
    """
    try:
        rows = tab.evaluate(_DUMP_JS)
    except Exception as e:                                  # noqa: BLE001
        print(f"PG|--| {when}: dump failed: {str(e).splitlines()[0][:70]}")
        return
    try:
        print(f"PG|--| {when} @ {tab.url[:64]}")
    except Exception:                                       # noqa: BLE001
        print(f"PG|--| {when}")
    for i, row in enumerate(rows[:limit]):
        print(f"PG|{i:02d}| {row[:72]}")
    if len(rows) > limit:
        print(f"PG|--| ...and {len(rows) - limit} more")


def _bundle_dropdown(tab, wanted: str, *, timeout: int = 20000):
    """Find the Select Bundle control and return (kind, locator), or (None, None).

    It has to BE that control. The previous version accepted the first visible
    `<select>` on the page, and that is precisely how run 4 (2026-08-25)
    reported the dropdown present and then timed out clicking a placeholder
    that was never there -- some other control on the form matched, the guard
    that should have said "Generate Bundle revealed nothing" stayed quiet, and
    the diagnostic it guards never printed.

    So a candidate only counts if it NAMES the bundle: the placeholder text, or
    `wanted` among its options. Anything else is not this dropdown, whatever
    shape it has.
    """
    waited, step = 0, 1000
    while waited < timeout:
        try:
            loc = tab.locator("text=-Select a Bundle-").first
            if loc.count() and loc.is_visible():
                return "text", loc
        except Exception:                                   # noqa: BLE001
            pass
        try:
            sels = tab.locator("select:visible")
            for i in range(sels.count()):
                sel = sels.nth(i)
                opts = " | ".join(
                    o.strip() for o in sel.locator("option").all_inner_texts())
                low = opts.lower()
                if "select a bundle" in low or wanted.lower() in low:
                    return "select", sel
        except Exception:                                   # noqa: BLE001
            pass
        try:
            boxes = tab.locator("[role='combobox']")
            for i in range(boxes.count()):
                box = boxes.nth(i)
                if "bundle" in (box.inner_text(timeout=2000) or "").lower():
                    return "combobox", box
        except Exception:                                   # noqa: BLE001
            pass
        tab.wait_for_timeout(step)
        waited += step
    return None, None


def _bundle_options(tab, kind: str, control) -> list:
    """Every real option the bundle control offers, placeholder removed."""
    if kind == "select":
        opts = [o.strip() for o in control.locator("option").all_inner_texts()]
    else:
        opts = [o.strip() for o in
                tab.locator("li[role='option'], .select2-results__option"
                            ).all_inner_texts()]
    return [o for o in opts if o and not o.lower().startswith("-select")]


def _pick_typeahead(tab, wanted: str, *, kind: str, control,
                    expect_single: bool, verbose: bool = True) -> None:
    """Choose the bundle, whichever shape the control turned out to be.

    Megan's Loom shows a typeahead (a text input inside an open list), so
    `select_option` would never touch it -- but the run has to survive being
    wrong about that, because being wrong about it is what cost run 4. If the
    control IS a real `<select>`, use select_option; otherwise click it open,
    type, and click the option.

    REFUSAL, either shape: under this bundle type the list holds exactly ONE
    real option. If it ever holds more, the campaign or the plan changed, and
    taking row one of a list that quietly grew is how somebody gets mailed the
    wrong contract. Stop instead.
    """
    if kind != "select":
        control.click(timeout=15000)
        tab.wait_for_timeout(600)

    real = _bundle_options(tab, kind, control)
    if verbose:
        print(f"    bundle list ({kind}): {real[:4]}")
    if expect_single and len(real) > 1:
        raise Refused(
            f"Select Bundle offers {len(real)} options ({real[:4]}), expected "
            f"only {wanted!r} — the campaign or the plan changed. Refusing "
            "rather than picking one.")
    if wanted not in real:
        raise Refused(f"Select Bundle has no {wanted!r} (saw {real[:4]})")

    if kind == "select":
        control.select_option(label=wanted)
        return
    box = tab.locator("input[type='search']:visible, .select2-search__field, "
                      "[role='combobox'] input:visible").first
    if box.count():
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
    # 0. On a dry run, say what this page HAS before touching it. The probe
    #    exists to read the page, and a selector timeout on its own never says
    #    what was actually rendered — two rounds were spent guessing that.
    if dry_run:
        _dump_controls(tab, "portal opened")

    # 1. Bundle Type. It is a RADIO, so click the input rather than the text —
    #    a text click lands on the label's text node and can leave the radio
    #    unset, which then makes step 2 look like the broken one.
    _choose_bundle_type(tab, config.BUNDLE_TYPE, verbose=verbose)

    # 2. Reveals the bundle dropdown — it does NOT generate anything.
    _click_any(tab, "Generate Bundle", page=tab)
    kind, control = _bundle_dropdown(tab, config.BUNDLE, timeout=20000)
    if control is None:
        _dump_controls(tab, "after Generate Bundle")
        raise Refused(
            f"{name}: 'Generate Bundle' revealed no bundle dropdown. Either the "
            f"bundle type {config.BUNDLE_TYPE!r} never got selected (the line "
            "above says whether its radio is CHECKED), or the dropdown renders "
            "differently than expected — the PG| lines list every control that "
            "IS on the page.")

    # 3. Reveals the commission checkboxes.
    _pick_typeahead(tab, config.BUNDLE, kind=kind, control=control,
                    expect_single=config.BUNDLE_EXPECT_SINGLE_OPTION,
                    verbose=verbose)

    # 4. Tick ours, leave the others strictly alone.
    for label in config.COMMISSION_BUNDLES_TICK:
        box = tab.locator("label", has_text=label).first
        box.wait_for(state="visible", timeout=20000)
        box.click(timeout=10000)

    # 5. Opens the long per-document form. Still not the submit.
    _click_any(tab, "Get Documents for Selected Bundle", page=tab)
    tab.wait_for_load_state("networkidle", timeout=60000)
    if dry_run:
        _dump_controls(tab, "document form")

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
