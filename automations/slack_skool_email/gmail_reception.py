"""Gmail for alphaletereception@gmail.com -- its OWN token, kept apart from
every other Google credential in this repo.

There are already three Google identities in play and mixing them breaks
things in ways that are quiet:
  * ~/.config/recruiting-report/oauth-token.json   raffi127@ (Sheets, ~52 tabs)
  * ~/.config/recruiting-report/gmail-token.json   alphaletereporting@ (drafts)
  * contacts-token-alphaletereception.json         reception's Contacts

Gmail sends FROM the mailbox that authorized the token, so this email -- which
has to come from reception, the address new starts already reply to -- needs a
fourth: reception's own gmail token. Re-consenting one of the others as
reception would break whatever depends on it.

One-time, on a machine where a human can click the consent screen:

    python -m automations.slack_skool_email.gmail_reception --auth

then ship it to the runner:

    lucy push_cred_file gmail-token-alphaletereception 'Lucy 1'
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

# gmail.compose covers create-draft AND send, so one grant serves both --send
# and --draft. gmail.send alone could not make the review draft.
SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
ACCOUNT = "alphaletereception@gmail.com"

_CONFIG_DIR = Path.home() / ".config" / "recruiting-report"
OAUTH_CLIENT_PATH = _CONFIG_DIR / "oauth-client.json"
TOKEN_PATH = _CONFIG_DIR / "gmail-token-alphaletereception.json"


def authorize() -> None:
    """One-time interactive OAuth -> saves reception's Gmail token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(
            "OAuth client not found at {}. Ask Megan for oauth-client.json."
            .format(OAUTH_CLIENT_PATH))

    flow = InstalledAppFlow.from_client_secrets_file(
        str(OAUTH_CLIENT_PATH), SCOPES)
    creds = flow.run_local_server(
        port=0,
        login_hint=ACCOUNT,
        prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Gmail.\n"
            "-> Sign in as {} (NOT raffi127, NOT alphaletereporting) "
            "and approve.\n"
            "If it doesn't open, copy this URL into your browser:\n{{url}}"
            .format(ACCOUNT)),
        success_message="Done - close this tab and return to the terminal.",
    )

    granted = set(creds.scopes or [])
    if not granted.issuperset(SCOPES):
        raise RuntimeError(
            "Authorization came back without the gmail.compose scope (got {})."
            .format(granted or "none"))

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print("OK - saved reception Gmail token to {}".format(TOKEN_PATH))


def load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_PATH.exists():
        raise RuntimeError(
            "No reception Gmail token at {}. Run the one-time authorization "
            "on a machine with a browser:\n"
            "  python -m automations.slack_skool_email.gmail_reception --auth"
            .format(TOKEN_PATH))

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Reception Gmail token is invalid and can't be refreshed. "
                "Re-run with --auth.")
    return creds


def _service():
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=load_credentials(),
                 cache_discovery=False)


def whoami() -> str:
    """The address this token actually sends as. Cheap way to catch a token
    that was authorized as the wrong account -- which would otherwise mail
    every new start from the WRONG mailbox and look like a clean run."""
    return _service().users().getProfile(userId="me").execute().get(
        "emailAddress", "")


def assert_right_mailbox() -> str:
    who = (whoami() or "").strip().lower()
    if who != ACCOUNT:
        raise RuntimeError(
            "This Gmail token belongs to {!r}, not {}. Sending would mail "
            "every new start from the wrong address. Re-run --auth and sign "
            "in as reception.".format(who or "an unknown account", ACCOUNT))
    return who


def _raw(msg: EmailMessage) -> str:
    return base64.urlsafe_b64encode(bytes(msg)).decode("ascii")


def send(msg: EmailMessage) -> dict:
    """Send `msg` from reception's mailbox. No undo."""
    return _service().users().messages().send(
        userId="me", body={"raw": _raw(msg)}).execute()


def create_draft(msg: EmailMessage) -> dict:
    """Land `msg` in reception's Drafts for a human to eyeball and send."""
    return _service().users().drafts().create(
        userId="me", body={"message": {"raw": _raw(msg)}}).execute()


def already_sent_today(search_phrase: str) -> bool:
    """Has this email already gone out from this mailbox today?

    `search_phrase` is a distinctive, punctuation-free run of words from the
    subject (config.SUBJECT_SEARCH), not the subject itself -- Gmail's search
    handles punctuation unevenly and a query that silently matches nothing
    would let the cohort be mailed twice.

    The re-send guard. It asks GMAIL rather than keeping a local marker, so it
    holds across machines and across a hand-send: if Alisson already sent it
    manually at 7:50, the 8:00 run finds it and stays quiet instead of mailing
    the cohort twice.
    """
    q = 'in:sent subject:"{}" newer_than:1d'.format(
        search_phrase.replace('"', ""))
    res = _service().users().messages().list(
        userId="me", q=q, maxResults=1).execute()
    return bool(res.get("messages"))


if __name__ == "__main__":
    import sys
    if "--auth" in sys.argv:
        authorize()
    else:
        print(whoami())
