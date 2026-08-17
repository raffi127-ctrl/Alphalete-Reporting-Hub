"""One delivery per recipient per day — enforced in the MODULE, not the wrapper.

WHY (2026-08-17): the "exactly one post/email a day" rule lived only in the
LaunchAgent wrappers. deploy/box_order_log.sh checks .box-order-log-posted-<date>
before adding --post, and box_order_log_owners.sh checks a per-owner marker
before adding --email. Every OTHER way of running these — `lucy rerun
box_order_log --post`, `lucy rerun box_order_log_roshan --email`, a Hub card
click, a hand-run — walks straight past that check, because the module itself
never knew the day was already done.

That is exactly what happened on 2026-08-17. A capped Tableau pull suppressed all
three deliveries in the morning; the pin was cleared at ~11:20 and the noon runs
posted Carlos's thread and emailed Abel and Roshan cleanly. Not seeing that, a
later session re-ran all three with --post / --email at ~16:35–16:54: both
channels got a second identical thread and both owners got a second identical
email. The wrapper would have caught it — the marker was sitting right there — but
`lucy rerun` never reads it.

So the check moves HERE, next to the send, where every caller has to pass it:

    if already_done(stem, today) and not resend:   -> skip, exit 0
    ...deliver...
    mark_done(stem, today)

The wrappers keep their own check + touch. That is deliberate redundancy, not
duplication: the wrapper still short-circuits before paying for a Tableau pull,
and the marker names/paths are identical, so either side writing it satisfies the
other. `--resend` is the deliberate override for a delivery that really does need
to go twice (a first send that went out wrong).

Marker names are FIXED — deploy/box_order_log.sh, deploy/box_order_log_owners.sh
and day_orchestrator/post_watch.py all key off these exact strings. Changing one
silently breaks the other two. Python 3.9 on the runners: no `X | Y` at runtime.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "output" / "logs"

# Carlos's Slack thread — the SAME file deploy/box_order_log.sh touches.
POST_STEM = ".box-order-log-posted-"


def owner_stem(owner_key: str) -> str:
    """Per-owner email marker — the SAME file deploy/box_order_log_owners.sh
    touches for that owner (it builds this name from $KEY)."""
    return ".box-order-log-owner-{}-posted-".format(owner_key)


def path(stem: str, day: Optional[dt.date] = None) -> Path:
    day = day or dt.date.today()
    return LOG_DIR / "{}{}".format(stem, day.isoformat())


def already_done(stem: str, day: Optional[dt.date] = None) -> bool:
    """True when today's delivery already went out. Fails CLOSED-ish on purpose:
    a marker we can't stat reads as absent, so a filesystem hiccup delivers a
    duplicate rather than silently suppressing the day's only send. A duplicate
    is embarrassing; a silent no-send is the failure we spent this morning
    chasing."""
    try:
        return path(stem, day).exists()
    except Exception:  # noqa: BLE001
        return False


def mark_done(stem: str, day: Optional[dt.date] = None) -> None:
    """Record that today's delivery landed. Best-effort — never let bookkeeping
    fail a send that already succeeded."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path(stem, day).touch()
    except Exception:  # noqa: BLE001
        pass


def skip_message(what: str, stem: str, day: Optional[dt.date] = None) -> str:
    """The one-line explanation a skipped run prints, naming the marker so the
    next person can see WHY it skipped and how to override."""
    return ("{} already went out today ({}) — skipping to avoid a duplicate. "
            "Pass --resend to send it again anyway.".format(
                what, path(stem, day).name))
