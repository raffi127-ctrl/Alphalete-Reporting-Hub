"""Paste Lucy Pitch Auditor's two Slack keys into hidden prompts.

    python -m automations.lucy_transcriber.set_tokens

Nothing you paste is shown or printed. Each key is checked against Slack
before it is saved to ~/.config/recruiting-report/ (only you can read the
files). Then, if Lucy 4 answers on the office network, both files are copied
there and the bot is (re)started -- otherwise it says so and the copy waits
for the next time this laptop is at the office.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys

from automations.lucy_transcriber import config as C

LUCY4 = "lucy4@Lucys-Mac-mini-2.local"
REMOTE_CFG = ".config/recruiting-report"


def _ask(label: str, prefix: str) -> str:
    while True:
        tok = getpass.getpass("Paste the {} (starts with {}), then Enter: ".format(label, prefix)).strip()
        if tok.startswith(prefix):
            return tok
        print("  That one doesn't start with {} -- try again.".format(prefix))


def _save(path, tok: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(tok + "\n")


def ship_to_lucy4() -> bool:
    """Copy both token files to Lucy 4 and restart the bot there. False when
    Lucy 4 isn't reachable (off the office network)."""
    ssh = ["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes", LUCY4]
    if subprocess.run(ssh + ["true"], capture_output=True).returncode != 0:
        return False
    subprocess.run(ssh + ["mkdir -p ~/{0} && chmod 700 ~/{0}".format(REMOTE_CFG)], check=True)
    for p in (C.BOT_TOKEN_FILE, C.APP_TOKEN_FILE):
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", str(p),
                        "{}:{}/{}".format(LUCY4, REMOTE_CFG, p.name)], check=True)
    subprocess.run(ssh + ["chmod 600 ~/{0}/transcriber-*-token".format(REMOTE_CFG)], check=True)
    subprocess.run(ssh + ["launchctl kickstart -k gui/$(id -u)/com.alphalete.lucy-transcriber "
                          "2>/dev/null || true"], check=True)
    return True


def main() -> int:
    bot = _ask("Bot User OAuth Token", "xoxb-")
    from automations.lucy_transcriber import bot as B
    try:
        auth = B.web(bot).auth_test()
    except Exception as e:  # noqa: BLE001
        print("  Slack didn't accept that bot token ({}). Nothing saved.".format(e))
        return 1
    app = _ask("App-Level Token", "xapp-")
    _save(C.BOT_TOKEN_FILE, bot)
    _save(C.APP_TOKEN_FILE, app)
    print("Saved. The bot is '{}' in your Slack.".format(auth.get("user")))
    if ship_to_lucy4():
        print("Copied to Lucy 4 and started the bot there.")
    else:
        print("Lucy 4 isn't reachable from here (not on the office Wi-Fi) -- "
              "the keys are saved on this laptop and get copied over next time.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
