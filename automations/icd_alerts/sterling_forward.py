"""Forward Sterling's login codes to Lucy -- the SaraPlus code forward, again.

WHY (Megan 2026-11-03). The office admin page's "Send background checks" runs
on the office's own computer, signed in to the ICD's Sterling account, and
Sterling emails a 6-digit code on every new login -- to the ICD's OWN personal
email. Same problem SaraPlus had, so the same answer: the ICD forwards
Sterling's code mails (and nothing else) to the reporting inbox, and Lucy 1
hands the code back (code_answer, service "sterling").

SHORTER THAN SARAPLUS'S, BECAUSE MOST OF IT IS ALREADY DONE. Gmail's
forwarding address (the reporting inbox) is added once per Gmail account; an
ICD who did the SaraPlus forward has it already. So:
  1. which address does Sterling email? (offered: the one SaraPlus uses)
  2. only if Gmail's forward isn't confirmed yet: add the forwarding address
  3. the filter -- from noreply@us.fadv.co, subject "Authentication Request"

THE SUBJECT IS THE POINT. noreply@us.fadv.co also emails every candidate's
background-check RESULT. Those stay in the ICD's inbox; only the login code
mails come to us. code_answer.check_forward_scope(service="sterling") tells
Megan + Eve if results start arriving anyway.

Reuses code_forward's helpers (clipboard, Gmail screens, the confirmation
wait) rather than copying them, so a fix there reaches this too.

    python -m automations.icd_alerts.sterling_forward
"""
from __future__ import annotations

from automations.icd_alerts import code_forward as F

STERLING_SENDER = "noreply@us.fadv.co"
STERLING_SUBJECT = "Authentication Request"
# Gmail's filter box, opened with BOTH boxes filled. from= is what code_forward
# proved on a real inbox (2026-11-02); subject= is the same URL form.
FILTER_URL = ("https://mail.google.com/mail/u/0/#create-filter/from="
              + STERLING_SENDER.replace("@", "%40")
              + "&subject=" + STERLING_SUBJECT.replace(" ", "%20"))

ASK_ADDRESS = ("Lucy can type Sterling's login codes for you, so your office "
               "computer can send background checks by itself, and show your "
               "admin who has passed. Only Sterling's emails get forwarded, to "
               "Lucy's own Sterling inbox. The rest of your inbox stays private.\n\n"
               "Are your Sterling codes emailed to %s?")
ADD_FORWARD = (
    "First, let's let Gmail forward to %s.\n\n"
    "Gmail just opened. Please make sure you're in the %s account (picture at "
    "the top right).\n\n"
    "1. Click Add a forwarding address.\n"
    "2. PASTE into the box (hold Command and tap V). We already copied it.\n"
    "3. Click Next, Proceed, then OK.\n\n"
    "Leave \"Disable forwarding\" selected -- \"Forward a copy of incoming "
    "mail\" would send your whole inbox.\n\n"
    "Click OK here when you're done.")
FILTER_STEPS = (
    "Last step! Gmail just opened a box with Sterling's address and the subject "
    "\"%s\" already filled in.\n\n"
    "Please check BOTH are there -- the subject is what keeps your background "
    "check results private.\n\n"
    "1. Click Create filter.\n"
    "2. Check Forward it to.\n"
    "3. Pick %s.\n"
    "4. Click Create filter again.\n\n"
    "Click OK here when you're done." % (STERLING_SUBJECT, F.REPORTING_INBOX))


# --- the RESULTS forward (Megan 2026-11-08) ---------------------------------
# Sterling's background-check RESULT mails -> their own inbox, never the
# reporting one, so the office admin's "Next week's starts" shows each
# person's BG status. Everything from Sterling EXCEPT the login codes: those
# keep going to the reporting inbox through the filter above.
RESULTS_INBOX = "lucysterlingreports@gmail.com"
RESULTS_FILTER_URL = ("https://mail.google.com/mail/u/0/#create-filter/from="
                      + STERLING_SENDER.replace("@", "%40")
                      + "&hasnot=%22" + STERLING_SUBJECT.replace(" ", "%20") + "%22")
ADD_RESULTS_FORWARD = (
    "One more forward: Sterling's background check RESULTS, so your admin can "
    "see who has passed. They go to Lucy's own results inbox, %s, not to the "
    "reporting team.\n\n"
    "Gmail just opened. Please make sure you're in the %s account.\n\n"
    "1. Click Add a forwarding address.\n"
    "2. PASTE into the box (hold Command and tap V). We already copied it.\n"
    "3. Click Next, Proceed, then OK.\n\n"
    "Leave \"Disable forwarding\" selected.\n\n"
    "Click OK here when you're done.")
RESULTS_FILTER_STEPS = (
    "Last filter! Gmail just opened a box with Sterling's address filled in, and "
    "\"Doesn't have\" set to \"%s\" so your login codes are left out.\n\n"
    "1. Click Create filter.\n"
    "2. Check Forward it to.\n"
    "3. Pick %s.\n"
    "4. Click Create filter again.\n\n"
    "Click OK here when you're done." % (STERLING_SUBJECT, RESULTS_INBOX))
RESULTS_WAIT_S = 180


def _wait_for_results(office_key: str, say=print, sleep=None) -> bool:
    """Has Lucy 1 confirmed this office's RESULTS forward? Up to 3 minutes."""
    import time
    from automations.icd_alerts import relay as R
    sleep = sleep or time.sleep
    say("      Checking with Lucy -- this takes up to 3 minutes...")
    deadline = time.time() + RESULTS_WAIT_S
    while True:
        if R.results_forward_confirmed(office_key):
            return True
        if time.time() >= deadline:
            return False
        sleep(F.CONFIRM_POLL_S)


def walk_results(ask, address: str, say=print, office_key: str = "") -> str:
    """The results forward, for the address Sterling mails. Never raises."""
    from automations.icd_alerts import relay as R
    try:
        if not R.report_forward(address, office_key=office_key, service="sterling_results"):
            say("      could not reach the reporting team -- tell them %s" % address)
            return "address not sent"
        if not R.results_forward_confirmed(office_key):
            F._copy(RESULTS_INBOX, say)
            F._open(F.for_account(F.FORWARDING_URL, address), say)
            ask.message(ADD_RESULTS_FORWARD % (RESULTS_INBOX, address))
            if not _wait_for_results(office_key, say, sleep=F.holding(ask)):
                ask.message(F.LEFT_OPEN)
                return "not confirmed yet"
        F._open(F.for_account(RESULTS_FILTER_URL, address), say)
        ask.message(RESULTS_FILTER_STEPS)
        return "done"
    except ask.Cancelled:
        return "skipped for now"
    except Exception as e:  # noqa: BLE001
        say("      could not show the results forward steps: %s" % type(e).__name__)
        return "skipped for now"


def _saraplus_address() -> str:
    """The address this computer's SaraPlus login uses -- usually the same."""
    return F._login_email()


ONE_FILTER_URL = ("https://mail.google.com/mail/u/0/#create-filter/from="
                  + STERLING_SENDER.replace("@", "%40"))
ONE_FILTER_STEPS = (
    "Last step! Gmail just opened a box with Sterling's address "
    "(%s) filled in.\n\n"
    "1. Click Create filter.\n"
    "2. Check Forward it to.\n"
    "3. Pick %s.\n"
    "4. Click Create filter again.\n\n"
    "That sends Lucy your Sterling login codes and background check results "
    "-- and nothing else from your inbox.\n\n"
    "Click OK here when you're done." % (STERLING_SENDER, RESULTS_INBOX))


def walk_through(ask, say=print, office_key: str = "") -> str:
    """ONE forward, ONE filter (Megan 2026-11-09): everything Sterling emails
    -- login codes AND results -- goes to Lucy's own Sterling inbox,
    lucysterlingreports@. Never the reporting inbox. Lucy 1 reads both codes
    and results there (code_answer looks in it first for a Sterling code).
    Returns a word for the summary. Never raises."""
    from automations.icd_alerts import relay as R
    try:
        guess = _saraplus_address()
        if guess:
            pick = ask.choose(ASK_ADDRESS % guess, [F.YES, F.OTHER, F.LATER])
        else:
            pick = F.OTHER
        if pick == F.LATER:
            return "skipped for now"
        address = guess if pick == F.YES else ask.text(
            "The email address Sterling sends your login codes to:").strip()
        if "@" not in address:
            say("      that did not look like an email address -- skipped")
            return "skipped for now"
        # Both tabs on our side: the code tab (whose codes to look for) and the
        # results tab (which office a forwarded result belongs to).
        sent = R.report_forward(address, office_key=office_key, service="sterling")
        sent = R.report_forward(address, office_key=office_key, service="sterling_results") and sent
        if not sent:
            say("      could not reach the reporting team -- tell them %s" % address)
            return "address not sent"
        if not R.results_forward_confirmed(office_key):
            F._copy(RESULTS_INBOX, say)
            F._open(F.for_account(F.FORWARDING_URL, address), say)
            ask.message(ADD_FORWARD % (RESULTS_INBOX, address))
            if not _wait_for_results(office_key, say, sleep=F.holding(ask)):
                ask.message(F.LEFT_OPEN)
                return "not confirmed yet"
        F._open(F.for_account(ONE_FILTER_URL, address), say)
        ask.message(ONE_FILTER_STEPS)
        return "done"
    except ask.Cancelled:
        return "skipped for now"
    except Exception as e:  # noqa: BLE001
        say("      could not show the Sterling forward steps: %s" % type(e).__name__)
        return "skipped for now"


def main(argv=None) -> int:
    from automations.icd_alerts import config as C
    from automations.icd_alerts import dialogs as ask

    def say(m=""):
        print(m, flush=True)

    office_key = str(C.install().get("office_key") or "")
    said = walk_through(ask, say, office_key=office_key)
    say("")
    if said != "done":
        say("  NOT YET -- run this same line again when you are ready.")
        return 1
    say("  ALL SET once that filter is saved. From now on, Lucy types")
    say("  Sterling's login codes for you and sees your results.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
