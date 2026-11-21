"""Who Lucy Transcriber is, who gets copies, and what it keeps."""
from __future__ import annotations

import os
from pathlib import Path

# Its own Slack app (Megan 2026-11-21: "a bot, not a channel -- like the 2nd
# round auditor bot"). Reps DM it a recording; it replies in that DM. Built
# from slack_app_manifest.json. Tokens live only on the machine that runs it.
CFG = Path.home() / ".config" / "recruiting-report"
BOT_TOKEN_FILE = CFG / "transcriber-bot-token"     # xoxb- (Bot User OAuth Token)
APP_TOKEN_FILE = CFG / "transcriber-app-token"     # xapp- (App-Level Token, connections:write)

# Who gets a copy of every transcript, to give the rep feedback. Their replies
# under the copy are saved with the transcript (the Phase 2 training set).
COACHES = {
    "U045Z8N0ZQC": "Raf",      # Rafael Hidalgo
}

OUT = Path(__file__).resolve().parents[2] / "output" / "lucy_transcriber"
STATE = OUT / "state.json"
# One JSON per recording: who sent it, the transcript, where it was posted,
# and every feedback reply. Phase 2 ("teach the AI what to look for") reads these.
RECORDS = OUT / "records"
AUDIO = OUT / "audio"

# On start-up, DMs from the last this-many hours with a recording and no
# answer are picked up (the bot was restarting / the Lucy was asleep).
CATCHUP_HOURS = 24

MAX_MB = 400
MAX_SECONDS = 3 * 3600
TRIES = 3           # a recording that fails this many times gets told, then left

AUDIO_TYPES = {"m4a", "mp3", "wav", "aac", "mp4", "mov", "webm", "ogg",
               "opus", "amr", "3gp", "3gpp", "flac", "caf", "qt", "m4v"}


def token(path: Path, env: str) -> str:
    tok = os.environ.get(env, "").strip()
    if not tok and path.exists():
        tok = path.read_text(encoding="utf-8-sig").strip()
    return tok.lstrip("﻿")
