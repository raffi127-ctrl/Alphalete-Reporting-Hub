"""Drive Apex (apex.herbjoyent.com) to add one new start, from a real session.

NO CREDENTIAL HANDLING, EVER. This opens a browser and WAITS for a human to
sign in, exactly like `blueink_docs.session --login`. It never types a password
and it never sets one.

WHY IT DOESN'T COPY THE EVERYDAY CHROME PROFILE (the way apex_payroll does).
Tried that first, 2026-09-03, and it cannot work for this app. Apex's login is
carried in `ApexSession` / `ApexSession.RefreshToken`, and both are
NON-PERSISTENT cookies -- they live in the running browser's memory. Copying a
profile out from under a live Chrome gets whatever stale session was last
flushed to disk, which on Megan's machine was an expired one Apex answers by
redirecting every single page to 'change your password before you continue'.
Enabling session restore didn't recover it either. Meanwhile her own tab was
working fine, because her real session had never touched the disk.

So the session is made HERE, in a browser this module owns, and the run does
its work inside that one browser session. `Identity.TwoFactorRememberMe` IS a
persistent cookie, so once the device is remembered the sign-in is a password
and nothing else -- no code to chase.

WHY THE FIELDS ARE FOUND BY LABEL. Nobody had a logged-in Apex screen in front
of them when this was written, and hard-coding selectors from a screenshot is
how you type a birthday into a hire-date box. So every field is located by the
LABEL a person reads next to it -- 'Last Name', 'Zip', 'Birth Date' -- with the
wordings Apex might use listed as alternatives. Two consequences on purpose:

  * `--explore` writes the real screen's inventory to `apex_screen.json`, so
    the first logged-in run turns guesses into facts.
  * Anything not matched with confidence is NOT typed. It is reported, and the
    person is left for a human to finish. Half a record that says so beats a
    full record that is quietly wrong.

ISOLATION. The browser profile lives at `.apex_profile` inside this module --
under `automations/`, which is one of the paths `day_orchestrator.chrome_guard`
recognises as ours and will not kill as a stray human window. It shares nothing
with apex_payroll's copied CDP profile, so the two can run without colliding.
"""
from __future__ import annotations

import json
import re
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

APEX_URL = "https://apex.herbjoyent.com/"
ROSTER_URL = "https://apex.herbjoyent.com/roster"
# Our own browser profile, not a copy of anybody's. Gitignored by the
# .*_profile rule, same as the other patchright profiles in this repo.
PROFILE_DIR = Path(__file__).resolve().parent / ".apex_profile"
SCREEN_PATH = Path(__file__).resolve().parent / "apex_screen.json"

# The labels a person reads beside each box. ALL of the stage-one wordings are
# CONFIRMED off the live screen (Megan's screenshots of the whole form,
# 2026-09-03), and four of the guesses they replaced were wrong in ways that
# would have mattered:
#
#   guessed 'state'      real 'State Working In' -- 'state' would ALSO match the
#                        home-address state on the employee's own page, and the
#                        two are different facts: Texas is where they work, their
#                        address can say anything.
#   guessed 'rate'       real 'Rate of Pay' -- and 'Salary' sits directly under
#                        it, taking a number just the same.
#   guessed 'job title'  real 'Position'
#   nothing              real 'Department' -- required, and nobody had mentioned
#                        it until the form was seen end to end.
#
# STAGE TWO IS NOT ON THIS PAGE. Confirmed by seeing all of it: the form ends at
# Security Roles / Module Admin and carries no address, date of birth or Social
# anywhere. Those live on the employee's own record after the first Save, a page
# still nobody has captured.
LABELS: Dict[str, tuple] = {
    # --- Apex User Account --------------------------------------------------
    "first": ("first name",),
    "middle": ("middle name",),
    "last": ("last name",),
    "username": ("user name",),
    "account_email": ("account email",),
    # --- Employment Record --------------------------------------------------
    "hire_date": ("hire date",),
    "pay_frequency": ("pay frequency",),
    "position": ("position",),
    "pay_basis": ("basis of pay",),
    "pay_state": ("state working in",),
    "rate": ("rate of pay",),
    "department": ("department",),
    # --- stage two: 'User Profile & Account' on the employee's record -------
    # Confirmed off a real record (Andrea Herrera, 2026-09-03). Note that
    # 'Street Address' and 'Street Address 2' are separate boxes AND so is
    # 'Apt/PO Box' -- three of them, which is why matching is exact-first.
    "dob": ("date of birth",),
    "gender": ("gender",),
    "address1": ("street address",),
    "apt": ("apt/po box",),
    "address2": ("street address 2",),
    "city": ("city",),
    "state": ("state",),
    "zip": ("zip code",),
    "country": ("country",),
    "home_phone": ("home phone",),
    "mobile_phone": ("mobile phone",),
    # --- stage three: 'Tax & Bank Information' ------------------------------
    # Confirmed 2026-09-05 off /employees/<id>/edit/bank-info.
    # Apex spells it "Claim Dependants" -- with an A. Spelled the usual way it
    # matches nothing, silently, forever.
    "claim_dependents": ("claim dependants", "claim dependents"),
    "marital_status": ("marital status",),
    "tax_state": ("state to be taxed in",),
}

# STAGE TWO lives behind the 'User Profile & Account' tab of a saved employee.
# The record has three tabs: Employment Record, User Profile & Account, and Tax
# & Bank Information -- and the Social is on that THIRD one, which nobody has
# captured and which this report would not type into anyway.
STAGE_TWO_TAB = "User Profile & Account"

# WHICH PHONE BOX. The record has Home Phone and Mobile Phone, and the I-9 asks
# for one number without saying which it is. The existing rows put it in Home
# Phone (Andrea Herrera's reads there), so this follows the office's own habit
# rather than inventing a second convention -- one line to flip if Megan wants
# these in Mobile instead.
PHONE_FIELD = "home_phone"

# The I-9 writes a two-letter state ('TX'); this dropdown holds full names
# ('Texas'). Selecting 'TX' would select nothing at all.
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "PR": "Puerto Rico", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# Boxes on that form this report leaves exactly as it finds them:
#   Office        pre-filled text, not an input -- it is the office you are in.
#   Status        already 'Pending', which is what a new start is.
#   Salary        optional, and these people are hourly + commission.
#   Time Clock    both ticked by default; changing either is a policy decision
#   Require Break about how somebody is paid, not a fact off their I-9.
#   Divisions     already holds 'General', and the form's own note says a
#                 division is what puts them on the payroll -- already right.
LEAVE_ALONE = ("office", "status", "salary", "time clock", "require break",
               "divisions",
               # stage two:
               "user name",        # read-only text on the saved record
               "override the user's password",   # a checkbox, and a password
               "send password reset")            # a button that MAILS someone

# WHAT THIS OFFICE PUTS IN THE BOXES THAT NO FORM ANSWERS (Megan, 2026-09-03).
# The same for every new start, so they are settings, not data: a new hire's I-9
# cannot tell you what they are paid or what they are called here. Every one of
# these lands in a SELECT except the rate, so the value has to read EXACTLY as
# the option does -- '400 Sales' picks an option, '400' picks nothing.
DEFAULTS = {
    "position": "Sales Rep",
    "rate": "10.00",              # $10/hr, into 'Rate of Pay' (NOT 'Salary')
    "pay_state": "Texas",         # 'State Working In' -- where they WORK, not
                                  # the state on their I-9 address.
    "pay_basis": "Commissions",
    "pay_frequency": "Weekly",
    # The dropdown reads '100 Owner / 200 Admin / 400 Sales / 750 Chips /
    # 900 1099' -- department numbers, and the option text carries the number.
    "department": "400 Sales",
    # Required on the profile page and empty on a Pending record -- it is NOT
    # pre-filled the way an existing employee's is.
    "country": "United States",
}

# The tax tab's own settings, kept apart from DEFAULTS because they are filled
# on a DIFFERENT PAGE. Mixing them would have every stage-one fill report
# 'tax_state: no field matched' -- noise that trains people to ignore the
# warnings that matter.
TAX_DEFAULTS = {
    "tax_state": "Texas",       # 'State to be taxed in' -- same answer as
                                # 'State Working In' on the employment record.
}

# SECURITY ROLE. Required radio group -- Office Admin / ICD Payroll Admin /
# Sales Rep / Owner -- and Megan's answer is Sales Rep (2026-09-03). It is set
# by `set_security_role`, not by the ordinary fill: it is a radio, and radios
# are in NON_TEXT_TYPES precisely so nothing can ever be typed into one.
#
# Matched on the label's EXACT text. A substring match is not safe here when the
# options are 'Office Admin', 'ICD Payroll Admin' and 'Owner': this decides what
# somebody can SEE inside a payroll system, and the difference between Sales Rep
# and ICD Payroll Admin is the difference between their own numbers and
# everyone's.
SECURITY_ROLE = "Sales Rep"

# Nothing on stage one is unanswered any more (Megan settled Department and the
# security role, 2026-09-03). Kept, empty, because the machinery that reports
# unanswered fields is what should carry the NEXT one -- stage two is not
# captured yet, and its fields will land here first.
# Nothing is unanswered any more: Megan added a Gender column to the board's
# New Starts box (2026-09-03) rather than leave the one field Apex requires and
# no form asks for. Kept, empty, because it is the machinery that will carry the
# next unanswerable field if one turns up.
UNANSWERED = ()

# USER NAME. Their email WITHOUT the domain (Megan, 2026-09-09):
# aundrebrowder22@gmail.com -> aundrebrowder22.
#
# The whole email was tried first, because that is what every existing roster
# row shows. Apex refused it on the live form: "This username is not available
# as it is currently being used under another Apex account" -- usernames are
# unique across ALL of Apex, not just this company, so a Gmail address another
# Apex customer has already used is taken. The local part collides far less and
# still reads as the person.
USERNAME_FROM_EMAIL_LOCAL_PART = True

# Saving stage one sends mail: 'Send this user a password reset to their
# Account Email' is TICKED by default on that form. Nothing here unticks it or
# ticks it -- the operator sees the box and decides, because that is an email
# to a real new hire and not this report's call to make.
PASSWORD_RESET_CHECKBOX = ("send this user a password reset",)

# Never typed by this runner, on purpose -- see run.py's SENSITIVE note. Listed
# here so a stray entry in LABELS can never resurrect one.
NEVER_TYPE = ("ssn", "social security", "social", "routing", "account number",
              "bank")

# What must be matched on the ADD ROSTER EMPLOYEE screen before the run types
# anything. Every one of these is marked required by the form itself, and all of
# them are fillable from the I-9 + the board + DEFAULTS.
#
# The address, date of birth and Social are NOT here, and that is the point: they
# are not on this page at all (see LABELS). An earlier version listed them, which
# would have skipped every single person as 'missing required field' on a form
# that never had those boxes.
REQUIRED = ("first", "last", "username", "account_email", "hire_date",
            "pay_frequency", "position", "pay_basis", "pay_state", "rate",
            "department")


def _sync_api():
    """patchright if present (stealth), else plain playwright."""
    try:
        from patchright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        from playwright.sync_api import sync_playwright
        return sync_playwright


def _interactive() -> bool:
    """Is somebody at a keyboard? Waiting for a sign-in that can never come is
    worse than failing with a message that says what to do."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:  # noqa: BLE001
        return False


def have_session() -> bool:
    return PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir())


# Any sign-in / account screen, under either prefix Apex serves them from:
#   /Identity/Account/Login      /Account/SendCode
#   /Identity/Account/ChangePassword
_AUTH_PATH = re.compile(r"/(?:identity/)?account/")


class ApexSession:
    """A browser sitting on Apex, signed in -- waiting for a person if it isn't.

    The window is deliberately VISIBLE. Somebody is at the keyboard for this
    report anyway (they add each Social and click Save), so a headless browser
    would only hide the one screen they need to see.
    """

    def __init__(self, log=print, *, login_timeout_s: int = 600):
        self.log = log
        self.login_timeout_s = login_timeout_s
        self._pw = None
        self.ctx = None
        self.page = None

    def __enter__(self):
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = _sync_api()().start()
        try:
            self.ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False, no_viewport=True,
            # NO channel="chrome" on purpose. macOS allows one primary Google
            # Chrome instance, so launching the real Chrome while somebody has
            # their own open gets our launch adopted into theirs -- blank
            # about:blank tabs, the failure that broke every browser report on
            # 2026-07-01. The bundled browser is its own process and cannot
            # collide, and Apex is a plain ASP.NET app with no bot-detection to
            # dodge (unlike Tableau, which is why the other modules pay that
            # price).
            args=["--window-size=1500,1000", "--window-position=0,0",
                  # The profile is ours and empty of any human's Google
                  # account, but sync stays off on principle -- these tabs
                  # must never turn up on somebody's other devices.
                  "--disable-sync", "--no-first-run",
                      "--no-default-browser-check", "--disable-infobars"])
        except Exception as e:  # noqa: BLE001
            self._pw.stop()
            self._pw = None
            if "existing browser session" in str(e):
                # One profile, one browser. A second run adopts the first one's
                # window instead of getting its own, and then drives a page
                # nobody is looking at. Say which run is in the way rather than
                # printing thirty lines of patchright stack.
                raise ProfileInUse(
                    "Another run of this report already has the Apex window "
                    "open (the browser profile can only be used once at a "
                    "time). Stop that run with Ctrl+C and close its window, "
                    "then start this one again. Nothing was typed.")
            raise
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.goto(ROSTER_URL, wait_until="domcontentloaded", timeout=60000)
        self.page.wait_for_timeout(2500)
        return self

    def __exit__(self, *exc):
        # Closed gracefully so Chrome writes what it can. The session cookie is
        # non-persistent either way; the remembered-device one is not, and that
        # is the part worth keeping.
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
        return False

    def on_signin_step(self) -> str:
        """Which sign-in screen is showing, for a log line that helps."""
        url = (self.page.url or "").lower()
        for tag, name in (("account/login", "the password page"),
                          ("sendcode", "the 2FA code page"),
                          ("verifycode", "the 2FA code page"),
                          ("changepassword", "the change-password page")):
            if tag in url:
                return name
        return "the sign-in" if _AUTH_PATH.search(url) else ""

    def password_gate(self) -> bool:
        """Is Apex holding this session behind a forced password change?

        Checked by URL: the modal on that page can be dismissed, but every
        navigation lands straight back on it, so a closed modal is not
        progress. Seen on a STALE copied session -- a freshly signed-in one
        has never shown it.
        """
        return "changepassword" in (self.page.url or "").lower()

    def signed_in(self) -> bool:
        """On a real Apex page -- not anywhere in the sign-in flow.

        This used to look only for the LOGIN url, and a live run walked
        straight past a half-finished sign-in: Apex was sitting on
        /Identity/Account/SendCode (the 2FA code screen, ReturnUrl=/roster) and
        this called it signed in, then went hunting for an 'Add Employee'
        button on a page that has never had one.

        So the test is inverted: the sign-in screens are named, and being
        signed in means being somewhere that isn't one of them.

        And they are served under TWO prefixes, which caught this a second
        time. The password page is /Identity/Account/Login, but after it Apex
        sent the 2FA step to a bare /Account/SendCode -- no /Identity -- and a
        check written for the first spelling waved it straight through.
        """
        url = (self.page.url or "").lower()
        if "herbjoyent.com" not in url:
            return False
        return not _AUTH_PATH.search(url)

    def require_login(self) -> None:
        """Wait for a human to sign in, however long the 2FA takes.

        No password is typed here and none is read. If nobody is at the
        keyboard this raises instead of hanging a scheduled job forever.
        """
        if self.signed_in():
            self.log(f"Apex is signed in — {self.page.url}")
            return
        if self.password_gate():
            raise PasswordChangeRequired(
                "Apex is holding this session behind 'change your password "
                "before you continue'. That is the account's own state and "
                "only its owner can clear it — this automation never sets a "
                "password.")
        # No tty is NOT a reason to refuse. The wait is already bounded by
        # login_timeout_s, and the person who needs to sign in is looking at
        # the window, not at whichever shell launched it -- refusing outright
        # meant the run died instantly when driven from anywhere but a
        # terminal, which is most of the ways it actually gets started.
        if not _interactive():
            self.log("  (no terminal here — waiting for the sign-in anyway, "
                     f"up to {self.login_timeout_s // 60} minutes)")
        self.log("")
        self.log("  Apex wants a sign-in. The window is open — sign in there.")
        self.log("  Nothing is typed for you and no password is read; this")
        self.log("  waits until the ROSTER loads — through the 2FA code too,")
        self.log("  so take as long as you need.")
        deadline = time.time() + self.login_timeout_s
        said = ""
        while time.time() < deadline:
            self.page.wait_for_timeout(2000)
            step = self.on_signin_step()
            if step and step != said:
                self.log(f"  ...waiting — you're on {step}")
                said = step
            if self.password_gate():
                raise PasswordChangeRequired(
                    "Apex is asking for a password change before it will let "
                    "anyone in. Clear that in Apex, then run this again.")
            if self.signed_in() and "herbjoyent" in (self.page.url or ""):
                self.log(f"  signed in — {self.page.url}")
                return
        raise NotLoggedIn(
            f"Nobody signed in within {self.login_timeout_s // 60} minutes. "
            "Nothing was typed.")


class NotLoggedIn(RuntimeError):
    pass


class ProfileInUse(RuntimeError):
    """A second run tried to open a browser the first one already has."""


class PasswordChangeRequired(RuntimeError):
    """Apex is signed in but won't let anyone past until the password is
    changed. A different problem from being logged out, and it has to say so:
    apex_payroll's login test sees the password boxes on that screen and calls
    it a login page, which sends whoever is running this off to sign in again
    -- something they have already done and which will not help.

    Nobody but the account holder can clear this. This automation does not set
    passwords, so it stops here every time and names the screen.
    """


# ------------------------------------------------------------- field finding

# Label matching runs in TWO passes: exact first, then substring. Stage two
# forced this. 'Street Address' and 'Street Address 2' sit one above the other,
# so a substring match on 'street address' hits both, reads as ambiguous, and
# fills neither -- while an exact match on the label's text (asterisk and
# padding stripped) lands on exactly one. The substring pass is still there
# underneath for labels we only half know.
_FIND_JS = r"""(args) => {
  const labels = args.labels, exact = args.exact;
  const out = [];
  const seen = new Set();
  const vis = el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const push = (el, how, text) => {
    if (!el || seen.has(el)) return;
    seen.add(el);
    out.push({how, text, tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type') || '',
              name: el.getAttribute('name') || '',
              id: el.id || '', visible: vis(el),
              readonly: el.hasAttribute('readonly') || el.disabled === true});
  };
  const norm = t => t.replace(/\*/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  const hit = t => exact ? labels.some(l => norm(t) === l)
                         : labels.some(l => norm(t).includes(l));
  for (const el of document.querySelectorAll('label')) {
    const t = (el.innerText || '').trim().toLowerCase();
    if (!t) continue;
    if (!hit(t)) continue;
    let f = el.htmlFor ? document.getElementById(el.htmlFor) : null;
    if (!f) f = el.querySelector('input,select,textarea');
    if (!f) {                       // label above/beside its box
      let n = el.nextElementSibling;
      for (let i = 0; i < 3 && n; i++, n = n.nextElementSibling) {
        const c = n.matches('input,select,textarea') ? n
                : n.querySelector('input,select,textarea');
        if (c) { f = c; break; }
      }
    }
    if (f) push(f, 'label', t);
  }
  if (!exact) {
    for (const el of document.querySelectorAll('input,select,textarea')) {
      const attrs = [el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                     el.getAttribute('name'), el.id].filter(Boolean)
                    .join(' ').toLowerCase();
      if (labels.some(l => attrs.includes(l.replace(/ /g, '')) || attrs.includes(l)))
        push(el, 'attr', attrs.slice(0, 60));
    }
  }
  return out;
}"""


# Input types that can never hold one of our values. A checkbox is not where a
# name goes, and excluding them is not just tidiness: on the real Add Employee
# screen the label 'Send this user a password reset to their Account Email'
# CONTAINS the words 'Account Email', so the account-email lookup matched both
# that checkbox and the actual box, called it ambiguous, and refused to fill a
# required field. Dropping non-text controls leaves exactly one answer -- and
# keeps that checkbox, which mails a real new hire, permanently out of reach.
NON_TEXT_TYPES = {"checkbox", "radio", "button", "submit", "reset", "hidden",
                  "file", "image"}


def _evaluate(page, script, arg):
    """page.evaluate, but a navigation mid-call is retried instead of fatal.

    Apex redirects while these lookups run -- an unfinished sign-in bounces
    every page -- and 'Execution context was destroyed' took down a whole run
    of 24 people at person one. A destroyed context means the page moved, so
    the answer is to let it settle and ask again, once.
    """
    try:
        return page.evaluate(script, arg)
    except Exception as e:  # noqa: BLE001
        if "context was destroyed" not in str(e).lower():
            raise
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1500)
        return page.evaluate(script, arg)


def find_field(page, semantic: str) -> Optional[dict]:
    """The one input that means `semantic`, or None if it isn't unambiguous.

    Ambiguity is a refusal, not a coin toss. 'Address' matching both 'Address 1'
    and 'Address 2' means we do not know which is which, so nothing is typed and
    the caller reports it -- the alternative is putting a home address in an
    apartment box on somebody's payroll record.
    """
    for exact in (True, False):
        for label in LABELS.get(semantic, ()):
            hits = [h for h in _evaluate(
                        page, _FIND_JS, {"labels": [label], "exact": exact})
                    if h["visible"] and not h["readonly"]
                    and not (h["tag"] == "input"
                             and (h["type"] or "").lower() in NON_TEXT_TYPES)]
            # A more specific later label ('address 2') can also match an
            # earlier broad one; take the first wording landing on ONE box.
            if len(hits) == 1:
                hit = dict(hits[0])
                hit["semantic"] = semantic
                hit["matched_label"] = label
                hit["exact"] = exact
                return hit
    return None


def _selector(hit: dict) -> str:
    if hit.get("id"):
        return f"#{hit['id']}"
    if hit.get("name"):
        return f"{hit['tag']}[name=\"{hit['name']}\"]"
    raise RuntimeError(f"Apex field {hit.get('semantic')} has neither an id nor "
                       "a name attribute — can't address it safely.")


def plan_fill(page, values: Dict[str, str]) -> tuple:
    """(matched, unmatched) without typing a thing.

    `matched` is [(semantic, value, hit)]; `unmatched` is [(semantic, why)].
    This is what --preview prints and what --live types, so what you approve is
    exactly what happens.
    """
    matched, unmatched = [], []
    for semantic, value in values.items():
        if any(bad in semantic for bad in NEVER_TYPE):
            unmatched.append((semantic, "never auto-typed — enter by hand"))
            continue
        hit = find_field(page, semantic)
        if not hit:
            unmatched.append((semantic, "no field on this screen matched "
                                        f"{'/'.join(LABELS.get(semantic, ()))}"))
            continue
        matched.append((semantic, value, hit))
    return matched, unmatched


def _option_like(page, sel: str, want: str) -> Optional[str]:
    """The dropdown option that means `want`, or None.

    Exact first, then a looser match, because the wording we carry and the
    wording Apex shows are written by different people. The filing statuses are
    the live case: the W-4 says 'Married filing jointly or Qualifying surviving
    spouse' and Apex's list may just say 'Married filing jointly'.

    Returning None is the important half. Handing a select a value it does not
    have selects NOTHING, silently -- the bug that would have left every state
    blank until 'TX' was turned into 'Texas'. A miss here is reported instead.
    """
    options = page.locator(f"{sel} option").all_text_contents()
    def fold(t):
        return " ".join(str(t or "").split()).strip().lower()
    w = fold(want)
    for opt in options:
        if fold(opt) == w:
            return opt.strip()
    for opt in options:
        o = fold(opt)
        if o and (o.startswith(w) or w.startswith(o)):
            return opt.strip()
    for opt in options:
        o = fold(opt)
        if o and (o in w or w in o):
            return opt.strip()
    return None


def apply_fill(page, matched: List[tuple], log=print) -> tuple:
    """Type the approved values. Returns (filled, problems).

    Nothing is submitted here -- saving is the caller's explicit step, so a bad
    match is still recoverable on screen. A dropdown with no matching option is
    left alone and reported rather than silently staying on 'Select'.
    """
    done, problems = 0, []
    for semantic, value, hit in matched:
        sel = _selector(hit)
        el = page.locator(sel).first
        if hit["tag"] == "select":
            option = _option_like(page, sel, value)
            if option is None:
                problems.append(
                    (semantic, f"{value!r} isn't one of the options on "
                               f"{hit['matched_label']!r} — left unset"))
                continue
            el.select_option(label=option, timeout=8000)
            log(f"    {semantic:9} -> {hit['matched_label']!r} = {option!r}")
        else:
            el.fill("", timeout=8000)
            el.type(value, delay=25)
            log(f"    {semantic:9} -> {hit['matched_label']!r} ({sel})")
        done += 1
    return done, problems


# The Social's boxes, looked up SEPARATELY from LABELS on purpose. Keeping them
# out of LABELS means plan_fill -- the path every ordinary value travels -- has
# no way to reach them even by accident; the only thing that can put a number
# here is `fill_ssn`, which takes a Secret a person typed.
#
# CONFIRMED off the real screen (2026-09-05, /employees/<id>/edit/bank-info).
# There are TWO boxes, not one: the page shows the existing number masked
# ('***-**-7663') and then asks for 'Change SSN' and 'Confirm SSN'. Filling one
# and not the other saves nothing, so this fills both or neither.
# W-4 Step 1(c), all three boxes, settled 2026-09-09. Exactly one is ticked on
# every one of 30 signed packets, so the keys were certain from the data -- but
# WHICH was which was not, and the two available signals disagreed. By placement
# order chk004 looked like Married Filing Jointly; by dependents it looked like
# Head of Household (2 of 2 of its people claimed dependents, against 1 of 4 of
# 6471's). Megan opened the two forms and the DEPENDENTS signal was right:
# Ashari Evans (chk004) is Head of household, Michael Moore (6471) is Married
# filing jointly. Placement order would have swapped them onto a real tax
# record, which is why neither was guessed.
MARITAL_BY_FLAG = {
    "filing_single": "Single or Married filing separately",
    "filing_mfj": "Married filing jointly or Qualifying surviving spouse",
    "filing_hoh": "Head of household",
}
MARITAL_SINGLE = MARITAL_BY_FLAG["filing_single"]

SSN_CHANGE_LABELS = ("change ssn", "social security number", "ssn")
SSN_CONFIRM_LABELS = ("confirm ssn", "confirm social security number")

# The Social lives on the employee's third tab. Its URL is the record's own with
# /edit/bank-info on the end, which is how the run gets there without hunting
# for a tab by name.
BANK_INFO_SUFFIX = "/edit/bank-info"


def _one_field(page, labels):
    """The single visible box matching any of `labels`, or None."""
    for exact in (True, False):
        for label in labels:
            hits = [h for h in _evaluate(
                        page, _FIND_JS, {"labels": [label], "exact": exact})
                    if h["visible"] and not h["readonly"]
                    and not (h["tag"] == "input"
                             and (h["type"] or "").lower() in NON_TEXT_TYPES)]
            if len(hits) == 1:
                hit = dict(hits[0])
                hit["matched_label"] = label
                return hit
    return None


def fill_ssn(page, secret) -> bool:
    """Type ONE Social into BOTH boxes, from a Secret the operator typed.

    All-or-nothing: if either box is missing, nothing is typed anywhere. A
    Social in 'Change SSN' with 'Confirm SSN' left empty does not save, and a
    Social typed into some other box on a payroll page is worse than a failure
    that says so.

    The value is revealed for exactly as long as it takes to type it, and it is
    never returned, logged or stored.
    """
    change = _one_field(page, SSN_CHANGE_LABELS)
    confirm = _one_field(page, SSN_CONFIRM_LABELS)
    if not change or not confirm or change["id"] == confirm["id"]:
        return False
    for hit in (change, confirm):
        el = page.locator(_selector(hit)).first
        el.fill("", timeout=8000)
        el.type(secret.reveal(), delay=20)
    return True


def set_security_role(page, role: str = SECURITY_ROLE) -> bool:
    """Tick the Security Roles radio whose label reads exactly `role`.

    Returns False and clicks NOTHING if that label isn't on the page or if more
    than one matches. The wrong radio here is not a typo -- it is somebody
    seeing the whole office's payroll instead of their own.
    """
    hits = page.evaluate("""(want) => {
      const out = [];
      for (const el of document.querySelectorAll('input[type="radio"]')) {
        let text = '';
        const lab = el.closest('label')
          || (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null);
        if (lab) text = (lab.innerText || '').trim();
        if (text.toLowerCase() === want.toLowerCase())
          out.push({id: el.id || '', name: el.getAttribute('name') || '', text});
      }
      return out;
    }""", role)
    if len(hits) != 1:
        return False
    hit = hits[0]
    sel = f"#{hit['id']}" if hit["id"] else f'input[type="radio"][name="{hit["name"]}"]'
    page.locator(sel).first.check(timeout=8000)
    return True


# ---------------------------------------------------------------- explore

def explore(session: "ApexSession") -> dict:
    """Inventory the screen that is open, and save it.

    Read-only. Run it once on a logged-in machine with the Add Employee form
    open and `apex_screen.json` turns every guess in LABELS into a fact -- and
    tells you the exact wording for anything that didn't match.
    """
    page = session.page
    inv = page.evaluate("""() => {
      const f = [];
      for (const el of document.querySelectorAll('input,select,textarea')) {
        const r = el.getBoundingClientRect();
        let lab = '';
        if (el.id) {
          const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (l) lab = (l.innerText || '').trim();
        }
        f.push({tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
                name: el.getAttribute('name') || '', id: el.id || '',
                placeholder: el.getAttribute('placeholder') || '',
                aria: el.getAttribute('aria-label') || '', label: lab,
                visible: r.width > 0 && r.height > 0});
      }
      return {url: location.href, title: document.title, fields: f};
    }""")
    resolved = {}
    for semantic in LABELS:
        hit = find_field(page, semantic)
        resolved[semantic] = (f"{hit['matched_label']} -> "
                              f"{hit.get('id') or hit.get('name')}") if hit else None
    inv["resolved"] = resolved
    SCREEN_PATH.write_text(json.dumps(inv, indent=2) + "\n")
    return inv
