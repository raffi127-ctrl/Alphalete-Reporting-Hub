"""Set this computer up to send Sterling background checks. Run once, by the ICD.

    python -m automations.icd_alerts.sterling_setup

WHY (Megan 2026-11-04). The office admin presses "Send background checks"
somewhere else; THIS computer signs in to the ICD's own Sterling account and
sends them (sterling_send). Two things only the ICD can give it, both asked
here, once:

  1. their Sterling login (User ID + password) -- saved on THIS computer
     only (config.save_sterling_creds), never sent to us or the relay;
  2. the code forward -- Sterling emails a code on new logins, to the ICD's
     own email, and the Gmail filter sends ONLY those code mails to us
     (sterling_forward).

Then one test sign-in (with the code, if Sterling asks) so the ICD knows it
works while they're still sitting there.
"""
from __future__ import annotations

from automations.icd_alerts import config as C

ASK_USER = ("Lucy can send your office's background checks from this computer.\n\n"
            "Your Sterling (First Advantage) User ID -- the one you sign in with "
            "at sterlingcheck.app. It's often not an email:")
ASK_PASSWORD = "Your Sterling password (saved on this computer only):"


def ask_login(ask, say=print) -> str:
    """Ask for and save the login. Returns a word for the summary."""
    try:
        user = ask.text(ASK_USER).strip()
        if not user:
            return "skipped -- no User ID"
        pwd = ask.password(ASK_PASSWORD)
    except ask.Cancelled:
        return "skipped for now"
    if not pwd:
        return "skipped -- no password"
    C.save_sterling_creds(user, pwd)
    say("      Sterling login saved on this computer.")
    return "saved"


def digi_docs_step(office_key: str, say=print) -> str:
    """The onboarding-documents question (which campaign and bundle THIS
    office's OwnerVille sends a new start), asked HERE and not in the main ECO
    install (Megan, 2026-11-13: "this should also only be on the sterling
    installer right now"). Asked once; an office with its answers saved is
    skipped. Never costs the Sterling setup, and a copy that does not carry
    the step yet shows no error."""
    try:
        from automations.icd_alerts import digi_docs_setup as DD
    except Exception:  # noqa: BLE001 -- not shipped to this office yet
        return "nothing to do yet"
    if not office_key:
        return "not enrolled yet"
    try:
        return DD.ask_office(office_key, log=say)
    except Exception as e:  # noqa: BLE001
        return "left for later (%s)" % type(e).__name__


def blueink_step(say=print) -> str:
    """The office's own Blue Ink account, asked HERE and not in the main ECO
    install (Megan, 2026-11-13: "the main eco installer shouldn't ask for blue
    ink - that's for a sterling/bg enrollment anyways"). Never costs the
    Sterling setup: an office whose copy does not carry the Blue Ink step yet
    is told nothing is needed, not shown an error it cannot act on."""
    try:
        from automations.icd_alerts import blueink_setup as BS
    except Exception:  # noqa: BLE001 -- not shipped to this office yet
        return "nothing to do yet"
    try:
        return BS.run(log=say)
    except Exception as e:  # noqa: BLE001
        return "left for later (%s)" % type(e).__name__


def main(argv=None) -> int:
    from automations.icd_alerts import dialogs as ask
    from automations.icd_alerts import sterling_forward, sterling_send

    def say(m=""):
        print(m, flush=True)

    office_key = str(C.install().get("office_key") or "")
    if not C.sterling_creds() or (argv and "--again" in argv):
        if ask_login(ask, say) != "saved":
            say("  NOT YET -- run this same line again when you're ready.")
            return 1
    fwd = sterling_forward.walk_through(ask, say, office_key=office_key)
    say("      code forward: %s" % fwd)
    say("")
    say("  Testing the sign-in (about a minute)...")
    res = sterling_send.check_login(office_key=office_key, log=say)
    if res.get("ok"):
        say("      Onboarding documents: %s" % digi_docs_step(office_key, say))
        say("      Blue Ink account: %s" % blueink_step(say))
        say("  ALL SET. Your admin can send background checks from now on.")
        if fwd != "done":
            say("  (The forward isn't finished yet -- run this same line again later")
            say("   so your admin can also see who has passed.)")
        return 0
    say("  The sign-in didn't finish: %s" % res.get("error"))
    say("  Run this same line again, or tell the reporting team.")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
