"""The office's own Blue Ink account, connected once on its own computer.

Megan, 2026-11-09: *"each ICD will have their own blueink account."*

TWO THINGS ARE NEEDED AND THEY ARE NOT THE SAME THING:

  * an **API key**, which is how the board READS who has signed
    (`blueink_data.completed_bundles` -> `/bundles/`). Reading is an ordinary
    API call and is not capped.
  * a **web session**, which is how documents are SENT. On the Unlimited
    Annual plan any bundle the API creates bills as a *Bulk Envelope* and that
    allowance is 50 a year; sends made in the web app come out of the unlimited
    *Envelopes* bucket instead. So sending drives the same screens a person
    does, and that needs a signed-in browser.

An office can have the first and not the second: the board fills, nothing is
sent. That is a fine state and this says so rather than calling it failure.

THE OWNER TYPES THEIR PASSWORD ONCE, HERE, AND IS NEVER ASKED AGAIN.

Until 2026-11-23 there was no automated password path at all, and the reason
given was "the repo is public". That reason is about the REPO, and the
credential never goes near it: it is typed into a password box on the owner's
own machine and saved beside their OwnerVille, Sterling, AppStream and Apex
passwords, readable by that user alone. Blue Ink's sign-in is an email, a
password and a Log In button -- no code, no second factor (Megan, 2026-11-23)
-- so once it is saved, Lucy signs in by herself and the fortnightly expiry
stops being anybody's problem. Without it, every office is interrupted every
two weeks by a window Lucy is not supposed to open at all.

Nobody here reads it back: it goes from the box to the file, and from the file
into the sign-in page. It is not logged, not posted, and not carried in an
exception (blueink_docs/auto_login.py).

WHERE IT IS KEPT: `~/.config/lucy-reports/`, beside every other ECO credential,
never in the repo -- the ICD app may be installed where the user cannot write,
and the repo copy is replaced on every update, so a key or profile parked
inside it is destroyed by a `git pull`.

THE KEY IS PROVED BEFORE IT IS SAVED. A pasted key with a stray space, or one
copied from the wrong account, is indistinguishable from a working one until
the first real run -- which is a week later, on somebody's first day.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

ECO_DIR = Path.home() / ".config" / "lucy-reports"
CREDS_PATH = ECO_DIR / "blueink-creds.json"

SKIP = "Not now"

ASK_KEY = (
    "Lucy needs your own Blue Ink account to see who has signed their "
    "onboarding documents.\n\n"
    "In Blue Ink: Settings → API → create a private API key, then paste it "
    "here. It stays on this computer.")


ASK_EMAIL = (
    "Lucy can sign in to Blue Ink for you, so nobody has to do it again "
    "every couple of weeks.\n\n"
    "The email address you use to sign in to Blue Ink:")
ASK_PASSWORD = (
    "And your Blue Ink password.\n\n"
    "It is saved on this computer only, next to your other sign-ins. "
    "Nobody can read it from here and it is never sent anywhere.")


def have_login() -> bool:
    """Is there already an email and password saved on this machine?"""
    try:
        from automations.blueink_docs import config as BC
        return bool(BC.login_creds())
    except Exception:          # noqa: BLE001
        return False


def save_login(email: str, password: str) -> None:
    """Into the office's own Blue Ink file, beside the API key.

    READ-MODIFY-WRITE, never a fresh file: the key and the template id may
    already be in there, and rewriting the file from scratch would throw them
    away to save a password.
    """
    ECO_DIR.mkdir(parents=True, exist_ok=True)
    try:
        body = json.loads(CREDS_PATH.read_text())
        if not isinstance(body, dict):
            body = {}
    except Exception:          # noqa: BLE001
        body = {}
    body["email"] = email
    body["password"] = password
    CREDS_PATH.write_text(json.dumps(body, indent=2))
    try:
        CREDS_PATH.chmod(0o600)
    except OSError:
        pass


def ask_login(ask, log=print) -> str:
    """Ask for the sign-in and save it. A word for the summary.

    SKIPPED WHEN IT IS ALREADY THERE, like every other setup step -- this
    runs on a link an office may use a dozen times.
    """
    if have_login():
        return "sign-in saved"
    try:
        email = (ask.text(ASK_EMAIL) or "").strip()
        if not email:
            return "no sign-in saved"
        password = ask.password(ASK_PASSWORD)
    except ask.Cancelled:
        return "no sign-in saved"
    if not password:
        return "no sign-in saved"
    save_login(email, password)
    log("      Blue Ink sign-in saved on this computer.")
    return "sign-in saved"


def have_key() -> bool:
    try:
        return bool(json.loads(CREDS_PATH.read_text()).get("blueink_api_key"))
    except Exception:          # noqa: BLE001
        return False


def _works(key: str) -> Optional[str]:
    """None when the key reads this account, else why not.

    Proved against the live account before anything is written.
    """
    before = os.environ.get("BLUEINK_PRIVATE_API_KEY")
    os.environ["BLUEINK_PRIVATE_API_KEY"] = key
    try:
        import importlib
        from automations.blueink_docs import blueink as B
        from automations.blueink_docs import config as C
        importlib.reload(C)
        importlib.reload(B)
        B._results(B._request("GET", "/bundles/", params={"per_page": 1}))
        return None
    except Exception as e:     # noqa: BLE001
        text = str(e)
        if "401" in text or "403" in text:
            return "Blue Ink did not accept that key."
        return "Blue Ink could not be reached (%s)." % type(e).__name__
    finally:
        if before is None:
            os.environ.pop("BLUEINK_PRIVATE_API_KEY", None)
        else:
            os.environ["BLUEINK_PRIVATE_API_KEY"] = before


def _templates(key: str) -> List[dict]:
    before = os.environ.get("BLUEINK_PRIVATE_API_KEY")
    os.environ["BLUEINK_PRIVATE_API_KEY"] = key
    try:
        import importlib
        from automations.blueink_docs import blueink as B
        from automations.blueink_docs import config as C
        importlib.reload(C)
        importlib.reload(B)
        return list(B.list_envelope_templates() or [])
    except Exception:          # noqa: BLE001 — a template pick is not the key
        return []
    finally:
        if before is None:
            os.environ.pop("BLUEINK_PRIVATE_API_KEY", None)
        else:
            os.environ["BLUEINK_PRIVATE_API_KEY"] = before


def _save(key: str, template_id: str = "", log=print) -> None:
    ECO_DIR.mkdir(parents=True, exist_ok=True)
    body = {}
    if CREDS_PATH.exists():
        try:
            body = json.loads(CREDS_PATH.read_text())
        except Exception:      # noqa: BLE001
            body = {}
    body["blueink_api_key"] = key
    if template_id:
        body["envelope_template_id"] = template_id
    CREDS_PATH.write_text(json.dumps(body, indent=1))
    CREDS_PATH.chmod(0o600)
    log("  saved to %s (owner-only)" % CREDS_PATH)


def connect_key(*, ask=None, log=print) -> str:
    """Ask for, PROVE and save an API key. Not part of normal setup.

    API Access is an Enterprise-only feature on this Blue Ink plan, so most
    offices cannot create a key however clearly they are asked -- which is why
    the board reads the web app instead and `run()` never requests one. This
    stays for an office that does have Enterprise access, run by hand.
    """
    if ask is None:
        from automations.icd_alerts import dialogs as ask  # type: ignore
    try:
        key = ask.password(ASK_KEY).strip()
        if not key:
            return "left for later"
        why = _works(key)
        if why:
            # NOT SAVED. A bad key looks exactly like a good one until the
            # first real run, which is a week later on somebody's first day.
            ask.message(why + "\n\nNothing was saved — run this again with "
                              "the key from Settings → API.", error=True)
            return "key not accepted"
        picked = ""
        templates = _templates(key)
        if len(templates) == 1:
            picked = str(templates[0].get("id") or "")
            log("  one document template on the account: %s"
                % templates[0].get("name"))
        elif templates:
            names = [str(t.get("name") or t.get("id")) for t in templates]
            choice = ask.choose(
                "Which document template do your new starts sign?",
                names + [SKIP])
            if choice != SKIP:
                picked = str(templates[names.index(choice)].get("id") or "")
        _save(key, picked, log=log)
        return "key saved"
    except ask.Cancelled:
        return "left for later"
    except Exception as e:     # noqa: BLE001
        log("  Blue Ink key step stopped: %s" % type(e).__name__)
        return "could not finish — run this again"


def run(*, ask=None, log=print) -> str:
    """Connect this office's Blue Ink. ONE STEP: sign in.

    Megan, 2026-11-09, on asking an owner for an API key: *"is it going to be
    hard for them?"* It was, and worse than hard -- API Access is an
    Enterprise-only feature on this plan, so an owner on a normal plan cannot
    create a key however clearly they are asked. So nothing is asked for. The
    person signs in to Blue Ink the way they always do, and the board reads
    who has signed off the same screen they would look at themselves.

    A key that happens to be on the machine is still used for the read, since
    it is quicker. It is simply never requested.

    Never raises: one setup step must not cost the ones after it.
    """
    if ask is None:
        from automations.icd_alerts import dialogs as ask  # type: ignore

    # DOES THIS OFFICE EVEN HAVE BLUE INK? Asked before anything else, because
    # an office without it cannot do Apex either -- Apex reads each person's
    # date of birth and address out of the signed packet -- and both steps are
    # then marked n/a on their board rather than sitting open for ever.
    try:
        from automations.icd_alerts import config as IC
        from automations.icd_onboarding import office_steps as OS
        rows = IC.enrollments()
        key = (rows[0].get("office_key") if rows else "") or ""
        known = OS.uses_blueink(key) if key else None
        if known is None and key:
            said_yes = ask.choose(
                "Does your office use Blue Ink for onboarding documents?\n\n"
                "It is what new starts sign before their first day. If you do "
                "not use it, Lucy will skip those steps for you.",
                ["Yes", "No", SKIP])
            if said_yes == SKIP:
                return "left for later"
            known = said_yes == "Yes"
            OS.save_blueink(key, known, log=log)
        if known is False:
            return "not used by this office — Blue Ink and Apex are skipped"
    except ask.Cancelled:
        return "left for later"
    except Exception as e:     # noqa: BLE001
        log("  could not check whether this office uses Blue Ink: %s"
            % type(e).__name__)

    said = ["API key here too" if have_key() else "reading the web app"]
    try:
        from automations.blueink_docs import session as S
        # have_session() is "is there a saved session worth replaying"; check()
        # opens it and asks the app. The cheap one first: an office that has
        # never signed in needs no browser opened to find that out.
        if S.have_session() and S.check(headless=True) == 0:
            said.append("signed in")
            return ", ".join(said)
        # THE SAVED PASSWORD FIRST. If this office has one, nobody is asked
        # anything -- which is the whole point of having asked once.
        said.append(ask_login(ask, log))
        try:
            from automations.blueink_docs import auto_login as AL
            if AL.can_try() and AL.ensure(log=log):
                said.append("signed in")
                return ", ".join(said)
        except Exception as e:  # noqa: BLE001
            log("  automatic Blue Ink sign-in stopped: %s" % type(e).__name__)

        yes = ask.choose(
            "Sign in to Blue Ink?\n\n"
            "Lucy needs this to see who has signed their onboarding documents, "
            "and to send them for you. Your browser opens on Blue Ink — sign in "
            "the way you normally do.",
            ["Yes, open Blue Ink", SKIP])
        if yes == SKIP:
            said.append("not signed in yet")
        else:
            S.login()
            said.append("signed in" if S.have_session()
                        else "sign-in did not stick")
    except ask.Cancelled:
        said.append("not signed in yet")
    except Exception as e:     # noqa: BLE001
        log("  Blue Ink sign-in stopped: %s" % type(e).__name__)
        said.append("sign-in could not be opened")
    return ", ".join(said)


def main(argv=None) -> int:
    """    python -m automations.icd_alerts.blueink_setup"""
    print(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
