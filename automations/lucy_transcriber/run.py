"""Lucy Transcriber -- hand checks. The bot itself is bot.py.

    python -m automations.lucy_transcriber.run --file "~/Downloads/door 3.m4a"
        # one local file -> prints exactly what the rep would get. No Slack.
    python -m automations.lucy_transcriber.run --doctor [--fix]
        # can THIS machine run the bot? Posts nothing.

Neither one colours the Hub card: they are questions, not deliveries.
"""
from __future__ import annotations  # Lucy runs Python 3.9

import argparse
import importlib
import platform
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.lucy_transcriber import config as C
from automations.lucy_transcriber import render as R
from automations.lucy_transcriber import transcribe as T

_PKGS = {"mlx_whisper": "mlx-whisper", "imageio_ffmpeg": "imageio-ffmpeg",
         "numpy": "numpy", "anthropic": "anthropic", "slack_sdk": "slack-sdk",
         "reportlab": "reportlab"}
# What the bot's token must carry (slack_app_manifest.json).
_SCOPES = ("chat:write", "im:history", "im:read", "im:write", "files:read",
           "files:write", "users:read", "reactions:write")


def doctor(fix: bool = False) -> int:
    """Read-only unless --fix, which pip-installs a missing package into this
    venv. Also warms up: a 2-second silent clip makes Whisper fetch its model
    now (one time, ~480 MB) instead of on a rep's first recording, and a
    two-line labelling call proves the Claude key works (a fraction of a
    cent)."""
    ok = True

    def say(good: bool, what: str) -> None:
        nonlocal ok
        ok = ok and good
        print("{}  {}".format("PASS" if good else "FAIL", what), flush=True)

    say(platform.machine() == "arm64",
        "Apple chip ({}) -- mlx-whisper needs one".format(platform.machine()))
    for mod, pkg in _PKGS.items():
        try:
            importlib.import_module(mod)
            say(True, "python package " + pkg)
            continue
        except ImportError:
            pass
        if fix:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg],
                               capture_output=True, text=True)
            importlib.invalidate_caches()
            try:
                importlib.import_module(mod)
                say(True, "python package {} (installed just now)".format(pkg))
                continue
            except ImportError:
                print((r.stderr or "")[-400:])
        say(False, "python package {} missing{}".format(pkg, "" if fix else " -- rerun with --fix"))
    try:
        from automations.brand_audit import credentials
        say(bool(credentials.anthropic_api_key()), "Anthropic key found")
    except Exception as e:  # noqa: BLE001
        say(False, "Anthropic key: {}".format(e))

    bt = C.token(C.BOT_TOKEN_FILE, "LUCY_TRANSCRIBER_BOT_TOKEN")
    at = C.token(C.APP_TOKEN_FILE, "LUCY_TRANSCRIBER_APP_TOKEN")
    say(bt.startswith("xoxb-"), "bot token in {}".format(C.BOT_TOKEN_FILE))
    say(at.startswith("xapp-"), "app token in {}".format(C.APP_TOKEN_FILE))
    if bt.startswith("xoxb-"):
        try:
            from automations.lucy_transcriber import bot
            auth = bot.web(bt).auth_test()
            scopes = set((auth.headers.get("x-oauth-scopes") or "").split(","))
            say(True, "Slack bot is {} ({})".format(auth.get("user"), auth.get("user_id")))
            for need in _SCOPES:
                say(need in scopes, "Slack scope " + need)
        except Exception as e:  # noqa: BLE001
            say(False, "Slack: {}".format(e))
    if ok:
        try:
            import numpy as np
            T.words(np.zeros(2 * T.SAMPLE_RATE, dtype=np.float32))
            say(True, "Whisper model ready ({})".format(T.MODEL))
            labels = T.label([
                {"n": 1, "start": 0.0, "end": 2.0,
                 "text": "Hi, I'm Jordan with AT&T, fiber just went live on your street."},
                {"n": 2, "start": 2.5, "end": 3.5, "text": "We already have Spectrum."}])
            say(labels == ["R", "C"], "Claude labels a test exchange ({})".format(labels))
        except Exception as e:  # noqa: BLE001
            say(False, "warm-up: {}".format(e))
    print("READY" if ok else "NOT READY", flush=True)
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="transcribe one local file and print it (no Slack)")
    ap.add_argument("--doctor", action="store_true",
                    help="can this machine run the bot? (posts nothing)")
    ap.add_argument("--fix", action="store_true",
                    help="with --doctor: pip-install a missing package")
    a = ap.parse_args(argv)
    try:
        from automations.shared import hub_autopublish
        hub_autopublish.nothing_to_report()
    except Exception:  # noqa: BLE001
        pass
    if a.doctor:
        return doctor(fix=a.fix)
    if a.file:
        got = T.transcribe(Path(a.file).expanduser(), max_seconds=C.MAX_SECONDS)
        print(("\n\n----- next message -----\n\n").join(
            R.slack_messages(got) or [R.as_text(got)]))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
