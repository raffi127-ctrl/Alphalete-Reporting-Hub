"""Paste Lucy Pitch Auditor's two Slack keys into hidden prompts.

    python -m automations.lucy_transcriber.set_tokens

Nothing you paste is shown or printed. Each key is checked against Slack
before it is saved to ~/.config/recruiting-report/ (only you can read the
files). Then, if Lucy 3 answers on the office network, both files are copied
there and the bot is (re)started -- otherwise it says so and the copy waits
for the next time this laptop is at the office.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys

from automations.lucy_transcriber import config as C

LUCY = "lucy3@Lucys-Mac-mini.local"     # Lucy 3: has the Claude key + Apple chip
REMOTE_CFG = ".config/recruiting-report"


# Where each key is on the app's Slack page -- shown in the Mac pop-up.
WHERE = {
    "xoxb-": "In the Slack tab: left menu “OAuth & Permissions” → "
             "“Bot User OAuth Token” → Copy.",
    "xapp-": "In the Slack tab: left menu “Basic Information” → scroll to "
             "“App-Level Tokens” → click “socket” → Copy.",
}


def _dialog(label: str, prefix: str, again: bool) -> str:
    """A Mac pop-up with a hidden box (Megan 2026-11-21: the Terminal prompt
    was one step too many). '' when she clicks Cancel."""
    msg = "{}{}\n\nThen click in the box below, press ⌘V, and click Save.".format(
        "That one didn't start with {}. ".format(prefix) if again else "", WHERE[prefix])
    script = ('display dialog {} default answer "" with hidden answer '
              'with title {} buttons {{"Cancel", "Save"}} default button "Save"\n'
              'text returned of result').format(
        _as(msg), _as("Lucy Pitch Auditor — " + label))
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _as(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ask(label: str, prefix: str, dialog: bool = False) -> str:
    again = False
    while True:
        if dialog:
            tok = _dialog(label, prefix, again)
            if not tok:
                raise SystemExit("Cancelled -- nothing saved.")
        else:
            tok = getpass.getpass("Paste the {} (starts with {}), then Enter: ".format(label, prefix)).strip()
        if tok.startswith(prefix):
            return tok
        again = True
        if not dialog:
            print("  That one doesn't start with {} -- try again.".format(prefix))


def _save(path, tok: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(tok + "\n")


def ship_to_lucy() -> bool:
    """Copy both token files to Lucy 3 and restart the bot there. False when
    Lucy 3 isn't reachable (off the office network)."""
    ssh = ["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes", LUCY]
    if subprocess.run(ssh + ["true"], capture_output=True).returncode != 0:
        return False
    subprocess.run(ssh + ["mkdir -p ~/{0} && chmod 700 ~/{0}".format(REMOTE_CFG)], check=True)
    for p in (C.BOT_TOKEN_FILE, C.APP_TOKEN_FILE):
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(p),
                        "{}:{}/{}".format(LUCY, REMOTE_CFG, p.name)], check=True)
    subprocess.run(ssh + ["chmod 600 ~/{0}/transcriber-*-token".format(REMOTE_CFG)], check=True)
    subprocess.run(ssh + ["launchctl kickstart -k gui/$(id -u)/com.alphalete.lucy-transcriber "
                          "2>/dev/null || true"], check=True)
    return True


def main() -> int:
    if "--ship-only" in sys.argv[1:]:
        # The keys are already on this laptop: just try the copy. Exit 3 =
        # Lucy 3 not reachable yet (off the office Wi-Fi) -- try again later.
        if not (C.BOT_TOKEN_FILE.exists() and C.APP_TOKEN_FILE.exists()):
            print("No keys saved on this laptop yet.")
            return 1
        if ship_to_lucy():
            print("Copied to Lucy 3 and started the bot there.")
            return 0
        print("Lucy 3 not reachable yet.")
        return 3
    dialog = "--dialog" in sys.argv[1:]
    bot = _ask("Bot token", "xoxb-", dialog)
    from automations.lucy_transcriber import bot as B
    try:
        auth = B.web(bot).auth_test()
    except Exception as e:  # noqa: BLE001
        print("  Slack didn't accept that bot token ({}). Nothing saved.".format(
            type(e).__name__))
        return 1
    app = _ask("App token", "xapp-", dialog)
    _save(C.BOT_TOKEN_FILE, bot)
    _save(C.APP_TOKEN_FILE, app)
    print("Saved. The bot is '{}' in your Slack.".format(auth.get("user")))
    if ship_to_lucy():
        print("Copied to Lucy 3 and started the bot there.")
    else:
        print("Lucy 3 isn't reachable from here (not on the office Wi-Fi) -- "
              "the keys are saved on this laptop and get copied over next time.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
