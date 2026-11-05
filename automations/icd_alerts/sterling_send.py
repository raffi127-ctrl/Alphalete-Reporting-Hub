"""Send Sterling background-check e-invites from this office's own computer.

Called by office_jobs for a 'bgc_send' job. The people come from the office
admin's ticks on the office admin page (read off ApplicantStream on the
admin's own computer).

WHY HERE (Megan 2026-11-03): the office admin is somewhere else; THIS is the
computer that holds the office's Sterling login. The admin's page queues the
job (office_admin/relay_client.py); office_jobs.py hands it to us.

THE SIGN-IN: Sterling emails a code on every login (noreply@us.fadv.co,
"Authentication Request", "Your authentication code is 966828."). Same road
as SaraPlus codes: the office's Gmail filter forwards ONLY those code mails
to the reporting inbox, the office's address goes on the relay workbook's
'Sterling Code Mail' tab, and at the code screen this calls code() below --
Lucy 1 (code_answer, service "sterling") finds the code and hands it back.

WIRED 2026-11-04, after a full live dry run on Megan's Mac (try_here): sign
in -> "Multiple user alert" Yes -> Client Hub Invite Candidate -> Position +
Package Elite -> Location type-ahead -> Next -> Bulk Upload -> "1 found",
stopped before Send Invites. The route is resources/sterling/portal-map.md.
  * dry  -> does ALL of that on this computer, stops before Send Invites,
            answers who it WOULD invite (the office's mode, set on our side)
  * live -> presses Send Invites and waits for "Your Bulk Upload is
            Processing". A failure AT Send is reported UNCONFIRMED, never
            retried -- a second press could invite people twice.
Press_send (the bottom-right button vs the "Send Invite(s)" tab) is the one
step not yet seen working: watch the first live job.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

WIRED = True

# --- the E-Invite form's Order Information (Megan 2026-11-03, screenshots;
# resources/sterling/portal-map.md section 4) ---------------------------------
# Bill To, WFD Workflow and Charge Type come prefilled on each ICD's own
# account and are never touched. These three are picked:
# Job Position: each ICD account lists ~3; the right one is whichever says
# "Elite" -- "Sterling - Elite" on some, "Sterling Elite / Extra" on others
# (Megan 2026-11-04). pick_elite: exactly one, else stop.
# Screening Package: same rule (Megan 2026-11-04) -- the one saying Elite.
JOB_POSITION = "Sterling - Elite"
SCREENING_PACKAGE = "Sterling - Elite"
# Bill Code: "just the only option that pops up for that office" -- 1658411
# on Raf's account. Anything but exactly one real option is a stop, never a
# guess (pick_bill_code).
_PLACEHOLDER_PREFIX = "<"


def pick_bill_code(options: List[str]) -> str:
    """The office's one Bill Code, off the dropdown's visible options.
    Raises ValueError unless there is exactly one real (non-placeholder)."""
    real = [o.strip() for o in options or []
            if o and o.strip() and not o.strip().startswith(_PLACEHOLDER_PREFIX)]
    if len(real) != 1:
        raise ValueError("expected exactly one Bill Code for this office, found %d (%s)"
                         % (len(real), ", ".join(real) or "none"))
    return real[0]


def pick_elite(options: List[str]) -> str:
    """The Job Position / Screening Package option that says Elite. Raises ValueError unless
    exactly one (non-placeholder) option does."""
    hits = [o.strip() for o in options or []
            if o and not o.strip().startswith(_PLACEHOLDER_PREFIX)
            and "elite" in o.lower()]
    if len(hits) != 1:
        raise ValueError("expected exactly one Elite job position, found %d (%s)"
                         % (len(hits), ", ".join(hits) or "none"))
    return hits[0]


def pick_option(options: List[str], want: str) -> str:
    """`want` among the dropdown's options, ignoring case/spacing. Raises
    ValueError when this account doesn't offer it."""
    norm = lambda x: " ".join((x or "").split()).lower()  # noqa: E731
    for o in options or []:
        if norm(o) == norm(want):
            return o
    raise ValueError("this Sterling account has no %r option" % want)


# --- THE WAY WE SEND: Client Hub bulk upload (Megan 2026-11-04, from Raf's
# Loom e7aecd44b6c84d1c8889a2b5f996d780) ---------------------------------------
# Old portal home -> "Click Here to access Client Hub" -> Invite Candidate ->
# Workflow Consent Plus -> Position (Elite) -> Package (Elite) -> Location
# (office state + city) -> Next -> Bulk upload: Sterling's CSV template is
# three columns. One upload sends the whole list.
# The three Position/Package options are "Drug Screen", "NBR" and the Elite
# one ("Elite" or "Elite / Extra") -- pick_elite.
# HEADERS ARE THE REAL TEMPLATE'S (Client Hub "CSV Template" button, downloaded
# 2026-11-04, copy at resources/sterling/client-hub-template.csv): exactly
# "First,Last,Email" + CRLF. The video said "First Name, Last Name, Email
# Address" -- that was wrong.
CSV_HEADERS = ("First", "Last", "Email")


# Client Hub's "Location of Job/Position" is ONE box that ends up reading
# "Plano, TX, USA" (Megan screenshot 2026-11-04) -- city, two-letter state,
# USA. The office's saved State is the full name, so it's shortened here.
STATE_CODES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}


def location_text(location: Dict) -> str:
    """What the Location box should read: 'Plano, TX, USA'. Raises
    ValueError on a state we can't shorten (never a guess)."""
    city = " ".join(str((location or {}).get("city") or "").split())
    state = str((location or {}).get("state") or "").strip()
    code = STATE_CODES.get(state)
    if not (city and code):
        raise ValueError("no usable office location (%r, %r)" % (city, state))
    return "%s, %s, USA" % (city, code)


def location_matches(shown: str, location: Dict) -> bool:
    """Does the box's text (or a suggestion) name the office's city + state?
    Case and spacing don't matter; 'USA' may or may not be there."""
    # Commas don't count: the suggestions read "Plano TX, USA" (city in
    # bold, no comma before the state -- live run 11/04).
    norm = lambda x: (x or "").replace(",", " ").lower().split()  # noqa: E731
    want = norm(location_text(location))
    got = norm(shown)
    return got == want or got == want[:-1]


def pick_location_suggestion(suggestions: List[str], location: Dict) -> str:
    """The Location box is a type-ahead: type the city, a list pops up, click
    one (Megan 2026-11-04). Returns the suggestion naming the office's city +
    state; raises ValueError when none does -- never the first Plano listed."""
    for s in suggestions or []:
        if location_matches(s, location):
            return s
    raise ValueError("no location suggestion for %s among %d shown"
                     % (location_text(location), len(suggestions or [])))


# After the file is attached the card reads "Bulk candidates uploaded: N found";
# after Send Invites a pop-up "Your Bulk Upload is Processing" / "Your file has
# been submitted. A confirmation email will be sent momentarily." [OK]
# (Megan screenshots 2026-11-04). The pop-up is the proof it was submitted.
SUBMITTED_TITLE = "Your Bulk Upload is Processing"


def found_count(text: str) -> int:
    """N out of 'Bulk candidates uploaded: N found'; -1 when not shown."""
    import re
    m = re.search(r"uploaded:\s*([\d,]+)\s*found", text or "", re.I)
    return int(m.group(1).replace(",", "")) if m else -1


def check_found(text: str, expected: int) -> None:
    """Before Send Invites: Sterling must have read exactly the rows we wrote.
    Raises ValueError otherwise -- a short read is never sent."""
    n = found_count(text)
    if n != expected:
        raise ValueError("Sterling read %s candidate(s) from the file, expected %d"
                         % ("no" if n < 0 else n, expected))


def build_csv(people: List[Dict]) -> str:
    """The bulk-upload file for `people`. One row per person, de-duplicated
    by email (Sterling refuses a second invite to the same address anyway)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_HEADERS)
    seen = set()
    for p in people or []:
        first = " ".join(str(p.get("first_name") or "").split())
        last = " ".join(str(p.get("last_name") or "").split())
        email = str(p.get("email") or "").strip()
        if not (first and last and "@" in email) or email.lower() in seen:
            continue
        seen.add(email.lower())
        w.writerow((first, last, email))
    return buf.getvalue()


def code(since: dt.datetime, office_key: str = "", log=print) -> str:
    """The Sterling code mailed after `since`, via Lucy 1. Raises
    sara_code.NoCode when none comes (no forward set up, or too slow)."""
    from automations.icd_alerts import sara_code
    return sara_code.code_from_relay(since, office_key=office_key, log=log,
                                     service="sterling")


def _name(p: Dict) -> str:
    return ("%s %s" % (p.get("first_name") or "", p.get("last_name") or "")).strip()


# --- the browser ------------------------------------------------------------
LOGIN_URL = "https://auth.sterlingcheck.app/oauth2/login?client_id=15smt5dkm826r0lbofg6c67loq"
PORTAL_HOST = "secure.sterlingdirect.com"
HUB_HOST = "sterlingcheck.app/dashboard"
HUB_START = "https://sterlingcheck.app/dashboard/#/start-order/?orderPage41=start-order"
CODE_HEADING = "We just sent you a verification code"
STEP_TIMEOUT_MS = 30_000


class StepFailed(RuntimeError):
    """One step of the route didn't go as mapped. `step` names it."""

    def __init__(self, step: str, why: str):
        super().__init__("%s: %s" % (step, why))
        self.step = step


def _snap_dir():
    from automations.icd_alerts import config as C
    d = C.APP_DIR / "sterling-snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snap(page, step: str, log=print) -> None:
    """Save what the page looked like when a step failed (HTML + picture),
    so the click path can be fixed from what was really there."""
    try:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        base = _snap_dir() / ("%s-%s" % (stamp, step))
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        log("      page saved: %s.(html|png)" % base)
    except Exception:  # noqa: BLE001 -- a snapshot never hides the real fault
        pass


# ScreeningDirect allows ONE session per username. Right after the code it may
# ask "Multiple user alert -- This username is already in use. Would you like
# to disconnect them so you can login?" [Yes] [No] (secure.sterlingdirect.com/
# oidc/idpresponse, Megan 2026-11-04): click YES -- it signs the other session
# out (the ICD's own browser, if they're in Sterling right then).
MULTI_USER_TITLE = "Multiple user alert"


def clear_multi_user(page, log=print) -> bool:
    """Press Yes on the 'Multiple user alert' if it's up. True if pressed."""
    try:
        if MULTI_USER_TITLE.lower() not in (page.inner_text("body") or "").lower():
            return False
        page.get_by_role("button", name="Yes", exact=True).first.click()
        log("      'username already in use' -- disconnected the other session (Yes)")
        page.wait_for_timeout(3000)
        return True
    except Exception:  # noqa: BLE001 -- not there is the normal case
        return False


def _on_portal(url: str) -> bool:
    return PORTAL_HOST in (url or "") or HUB_HOST in (url or "")


def _context(p, headless: bool, profile_dir=None, banner: bool = True):
    from automations.icd_alerts import config as C
    prof = profile_dir or C.STERLING_PROFILE_DIR
    prof.mkdir(parents=True, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(str(prof), headless=headless,
                                               args=["--disable-sync"])
    # The red "do not log in" bar -- never on try_here, where a person MUST.
    if not headless and banner:
        try:
            from automations.shared import browser_banner
            browser_banner.attach(ctx)
        except Exception:  # noqa: BLE001
            pass
    return ctx


def _cookie_banner(page) -> None:
    """Osano's banner on the login page: always 'Deny Non-Essential'."""
    try:
        b = page.get_by_role("button", name="Deny Non-Essential")
        if b.count() and b.first.is_visible():
            b.first.click()
    except Exception:  # noqa: BLE001 -- not shown is fine
        pass


def _type_code(page, code_: str) -> None:
    """Six single-digit boxes: type into the first and let it advance; if it
    doesn't, fill box by box."""
    boxes = page.locator("input:visible")
    n = boxes.count()
    if n == 0:
        raise StepFailed("code", "no code boxes on the page")
    boxes.first.click()
    page.keyboard.type(code_, delay=80)
    got = "".join((boxes.nth(i).input_value() or "") for i in range(min(n, 6)))
    if got != code_ and n >= len(code_):
        for i, d in enumerate(code_):
            boxes.nth(i).fill(d)


def _enter_user(page, username: str, log=print) -> None:
    """The User ID step. A REMEMBERED computer shows the box already filled and
    LOCKED (Raf's MacBook 11/05: `<input disabled id="user...">`, both setup
    runs timed out typing into it) with the Password box right under it -- so:
      * locked + shows this user  -> nothing to type, straight to Password
      * locked + shows SOMEONE ELSE -> clear it (the X / "Not you?") and type
      * open                       -> type it and press Continue"""
    user = page.get_by_label("User ID / Email")
    user.wait_for(timeout=STEP_TIMEOUT_MS)
    for _ in range(10):                      # a box can be locked for a moment while the page loads
        if user.is_enabled():
            break
        page.wait_for_timeout(500)
    if user.is_enabled():
        user.fill(username)
        page.get_by_role("button", name="Continue").click()
        return
    shown = (user.input_value() or "").strip().lower()
    if shown == username.strip().lower():
        log("      Sterling remembers %s -- straight to the password" % username)
        return
    log("      Sterling remembers a different user (%s) -- switching" % (shown or "?"))
    for label in ("Not you?", "Clear", "Change"):
        b = page.get_by_text(label, exact=False)
        if b.count() and b.first.is_visible():
            b.first.click()
            break
    else:
        page.locator('button[aria-label*="lear"], [data-testid*="clear"]').first.click()
    user.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
    page.wait_for_timeout(1000)
    if not user.is_enabled():
        raise StepFailed("login", "Sterling shows user %r and won't let it be changed" % shown)
    user.fill(username)
    page.get_by_role("button", name="Continue").click()


def sign_in(page, creds: Dict, *, office_key: str = "", get_code=None, log=print) -> None:
    """Login page -> (code) -> portal. Already signed in (remembered) = no-op.
    get_code(since) supplies the emailed code; default = Lucy 1 via code()."""
    page.goto(LOGIN_URL, timeout=STEP_TIMEOUT_MS)
    page.wait_for_timeout(2500)
    if _on_portal(page.url):
        log("      already signed in")
        return
    _cookie_banner(page)
    try:
        _enter_user(page, creds["username"], log)
        page.get_by_label("Password").fill(creds["password"], timeout=STEP_TIMEOUT_MS)
        remember = page.get_by_label("Remember me")
        if remember.count() and not remember.is_checked():
            remember.check()
        since = dt.datetime.now().astimezone()
        page.get_by_role("button", name="Sign In").click()
    except StepFailed:
        raise
    except Exception as e:  # noqa: BLE001
        _snap(page, "login", log)
        raise StepFailed("login", "%s: %s" % (type(e).__name__, str(e)[:160]))
    # Either the portal, or the code screen.
    for _ in range(40):
        page.wait_for_timeout(500)
        if _on_portal(page.url):
            log("      signed in (no code asked)")
            return
        if CODE_HEADING.lower() in (page.inner_text("body") or "").lower():
            break
    else:
        _snap(page, "after-sign-in", log)
        raise StepFailed("login", "neither the portal nor the code screen came up -- wrong password?")
    log("      Sterling asked for a code -- getting it from Lucy")
    try:
        code_ = (get_code or (lambda t: code(t, office_key=office_key, log=log)))(since)
    except Exception as e:  # noqa: BLE001 -- includes sara_code.NoCode
        raise StepFailed("code", "no code came back (%s) -- is the code forward set up?" % e)
    _type_code(page, code_)
    page.get_by_role("button", name="Continue").click()
    try:
        page.wait_for_url(lambda u: _on_portal(u), timeout=STEP_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        _snap(page, "code", log)
        raise StepFailed("code", "the code was not accepted")
    for _ in range(6):
        page.wait_for_timeout(1000)
        if clear_multi_user(page, log):
            break
    log("      signed in")


def _live_page(ctx, prefer=None):
    """A page in this browser that is still open (prefer `prefer`)."""
    if prefer is not None and not prefer.is_closed():
        return prefer
    for pg in reversed(ctx.pages):
        if not pg.is_closed():
            return pg
    return ctx.new_page()


def open_hub(page, log=print):
    """Portal home -> Client Hub's Invite Candidate. Returns the page it is
    on. The sign-in is shared across Sterling's sites, so it goes straight to
    Invite Candidate; the old portal's banner is only a fallback. A page that
    closes under it (the banner swapping windows, the multi-user Yes
    reloading -- live run 11/04) is replaced by one that's still open."""
    ctx = page.context
    try:
        clear_multi_user(page, log)
    except Exception:  # noqa: BLE001
        pass
    page = _live_page(ctx, page)
    for attempt in range(2):
        try:
            page.goto(HUB_START, timeout=STEP_TIMEOUT_MS)
            page.get_by_text("New Order Settings").wait_for(timeout=STEP_TIMEOUT_MS)
            page.wait_for_timeout(4000)   # its dropdown lists load after it draws
            return page
        except Exception as e:  # noqa: BLE001
            log("      Client Hub didn't open (%s) -- %s" % (
                type(e).__name__, "trying the portal's banner" if attempt == 0 else "giving up"))
            page = _live_page(ctx, page)
            if attempt == 0 and PORTAL_HOST in page.url:
                try:
                    with ctx.expect_page(timeout=8000) as newp:
                        page.get_by_text("Click Here", exact=False).first.click()
                    page = newp.value
                except Exception:  # noqa: BLE001 -- same tab
                    pass
                page = _live_page(ctx, page)
    _snap(page, "hub", log)
    raise StepFailed("hub", "Invite Candidate's 'New Order Settings' never showed")


# Client Hub's form, read off the real page 2026-11-04 (snapshot of the live
# run): react-select dropdowns wrapped in [data-testid="selectDropdown-<key>-
# wrapper"], each with a hidden <input name="<key>"> holding the chosen value;
# options render as .list__option; Location is input#locationOfEmployment
# (role=combobox, a type-ahead).
FIELD_KEYS = {"Position": "position", "Screening Package": "screeningPackage",
              "Billing Code": "billingCode"}


def field_value(page, key: str) -> str:
    """The chosen value of a Client Hub dropdown, from its hidden input."""
    loc = page.locator('input[name="%s"]' % key)
    return (loc.first.input_value() if loc.count() else "") or ""


def _visible_options(page) -> List[str]:
    """Visible option names, each ONCE: an option and its inner box both
    match (live run 11/04 saw 'Sterling - Elite' twice)."""
    opts = page.locator(".list__option, [role=option]")
    out: List[str] = []
    for i in range(opts.count()):
        o = opts.nth(i)
        if o.is_visible():
            t = " ".join((o.inner_text() or "").split())
            if t and t not in out:
                out.append(t)
    return out


def _open_list(page, key: str, tries: int = 4) -> List[str]:
    """Open a react-select's list and return its options.

    LIVE RUNS 11/04: the first run opened Position by CLICKING its input
    (#position-input) after the long way round through the portal; straight
    after a direct load, focus + Down opened nothing -- the lists fill in
    from the server a moment after the page draws. So: click the input, wait
    for real options (a "No options" notice = not loaded yet), retry."""
    for i in range(tries):
        try:
            page.locator("#%s-input" % key).click()
            page.locator(".list__option, .list__menu-notice").first.wait_for(
                state="visible", timeout=6_000)
            opts = _visible_options(page)
            if opts:
                return opts
        except Exception:  # noqa: BLE001
            pass
        page.keyboard.press("Escape")
        page.wait_for_timeout(2500 * (i + 1))
    return _visible_options(page)


def _choose(page, label: str, picker, log=print) -> str:
    key = FIELD_KEYS[label]
    slug = label.lower().replace(" ", "-")
    try:
        opts = _open_list(page, key)
        want = picker(opts)
        page.locator(".list__option, [role=option]").filter(
            has_text=want).first.click()
        page.wait_for_timeout(1000)
        got = field_value(page, key)
        if " ".join(got.split()).lower() != " ".join(want.split()).lower():
            raise ValueError("%s reads %r after picking %r" % (label, got, want))
        log("      %s: %s" % (label, got))
        return got
    except ValueError as e:
        page.keyboard.press("Escape")
        _snap(page, slug, log)
        raise StepFailed(label, str(e))
    except Exception as e:  # noqa: BLE001
        _snap(page, slug, log)
        raise StepFailed(label, "%s: %s" % (type(e).__name__, str(e)[:160]))


def fill_order(page, location: Dict, log=print) -> None:
    """Order Settings: Position + Package = the Elite one, Location by the
    type-ahead, everything prefilled left alone (Billing Code must show)."""
    _cookie_banner(page)   # Osano shows on Client Hub too
    _choose(page, "Position", pick_elite, log)
    _choose(page, "Screening Package", pick_elite, log)
    # Each office's Billing Code differs (prefilled); only an EMPTY one stops.
    if not any(ch.isdigit() for ch in field_value(page, "billingCode")):
        _snap(page, "billing-code", log)
        raise StepFailed("Billing Code", "the Billing Code is blank on this account")
    try:
        box = page.locator("#locationOfEmployment")
        box.click()
        box.fill("")
        # REAL KEYSTROKES: fill() set the text without the type-ahead
        # noticing -- no list (live run 11/04).
        box.press_sequentially(" ".join(str(location.get("city") or "").split()), delay=150)
        page.wait_for_timeout(3000)
        sugg = [" ".join(t.split()) for t in
                page.locator(".locationSuggestion:visible").all_inner_texts()]
        if not sugg:
            sugg = _visible_options(page)
        if not sugg:   # the type-ahead's list may not be role=option
            sugg = [" ".join(t.split()) for t in
                    page.locator("li:visible, .pac-item:visible, [id*=location] div:visible").all_inner_texts()
                    if t.strip()]
        if not any(location_matches(x, location) for x in sugg):
            _snap(page, "location-list", log)   # map what the list really is
        want = pick_location_suggestion(sugg, location)
        opt = page.locator(".locationSuggestion, .list__option, [role=option], li").filter(
            has_text=want.split()[-2] if len(want.split()) > 1 else want)
        opt = opt.filter(has_text=want.split()[0]) if opt.count() else opt
        (opt.first if opt.count() else page.get_by_text(want, exact=True).first).click()
        page.wait_for_timeout(1000)
        shown = box.input_value()
        if not location_matches(shown, location):
            raise ValueError("Location box reads %r" % shown)
        log("      Location: %s" % shown)
    except ValueError as e:
        _snap(page, "location", log)
        raise StepFailed("Location", str(e))
    except Exception as e:  # noqa: BLE001
        _snap(page, "location", log)
        raise StepFailed("Location", "%s: %s" % (type(e).__name__, str(e)[:160]))


def upload(page, people: List[Dict], log=print) -> int:
    """Next -> Bulk Upload -> attach the CSV -> 'N found' must match.
    Returns N. Does NOT press Send Invites."""
    import tempfile
    from pathlib import Path
    try:
        page.get_by_role("button", name="Next").click()
        page.get_by_text("Add Candidate").wait_for(timeout=STEP_TIMEOUT_MS)
        page.get_by_text("Bulk Upload", exact=True).first.click()
        page.wait_for_timeout(1000)
        rows = build_csv(people)
        n = len(rows.strip().splitlines()) - 1
        with tempfile.TemporaryDirectory(prefix="lucy-sterling-") as tmp:
            f = Path(tmp) / "candidates.csv"
            f.write_bytes(rows.encode("utf-8"))
            # The CSV's OWN input (accept=".csv,.txt"). The page's FIRST file
            # input belongs to an "Attachments" section -- live run 11/04 put
            # the list there and nothing happened.
            csv_in = page.locator('input[type=file][accept*=".csv"]')
            if csv_in.count() != 1:
                raise ValueError("expected one CSV upload box, found %d" % csv_in.count())
            csv_in.set_input_files(str(f))
            page.get_by_text("found", exact=False).first.wait_for(timeout=STEP_TIMEOUT_MS)
        check_found(page.inner_text("body"), n)
        log("      Sterling read %d candidate(s) from the file" % n)
        return n
    except ValueError as e:
        _snap(page, "upload", log)
        raise StepFailed("upload", str(e))
    except Exception as e:  # noqa: BLE001
        _snap(page, "upload", log)
        raise StepFailed("upload", "%s: %s" % (type(e).__name__, str(e)[:160]))


def press_send(page, log=print) -> None:
    """The bottom-right 'Send Invites' -- NOT the 'Send Invite' tab beside
    Bulk Upload -- then the 'Your Bulk Upload is Processing' pop-up."""
    import re
    btns = page.get_by_role("button", name=re.compile(r"^\s*send invites?\s*$", re.I))
    best, best_y = None, -1.0
    for i in range(btns.count()):
        b = btns.nth(i)
        box = b.bounding_box()
        if box and box["y"] > best_y:
            best, best_y = b, box["y"]
    if best is None:
        _snap(page, "send", log)
        raise StepFailed("send", "no Send Invites button")
    best.click()
    try:
        page.get_by_text(SUBMITTED_TITLE).wait_for(timeout=STEP_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        _snap(page, "send", log)
        raise StepFailed("send", "the 'Your Bulk Upload is Processing' pop-up never showed -- check Sterling before resending")
    try:
        page.get_by_role("button", name="OK").click()
    except Exception:  # noqa: BLE001
        pass
    log("      submitted")


def run_route(page, people: List[Dict], location: Dict, *, live: bool,
              creds: Optional[Dict] = None, office_key: str = "",
              get_code=None, log=print) -> Dict:
    """The whole mapped route on one page. live=False stops right before
    Send Invites."""
    if creds:
        sign_in(page, creds, office_key=office_key, get_code=get_code, log=log)
    page = open_hub(page, log)
    fill_order(page, location, log)
    n = upload(page, people, log)
    names = [_name(p) for p in people]
    if not live:
        return {"status": "dry_run", "would_send": names, "found": n,
                "location": location_text(location), "signed_in": True,
                "note": "test run -- everything filled, stopped before Send Invites"}
    press_send(page, log)
    return {"status": "sent", "sent": names, "found": n}


def send_invites(people: List[Dict], *, live: bool, office_key: str = "",
                 log=print, location: Dict = None) -> Dict:
    """-> {'status': 'sent'|'dry_run'|'error', 'sent': [...], 'failed': [...],
    'would_send': [...], 'error': str}."""
    people = [p for p in people or [] if _name(p) and "@" in str(p.get("email") or "")]
    if not people:
        return {"status": "error", "error": "nobody to invite"}
    # Sterling's "Location of Job/Position" -- the office's, set once on the
    # admin page. Without it the form cannot be submitted.
    location = location or {}
    if not (location.get("state") and location.get("city")):
        return {"status": "error", "error": "the office's city and state aren't set"}
    if not WIRED:
        if not live:
            return {"status": "dry_run", "would_send": [_name(p) for p in people],
                    "location": "%s, %s" % (location["city"], location["state"]),
                    "signed_in": False,
                    "note": "test run -- Sterling sign-in not wired yet, nothing sent"}
        return {"status": "error",
                "error": "sending from this computer isn't switched on yet -- send these in Sterling by hand",
                "failed": [_name(p) for p in people]}
    from automations.icd_alerts import config as C
    creds = C.sterling_creds()
    if not creds:
        return {"status": "error",
                "error": "this computer has no Sterling login saved -- run sterling_setup",
                "failed": [_name(p) for p in people]}
    try:
        location_text(location)
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _context(p, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return run_route(page, people, location, live=live, creds=creds,
                             office_key=office_key, log=log)
        except StepFailed as e:
            # Before Send nothing went out; at Send it is UNCONFIRMED.
            res = {"status": "error", "error": str(e), "step": e.step}
            if e.step == "send":
                res["unconfirmed"] = [_name(p_) for p_ in people]
            else:
                res["failed"] = [_name(p_) for p_ in people]
            return res
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def check_login(*, office_key: str = "", log=print) -> Dict:
    """Setup's test: sign in (with the code if asked) and reach Client Hub.
    {'ok': bool, 'error': str}. Sends nothing."""
    from automations.icd_alerts import config as C
    creds = C.sterling_creds()
    if not creds:
        return {"ok": False, "error": "no Sterling login saved"}
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = _context(p, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            sign_in(page, creds, office_key=office_key, log=log)
            open_hub(page, log)
            return {"ok": True}
        except StepFailed as e:
            return {"ok": False, "error": str(e)}
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


# --- trying it on our own Mac ------------------------------------------------
def _attempt(page, people, location, log=print) -> Dict:
    try:
        return run_route(page, people, location, live=False, log=log)
    except StepFailed as e:
        return {"status": "error", "error": str(e), "step": e.step,
                "snapshots": str(_snap_dir())}


def try_here(people: List[Dict], location: Dict, *, wait_min: int = 10,
             profile_dir=None, peek=None, stay_min: int = 0, stay_dir=None,
             log=print) -> Dict:
    """Mapping / dry run on OUR computer: a visible browser opens on
    Sterling's login, a PERSON signs in (password + code -- the bot never
    types them here), and once the portal shows the bot drives the rest and
    STOPS BEFORE Send Invites. Nothing is sent."""
    import sys
    import time
    from pathlib import Path
    from patchright.sync_api import sync_playwright
    prof = Path(profile_dir) if profile_dir else (
        Path(__file__).resolve().parents[2] / "output" / "sterling_try_profile")
    with sync_playwright() as p:
        ctx = _context(p, headless=False, profile_dir=prof, banner=False)
        # Labelled, so nobody signs in to some other Lucy job's window.
        ctx.add_init_script("""(() => { const t = () => { if (!document.title.startsWith('LUCY TEST'))
            document.title = 'LUCY TEST - ' + document.title; };
            document.addEventListener('DOMContentLoaded', t); setInterval(t, 1000); })()""")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL)
        # Other Lucy jobs on this Mac use the same "Chrome for Testing" app
        # (an OwnerVille window came up first, 11/04) -- put OURS in front.
        page.bring_to_front()
        log("  Sign in to Sterling in the window that opened (password + code).")
        log("  The bot takes over once the portal shows -- waiting up to %d min." % wait_min)
        end = time.time() + wait_min * 60
        last = None
        while not any(_on_portal(pg.url) for pg in ctx.pages):
            if time.time() > end:
                ctx.close()
                return {"status": "error", "error": "nobody signed in within %d min" % wait_min}
            urls = [pg.url for pg in ctx.pages]
            if peek:
                try:
                    ctx.pages[-1].screenshot(path=str(peek))
                except Exception:  # noqa: BLE001
                    pass
            if urls != last:
                log("    window shows: %s" % " | ".join(urls))
                last = urls
            time.sleep(2)
        log("  portal reached -- the bot takes over now")
        page = next(pg for pg in ctx.pages if _on_portal(pg.url))
        page.wait_for_timeout(3000)
        res = _attempt(page, people, location, log)
        if not stay_min:
            log("  Leaving the window open 60s so you can look -- nothing was sent.")
            page.wait_for_timeout(60_000)
            ctx.close()
            return res
        # STAY: keep the signed-in window; each time `<stay_dir>/retry`
        # appears, reload this module and run the route again in it -- no
        # second sign-in while the click path is being fixed.
        import importlib
        import json as _json
        stay_dir = Path(stay_dir or prof.parent)
        retry, stop = stay_dir / "retry", stay_dir / "stop"
        end = time.time() + stay_min * 60
        log("  Staying signed in %d min: touch %s to run again, %s to quit." % (stay_min, retry, stop))
        while time.time() < end and not stop.exists():
            if retry.exists():
                retry.unlink()
                try:
                    # By its real name: run as `python -m`, this file is
                    # __main__, which can't be reloaded (live run 11/04).
                    mod = importlib.reload(importlib.import_module(
                        "automations.icd_alerts.sterling_send"))
                    page = _live_page(ctx)
                    res = mod._attempt(page, people, location, log)
                except Exception as e:  # noqa: BLE001 -- never lose the signed-in window
                    res = {"status": "error", "error": "retry crashed: %s: %s"
                           % (type(e).__name__, str(e)[:200])}
                log("  RESULT " + _json.dumps(res))
            page.wait_for_timeout(1000)
        ctx.close()
        return res


def main(argv=None) -> int:
    """python -m automations.icd_alerts.sterling_send --try-here \\
           --first Megan --last Hidalgo --email you@x.com --city Plano --state Texas"""
    import argparse
    import json as _json
    ap = argparse.ArgumentParser(description="Sterling e-invites: dry run on this computer.")
    ap.add_argument("--try-here", action="store_true", required=True)
    ap.add_argument("--first", required=True)
    ap.add_argument("--last", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--city", required=True)
    ap.add_argument("--state", required=True, help="full name, e.g. Texas")
    ap.add_argument("--wait-min", type=int, default=10)
    ap.add_argument("--peek", default=None, help="keep a screenshot of the window here")
    ap.add_argument("--stay-min", type=int, default=0,
                    help="keep the signed-in window this long for re-runs")
    ap.add_argument("--stay-dir", default=None, help="where the retry/stop files go")
    a = ap.parse_args(argv)
    res = try_here([{"first_name": a.first, "last_name": a.last, "email": a.email}],
                   {"city": a.city, "state": a.state}, wait_min=a.wait_min, peek=a.peek,
                   stay_min=a.stay_min, stay_dir=a.stay_dir)
    print(_json.dumps(res, indent=1))
    return 0 if res.get("status") == "dry_run" else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
