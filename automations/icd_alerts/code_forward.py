"""Set up the SaraPlus code forward with the owner, during setup.

WHY (Megan 2026-10-29: "We should build this into the installer to do it with
them on the Zoom if possible"). Lucy can type SaraPlus's emailed code herself
(sara_code + code_answer) -- but only for an office that forwards those code
mails to the reporting inbox, and whose address is on the 'SaraPlus Code Mail'
tab. Asking for that afterwards meant a message to every owner. The moment
SaraPlus first asks THIS computer for a code is the moment the owner is sitting
there with us, so that is when it is asked.

ONLY WHERE SARAPLUS WANTS A CODE. Most accounts sign in without one; they are
never shown this. It is offered by setup when the check hits the code screen,
by finish_setup when this machine has hit it since, and at the end of the
sara-signin line (offer_after_signin): the owner who just typed a code by hand
is the one person sitting at this computer who wants this.

ONLY SARAPLUS'S CODE MAILS, NEVER THE INBOX (Eve 2026-11-02). Gmail's forwarding
screen has a second switch, "Forward a copy of incoming mail", that would send
the owner's whole inbox to ours -- the steps say so in as many words, because
adding the address is on that same screen. The filter is the only thing that
forwards. code_answer.check_forward_scope watches for it going wrong anyway.

THE ADDRESS GOES HOME DELIBERATELY. relay.report_fault scrubs every email
address out of a fault, as it should. This is the one message whose whole point
is an address the owner typed for us, so it is sent with relay.report_forward,
which says so. It lands on the private ICD Faults tab and code_answer (Lucy 1)
moves it onto 'SaraPlus Code Mail' -- never the repo, which is public.
"""
from __future__ import annotations

import datetime as dt

from automations.icd_alerts import config as C

REPORTING_INBOX = "alphaletereporting@gmail.com"
SARAPLUS_SENDER = "security.info@saraplus.com"
MARK_PATH = C.APP_DIR / "sara-code-forward.txt"

STEPS = (
    "So nobody has to type SaraPlus codes for Lucy again, forward SaraPlus's "
    "code emails to %s.\n\n"
    "Our address is already copied, so don't type anything. Gmail just opened "
    "on its forwarding settings: click Add a forwarding address -> in the box, "
    "PASTE (hold Command and tap V) -> Next -> Proceed. Lucy confirms it on our "
    "side.\n\n"
    "Then leave \"Disable forwarding\" selected. Do NOT pick \"Forward a copy "
    "of incoming mail\": that sends your whole inbox. We only want SaraPlus's "
    "code emails, and the next step's filter takes care of that.\n\n"
    "Click OK only after you have done this in Gmail."
    % REPORTING_INBOX)

OFFER = ("One last step, about 2 minutes, one time: this lets Lucy enter "
         "SaraPlus's codes herself from now on. Only SaraPlus's code emails get "
         "forwarded to us, nothing else in your inbox.")
WAIT_FOR_CONFIRM = ("Lucy is confirming it now. Wait about 2 minutes, then click "
                    "OK for the last step.")
FORWARD_PAGE = ("https://raffi127-ctrl.github.io/Alphalete-Reporting-Hub/"
                "sara-forward.html")

YES = "Yes, that one"
FILTER_NOW = "Open the filter step"
FILTER_LATER = "Later"
OTHER = "No, a different address"
LATER = "Skip for now"


def already_set_up() -> bool:
    return MARK_PATH.exists()


def _login_email() -> str:
    try:
        return str(C.creds().get("email") or "").strip()
    except Exception:  # noqa: BLE001 -- no login saved yet
        return ""


def _copy(text: str, say=print) -> None:
    """Put our address on the clipboard. THE DIALOG THAT SHOWS IT CLOSES ON OK,
    and its text can't be relied on to copy, so an owner who reached Gmail's box
    had to have memorized it (Eve 2026-11-02). Never raises: the steps name it."""
    import subprocess
    import sys
    tool = "clip" if sys.platform == "win32" else "pbcopy"
    try:
        subprocess.run([tool], input=text.encode("utf-8"), timeout=5, check=True)
    except Exception:  # noqa: BLE001
        say("      our address is %s" % text)


def _mark(address: str) -> None:
    try:
        MARK_PATH.parent.mkdir(parents=True, exist_ok=True)
        MARK_PATH.write_text("%s %s\n" % (dt.datetime.now().isoformat(timespec="seconds"),
                                          address))
    except OSError:
        pass


def walk_through(ask, say=print, office_key: str = "", can_skip: bool = True) -> str:
    """Show the steps, ask which address SaraPlus mails, send it home.

    Returns a word for the setup summary. Never raises: this is a courtesy on
    top of a working install, not a condition of one.

    can_skip=False takes the skip buttons away, for the owner who just typed a
    code by hand (offer_after_signin).
    """
    from automations.icd_alerts import relay as R

    # GMAIL OPENS ON THE RIGHT SCREEN FIRST (Megan 2026-10-29: "the other
    # option here too") -- the same thing the sara-forward line does, so the
    # Zoom and the link are one flow, not two sets of directions.
    _copy(REPORTING_INBOX, say)
    _open(FORWARDING_URL, say)
    try:
        ask.message(STEPS)
        login = _login_email()
        if login:
            pick = ask.choose("Are your SaraPlus codes emailed to %s?" % login,
                              [YES, OTHER] + ([LATER] if can_skip else []))
        else:
            pick = OTHER
        if pick == LATER:
            return "skipped for now"
        address = login if pick == YES else ask.text(
            "The email address SaraPlus sends your codes to:").strip()
    except ask.Cancelled:
        return "skipped for now"
    except Exception as e:  # noqa: BLE001
        say("      could not show the code-forward steps: %s" % type(e).__name__)
        return "skipped for now"
    if "@" not in address:
        say("      that did not look like an email address -- skipped")
        return "skipped for now"
    if not R.report_forward(address, office_key=office_key):
        say("      could not reach the reporting team -- tell them %s" % address)
        return "address not sent"
    _mark(address)
    say("      Thanks -- Lucy will confirm the forward in about 2 minutes.")
    # ON THE ZOOM WE CONFIRM WHILE THEY WAIT, so the filter can be done right
    # here instead of on a second run of the sara-forward line.
    if not can_skip:
        ask.message(WAIT_FOR_CONFIRM)
        open_filter(ask, say)
        return "done"
    try:
        if ask.choose("Wait about 2 minutes while Lucy confirms it, then:",
                      [FILTER_NOW, FILTER_LATER]) == FILTER_NOW:
            open_filter(ask, say)
            return "done"
    except Exception:  # noqa: BLE001 -- the sara-forward line does it later
        pass
    say("      The filter is left -- finish it here: %s" % FORWARD_PAGE)
    return "done"


def offer_after_signin(ask=None, say=print) -> str:
    """Offered once SaraPlus has let this computer in, by hand. Never raises:
    the sign-in already worked, and nothing here may read as if it had not.

    Not for an office whose codes come by text (sms_code): a mail forward does
    nothing for those, and they have their own road.

    NO "NOT NOW" (Eve 2026-11-02). Nobody finished the forward when it was
    optional, and every office left out keeps getting asked for codes by hand.
    The dialogs' own Cancel still exists; whoever uses it gets this again on
    the next hand sign-in.
    """
    try:
        from automations.icd_alerts import sms_code as T
        office_key = str(C.install().get("office_key") or "")
        if already_set_up() or T.wants_text(office_key):
            return "not asked"
        if ask is None:
            from automations.icd_alerts import dialogs as ask
        ask.message(OFFER)
        return walk_through(ask, say, can_skip=False)
    except Exception as e:  # noqa: BLE001 -- includes the dialog being cancelled
        say("      code forwarding skipped: %s" % type(e).__name__)
        return "skipped"


# --- the one line an office pastes (docs/sara-forward.html) -----------------
# Megan 2026-10-29: "a code they can just run in their terminal", like the
# sara-signin page. Gmail will not let a script turn forwarding on for a
# personal account, so this does everything around the two clicks that only
# the owner can make: opens Gmail on the right screen, asks the address, sends
# it home. The SAME line, run again after we confirm, opens the filter screen.
FORWARDING_URL = "https://mail.google.com/mail/u/0/#settings/fwdandpop"
# #create-filter opens Gmail's filter box with SaraPlus's address already in it
# (opened by hand on a real inbox, 2026-11-02), so nobody hunts for the icon.
FILTER_URL = ("https://mail.google.com/mail/u/0/#create-filter/from="
              + SARAPLUS_SENDER.replace("@", "%40"))

FILTER_STEPS = (
    "Last step. Gmail just opened a box with %s already filled in.\n\n"
    "Click Create filter -> check Forward it to -> pick %s -> Create filter.\n\n"
    "Only emails from that address get forwarded. If our address is not in the "
    "list yet, wait a minute and reload the page."
    % (SARAPLUS_SENDER, REPORTING_INBOX))


def _open(url: str, say=print) -> None:
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 -- the steps say where to go anyway
        say("      open %s" % url)


def open_filter(ask, say=print) -> None:
    _open(FILTER_URL, say)
    try:
        ask.message(FILTER_STEPS)
    except Exception:  # noqa: BLE001
        say("  " + FILTER_STEPS)


def main(argv=None) -> int:
    from automations.icd_alerts import dialogs as ask

    def say(m=""):
        print(m, flush=True)

    if not already_set_up():
        said = walk_through(ask, say)
        if said != "done":
            say("")
            say("  NOT YET -- run this same line again when you are ready.")
            return 1
        say("")
        say("  STEP 1 DONE. If the filter is not saved yet: wait about 2 minutes")
        say("  and run this same line once more.")
        return 0
    open_filter(ask, say)
    say("")
    say("  ALL SET once that filter is saved. Lucy enters SaraPlus's codes")
    say("  herself from now on.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
