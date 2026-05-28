"""Ongoing Cancel — thin wrapper around the shared Metrics-thread poster.

Posts 'Ongoing Cancel' + image into today's 'Metrics M/DD' thread in
#alphalete-sales, and adds a 🔄 reaction on the parent (matches Eve's
manual emoji-per-metric flow)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from automations.shared import slack_metrics_post as _smp

# Re-export so anything that imported these from here keeps working.
SlackPostError = _smp.SlackPostError
CHANNEL_ID = _smp.CHANNEL_ID
TOKEN_PATH = _smp.TOKEN_PATH
_load_token = _smp._load_token
_client = _smp._client
find_metrics_thread_ts = _smp.find_metrics_thread_ts


def post_reply_with_image(image_path: Path,
                          today: dt.date | None = None,
                          dry_run: bool = False) -> dict:
    return _smp.post_reply_with_image(
        image_path,
        comment="Ongoing Cancel",
        react_emoji="arrows_counterclockwise",   # 🔄
        today=today,
        dry_run=dry_run,
    )
