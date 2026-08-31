"""Is this Mac ready to send swag texts AND cards? Run it before a batch.

Every swag failure so far has been one of a handful of machine-level things --
old macOS, missing Shortcut, stale Hub process, missing API key -- and each one
looked like a mystery from the Hub. This checks all of them in one go and says
exactly what to do about each.

    python -m automations.swag_welcome.check_machine

Read-only: it sends nothing and changes nothing. To prove the card path
end-to-end afterwards, send yourself one card:

    python -m automations.swag_welcome.verify_card +15551234567
"""

from __future__ import annotations

import importlib
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]

OK, WARN, BAD = "PASS", "WARN", "FAIL"


def _row(state: str, label: str, detail: str = "", fix: str = "") -> dict:
    return {"state": state, "label": label, "detail": detail, "fix": fix}


def _run(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw)


def check_macos() -> dict:
    if platform.system() != "Darwin":
        return _row(BAD, "macOS", f"this is {platform.system()}",
                    "swag texts only send from a Mac.")
    ver = platform.mac_ver()[0] or "?"
    try:
        major = int(ver.split(".")[0])
    except ValueError:
        major = 0
    if major >= 26:
        return _row(OK, "macOS version", ver)
    return _row(BAD, "macOS version", ver,
                "Cards cannot auto-send below macOS 26 -- the Shortcut runs, "
                "exits clean and delivers nothing. Texts still send. Either "
                "upgrade this Mac to macOS 26, or turn ON 'Show When Run' in "
                "the Shortcut and click Send once per card.")


def check_code_current() -> dict:
    """Is the checkout current, and does it have the card fixes?"""
    from automations.swag_welcome import imessage
    if not hasattr(imessage, "card_autosend_blocked"):
        return _row(BAD, "swag code", "this checkout predates the card fixes",
                    "Run: git pull")
    if not getattr(imessage, "_AUTO_SEND_CARD", False):
        return _row(BAD, "card auto-send", "switched off in imessage.py",
                    "Run: git pull  (it is ON as of 2026-08-25)")
    try:
        _run(["git", "fetch", "-q", "origin"], cwd=WORKSPACE)
        behind = _run(["git", "rev-list", "--count", "HEAD..origin/main"],
                      cwd=WORKSPACE).stdout.strip()
        if behind.isdigit() and int(behind) > 0:
            return _row(WARN, "swag code", f"{behind} commit(s) behind origin/main",
                        "Run: git pull  (then restart the Hub)")
    except Exception:
        pass
    return _row(OK, "swag code", "current, card auto-send ON")


def check_shortcut() -> dict:
    from automations.swag_welcome import imessage
    actual = imessage._find_shortcut()
    if actual:
        return _row(OK, "card Shortcut", f"found as {actual!r}")
    return _row(BAD, "card Shortcut", f"no Shortcut named {imessage.SHORTCUT_NAME!r}",
                "Build it in the Shortcuts app (4 actions -- the Hub's swag card "
                "shows the exact steps), then re-run this check. Texts send "
                "without it; cards do not.")


def check_messages() -> dict:
    from automations.swag_welcome import imessage
    ok, detail = imessage.messages_ready()
    if ok:
        return _row(OK, "Messages", detail)
    return _row(BAD, "Messages", detail,
                "Open Messages and sign into iMessage with the account the "
                "hires should hear from.")


def check_handoff_folder() -> dict:
    from automations.swag_welcome import imessage
    d = imessage._SWAG_DIR
    try:
        d.mkdir(exist_ok=True)
        probe = d / ".writecheck"
        probe.write_text("ok")
        probe.unlink()
    except Exception as e:
        return _row(BAD, "card handoff folder", f"{d} not writable ({e})",
                    f"Create {d} and make sure this user owns it.")
    return _row(OK, "card handoff folder", str(d))


def check_roster_reader() -> dict:
    """The roster screenshot is read by Claude -- needs the package AND a key."""
    try:
        importlib.import_module("anthropic")
    except Exception:
        return _row(BAD, "roster reader", "the `anthropic` package is missing",
                    f"Run: {sys.executable} -m pip install anthropic")
    key = None
    try:
        # Same lookup extract.py uses to read the roster screenshot -- checking
        # any other path would pass here and still fail in the real run.
        from automations.brand_audit import credentials
        key = credentials.anthropic_api_key()
    except Exception:
        key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return _row(BAD, "roster reader", "no Anthropic API key on this machine",
                    'Put {"anthropic_api_key":"sk-ant-..."} in '
                    "~/.config/brand-audit/keys.json, then RESTART the Hub "
                    "(the key lookup is cached for the life of the process).")
    if not str(key).startswith("sk-ant-"):
        return _row(BAD, "roster reader", "the stored key is not an Anthropic key",
                    "keys.json holds more than one key -- copy the sk-ant- one "
                    "into anthropic_api_key (the 64-char hex one is SerpApi).")
    return _row(OK, "roster reader", "anthropic package + key present")


def check_hub_fresh() -> dict:
    """A Hub started before the code changed is still running the OLD module."""
    try:
        ps = _run(["pgrep", "-f", "streamlit run"]).stdout.split()
    except Exception:
        return _row(WARN, "Hub process", "couldn't check")
    if not ps:
        return _row(OK, "Hub process", "not running -- it will load fresh code on start")
    newest_code = max(p.stat().st_mtime
                      for p in (WORKSPACE / "automations" / "swag_welcome").glob("*.py"))
    stale = []
    for pid in ps:
        out = _run(["ps", "-o", "lstart=", "-p", pid]).stdout.strip()
        if not out:
            continue
        try:
            started = time.mktime(time.strptime(out))
        except ValueError:
            continue
        if started < newest_code:
            stale.append(pid)
    if stale:
        return _row(BAD, "Hub process",
                    f"pid {', '.join(stale)} started before the current swag code",
                    "The Hub does not watch files -- it is still running the OLD "
                    "code in memory. Quit and relaunch the Hub before the batch.")
    return _row(OK, "Hub process", "running code no older than the files on disk")


CHECKS = [check_macos, check_code_current, check_shortcut, check_messages,
          check_handoff_folder, check_roster_reader, check_hub_fresh]


def main() -> int:
    print("Swag sender -- machine check")
    print(f"  {platform.node()}  |  {WORKSPACE}\n")
    rows = []
    for fn in CHECKS:
        try:
            rows.append(fn())
        except Exception as e:  # a check must never be the thing that breaks
            rows.append(_row(WARN, fn.__name__, f"check errored: {e}"))

    mark = {OK: "[ok]  ", WARN: "[warn]", BAD: "[FAIL]"}
    for r in rows:
        print(f"{mark[r['state']]} {r['label']}: {r['detail']}")

    bad = [r for r in rows if r["state"] == BAD]
    warn = [r for r in rows if r["state"] == WARN]
    print()
    if not bad:
        print("READY -- texts and cards will both send from this Mac.")
        if warn:
            print("\nWorth doing first:")
            for r in warn:
                print(f"  - {r['label']}: {r['fix'] or r['detail']}")
        print("\nProve the card path end-to-end (sends ONE card to a number you own):")
        print(f"  {sys.executable} -m automations.swag_welcome.verify_card "
              "+1YOURCELL")
        return 0

    thing = "thing" if len(bad) == 1 else "things"
    print(f"NOT READY -- {len(bad)} {thing} to fix:\n")
    for i, r in enumerate(bad, 1):
        print(f"  {i}. {r['label']} -- {r['detail']}")
        for line in (r["fix"] or "").split(". "):
            if line.strip():
                print(f"     {line.strip().rstrip('.')}.")
        print()
    print("Texts still send even if only the CARD checks failed -- the hires get "
          "the message, and the cards can be sent after with:")
    print(f"  {sys.executable} -m automations.swag_welcome.send_cards_only --send")
    return 1


if __name__ == "__main__":
    sys.exit(main())
