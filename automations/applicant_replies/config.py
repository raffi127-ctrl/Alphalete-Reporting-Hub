"""Settings for Lucy's applicant replies.

Megan 2026-10-20: "let's build it out but not apply it to any account yet".

So ENABLED_OFFICES is EMPTY on purpose. Nothing in this package logs into
AppStream or sends a text — it reads saved SMS logs (output/sms_log_*.json,
written by sms_audit.pull_log) and writes what Lucy WOULD have said. The set
is here so the day an account is switched on, it is one reviewed line, and
test_never_sends fails if anyone wires a send path in without it.
"""
from __future__ import annotations

import os

# Accounts Lucy may act on live. Empty = shadow only, everywhere.
ENABLED_OFFICES = frozenset()

MODEL = "claude-opus-5-5"
EFFORT = os.environ.get("LUCY_REPLY_EFFORT", "medium")

# An applicant message with no reply from us inside this many minutes is
# "left hanging". Recruiters reply in a median 9 min (SMS audit, WE 9/25),
# but at 15 the first shadow run of 11280 showed 381 of 692 "unanswered"
# turns DID get a human reply inside the hour — Lucy at 15 would have
# double-texted them. 30 keeps her clear of a normal slow reply. Live, this
# also needs a claim on the thread so a recruiter and Lucy can't both answer.
WAIT_MINUTES = int(os.environ.get("LUCY_REPLY_WAIT_MIN", "30"))

# Two SMS segments is the house target (escalations.WHY["TOO LONG"]).
MAX_SEGMENTS = 2

# How much of the thread the model sees. Ruling 7's lesson: a reply read
# without the messages above it gets judged wrong.
THREAD_TAIL = 14
