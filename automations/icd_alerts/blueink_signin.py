"""Ask the OWNER, at their own computer, to sign in to Blue Ink again.

WHY THIS EXISTS. Blue Ink's sign-in lasts about a fortnight and then the send
stops. That expiry is deliberate and stays: Blue Ink is Google SSO, this repo
is public, and the session can send contracts that cannot be recalled -- so
nothing here types a password and a person signs in by hand
(blueink_docs/session.py). Sending cannot go round it with the API key: on
this plan an API bundle bills as a Bulk Envelope, 50 a year and spent, and
both API routes were tried and refused. The web app's Envelopes bucket is
unlimited, which is why the send drives the same screens a person does.

WHAT WAS MISSING. With one shared account, a dead session was one post in
#claudecorrections-and-requests naming Lucy 2 and a python command -- fine for
us. On an ICD's own machine the person who can fix it is the OWNER: not in
that channel, and never going to run a module path. Nothing would reach them,
and the first anyone knew would be a new start with no paperwork on their
first morning.

So this is the OwnerVille copy (icd_alerts/ov_signin.py), for Blue Ink: a
window on their machine, their own account, and the sign-in they already know
how to do. A person has to act, so a window is the right answer here -- see
icd_alerts/visible_windows.py for the rule.

NOT SHIPPED YET, AND NOT LISTED YET. No blueink_docs file is in
agent_files.txt: Blue Ink still sends from our machine, and moving the steps
onto the ICDs' boxes is the last phase of this build, not this one (Megan,
2026-11-23: "I want to move it to the ECO machines once it's all built out").
This is the piece that has to exist BEFORE that move, not the move.

WHEN IT DOES SHIP, the file that needs the visible_windows entry is
`blueink_docs/session.py`, not this one -- that is where headless=False lives.
This module only asks dialogs.py, which is listed already.

    python -m automations.icd_alerts.blueink_signin

Types no password, posts nothing, sends nothing. It opens a browser, waits,
and saves the session the send will replay.
"""
from __future__ import annotations

import sys


def _say_through_window(lines):
    """Collect what login() narrates and show it in ONE box at the end.

    Not a box per line: login() speaks four or five times, and a person
    clicking through five dialogs to be told the same thing learns to click
    without reading -- which is how the one that matters gets dismissed.
    """
    from automations.icd_alerts import dialogs
    body = "\n".join(l for l in lines if (l or "").strip())
    if body:
        dialogs.message(body)


def run(log=print) -> int:
    from automations.blueink_docs import auto_login, session

    # TRY THE SAVED PASSWORD FIRST, AND OPEN NOTHING IF IT WORKS. Blue Ink's
    # sign-in needs no code, so on a machine that has the office's password
    # this whole window is avoidable -- and a window nobody needed is exactly
    # what Lucy is not supposed to put on an owner's screen. The box below is
    # for when the password is absent, changed, or refused.
    try:
        if auto_login.ensure(log=log):
            log("  Blue Ink signed in without anybody being asked.")
            return 0
    except Exception as exc:                        # noqa: BLE001
        log("  automatic sign-in could not run (%s) -- asking the owner"
            % type(exc).__name__)

    said = []

    def say(text: str) -> None:
        said.append(str(text))
        log(str(text))

    from automations.icd_alerts import dialogs
    dialogs.message(
        "Your Blue Ink sign-in has run out.\n\n"
        "New starts' paperwork cannot go out until you sign in again. "
        "A browser is about to open -- sign in to Blue Ink there, the same "
        "way you normally would.\n\n"
        "It has to be THAT window: signing in with your own browser does not "
        "reach Lucy.")
    try:
        code = session.login(say=say)
    except Exception as exc:                    # noqa: BLE001
        # NEVER let the window be the thing that fails. A sign-in prompt that
        # crashes leaves the owner thinking they did it.
        log("blueink sign-in could not run: %s: %s" % (type(exc).__name__, exc))
        _say_through_window(
            ["Blue Ink could not be opened just now.",
             "Nothing has changed, and nothing was sent.",
             "Try again in a few minutes."])
        return 2

    if code == 0:
        _say_through_window(
            ["You're signed in to Blue Ink.",
             "",
             "New starts' paperwork goes out on its own again -- there is "
             "nothing else for you to do."])
    else:
        _say_through_window(
            ["Nobody signed in, so nothing has changed.",
             "",
             "Paperwork stays on hold until somebody does. Run this again "
             "when you have a minute at the computer."])
    return code


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
