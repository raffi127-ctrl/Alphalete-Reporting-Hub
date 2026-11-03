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

DONE MEANS GMAIL SAID SO (Eve 2026-11-03). Pressing OK used to mark this computer
as set up, whether or not anything had happened in Gmail. Isaiah, Jamis and Trang
all pressed it with no confirmation mail ever reaching us: the owner was told
"Thanks", the offer never came back, and the line went straight to a filter
screen that could not list our address. Now the mark is written only after Lucy 1
has confirmed the forward and the filter step has been shown. The mark has a NEW
FILE NAME so that the old premature ones (sara-code-forward.txt) count for nothing,
which is what brings those offices back at their next hand sign-in.
"""
from __future__ import annotations

import datetime as dt
import time

from automations.icd_alerts import config as C

REPORTING_INBOX = "alphaletereporting@gmail.com"
SARAPLUS_SENDER = "security.info@saraplus.com"
MARK_PATH = C.APP_DIR / "sara-code-forward-done.txt"

STEPS = (
    "So nobody has to type SaraPlus codes for Lucy again, forward SaraPlus's "
    "code emails to %s.\n\n"
    "Gmail just opened. Check the account picture at the top right: it has to "
    "be %s. If it is not, switch to that account first.\n\n"
    "Our address is already copied, so don't type anything. On the forwarding "
    "settings: click Add a forwarding address -> in the box, "
    "PASTE (hold Command and tap V) -> Next -> Proceed. Lucy confirms it on our "
    "side.\n\n"
    "Then leave \"Disable forwarding\" selected. Do NOT pick \"Forward a copy "
    "of incoming mail\": that sends your whole inbox. We only want SaraPlus's "
    "code emails, and the next step's filter takes care of that.\n\n"
    "Click OK only after you have done this in Gmail.")

OFFER = ("One last step, about 2 minutes, one time: this lets Lucy enter "
         "SaraPlus's codes herself from now on. Only SaraPlus's code emails get "
         "forwarded to us, nothing else in your inbox.")
WAIT_FOR_CONFIRM = ("Click OK, then leave this computer open for up to 3 minutes. "
                    "Lucy is checking with Gmail, and the last step opens by "
                    "itself.")
NOT_ARRIVED = (
    "Gmail has not told us about it yet, so it did not go through.\n\n"
    "Gmail just opened again. Check that:\n"
    "1. The account at the top right is %s\n"
    "2. Under Forwarding, you clicked Add a forwarding address, pasted %s, then "
    "Next and Proceed.\n\n"
    "Click OK when that is done.")
LEFT_OPEN = ("Your sign-in worked and Lucy is running. This last step is not "
             "finished yet, so you'll see it again the next time SaraPlus asks "
             "for a code.")
FORWARD_PAGE = ("https://raffi127-ctrl.github.io/Alphalete-Reporting-Hub/"
                "sara-forward.html")

CONFIRM_WAIT_S = 180
CONFIRM_POLL_S = 15
TRIES = 2

YES = "Yes, that one"
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


def _wait_for_gmail(office_key: str, say=print, sleep=time.sleep,
                    clock=time.time) -> bool:
    """Has Lucy 1 confirmed this office's forward? Asks for CONFIRM_WAIT_S."""
    from automations.icd_alerts import relay as R
    say("      Checking with Lucy -- this takes up to 3 minutes...")
    deadline = clock() + CONFIRM_WAIT_S
    while True:
        if R.forward_confirmed(office_key):
            return True
        if clock() >= deadline:
            return False
        sleep(CONFIRM_POLL_S)


def _finish(ask, say=print) -> str:
    """The forward is confirmed: the filter is all that is left."""
    if not open_filter(ask, say):
        return "filter not shown"
    _mark(REPORTING_INBOX)
    return "done"


def walk_through(ask, say=print, office_key: str = "", can_skip: bool = True) -> str:
    """Ask which address SaraPlus mails, show the steps, send it home, and do
    not call it done until Gmail has confirmed it.

    Returns a word for the setup summary. Never raises: this is a courtesy on
    top of a working install, not a condition of one.

    can_skip=False takes the skip buttons away, for the owner who just typed a
    code by hand (offer_after_signin).
    """
    from automations.icd_alerts import relay as R

    # ALREADY CONFIRMED (the address was added before, or one of us clicked the
    # mail): the only thing left is the filter, so nobody redoes step 1.
    if R.forward_confirmed(office_key):
        return _finish(ask, say)
    try:
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
        if "@" not in address:
            say("      that did not look like an email address -- skipped")
            return "skipped for now"
        # GMAIL OPENS ON THE RIGHT SCREEN (Megan 2026-10-29), now AFTER the
        # address, so the steps can name the account to be in: /u/0 is whichever
        # account this browser calls its first, not necessarily that one.
        _copy(REPORTING_INBOX, say)
        _open(FORWARDING_URL, say)
        ask.message(STEPS % (REPORTING_INBOX, address))
        if not R.report_forward(address, office_key=office_key):
            say("      could not reach the reporting team -- tell them %s" % address)
            return "address not sent"
        ask.message(WAIT_FOR_CONFIRM)
        for attempt in range(TRIES):
            if _wait_for_gmail(office_key, say):
                return _finish(ask, say)
            if attempt + 1 < TRIES:
                _copy(REPORTING_INBOX, say)
                _open(FORWARDING_URL, say)
                ask.message(NOT_ARRIVED % (address, REPORTING_INBOX))
        ask.message(LEFT_OPEN)
        return "not confirmed yet"
    except ask.Cancelled:
        return "skipped for now"
    except Exception as e:  # noqa: BLE001
        say("      could not show the code-forward steps: %s" % type(e).__name__)
        return "skipped for now"


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
# it home, waits for the confirmation, opens the filter. Stopped halfway, the SAME
# line picks up from wherever Gmail says it is.
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


def open_filter(ask, say=print) -> bool:
    """True once the owner has been through the filter step's dialog."""
    _open(FILTER_URL, say)
    try:
        ask.message(FILTER_STEPS)
        return True
    except Exception:  # noqa: BLE001 -- includes the dialog being cancelled
        say("  " + FILTER_STEPS)
        return False


def main(argv=None) -> int:
    from automations.icd_alerts import dialogs as ask

    def say(m=""):
        print(m, flush=True)

    if already_set_up():
        open_filter(ask, say)
        said = "done"
    else:
        said = walk_through(ask, say)
    say("")
    if said != "done":
        say("  NOT YET -- run this same line again when you are ready.")
        return 1
    say("  ALL SET once that filter is saved. Lucy enters SaraPlus's codes")
    say("  herself from now on.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
