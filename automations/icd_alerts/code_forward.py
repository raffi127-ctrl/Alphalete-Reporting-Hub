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
and by finish_setup when this machine has hit it since.

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
    "code emails (from %s) to %s.\n\n"
    "1. Gmail gear -> See all settings -> Forwarding and POP/IMAP -> Add a "
    "forwarding address -> %s. The reporting team confirms it on their side.\n"
    "2. Then search from:%s -> sliders icon -> Create filter -> Forward it to "
    "that address." % (SARAPLUS_SENDER, REPORTING_INBOX, REPORTING_INBOX,
                       SARAPLUS_SENDER))

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


def _mark(address: str) -> None:
    try:
        MARK_PATH.parent.mkdir(parents=True, exist_ok=True)
        MARK_PATH.write_text("%s %s\n" % (dt.datetime.now().isoformat(timespec="seconds"),
                                          address))
    except OSError:
        pass


def walk_through(ask, say=print, office_key: str = "") -> str:
    """Show the steps, ask which address SaraPlus mails, send it home.

    Returns a word for the setup summary. Never raises: this is a courtesy on
    top of a working install, not a condition of one.
    """
    from automations.icd_alerts import relay as R

    try:
        ask.message(STEPS)
        login = _login_email()
        if login:
            pick = ask.choose("Are your SaraPlus codes emailed to %s?" % login,
                              [YES, OTHER, LATER])
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
    say("      Thanks -- the reporting team will confirm the forward.")
    return "done"
