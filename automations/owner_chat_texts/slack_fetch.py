"""Pull today's tracker PNGs back OUT of #alphalete-sales.

The trackers are captured on Lucy 3 and posted there every morning; this module
downloads those exact images so Lucy 1 can forward them to iMessage without a
second Tableau capture (the access budget is why — see
[[project_tableau_access_budget]]). Same picture the channel got, by
construction.

Reuses tableau_screenshots.slack_post's own thread finder + reply matcher, so
"which reply is which tracker" can never drift from how the poster decides it.

THE PNG-MAGIC CHECK IS LOAD-BEARING: a Slack token without `files:read` gets a
200 OK with a sign-in HTML page, not a 401 ([[reference_slack_files_read_html_page]]).
Without the check we would happily text HTML bytes into the owners' chat.

Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from automations.owner_chat_texts import config as cfg


class TrackerFetchError(RuntimeError):
    pass


def _download(url: str, token: str, dest: Path) -> Path:
    r = requests.get(url, headers={"Authorization": "Bearer %s" % token},
                     timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"\x89PNG"):
        head = r.content[:60].decode("utf-8", "replace")
        raise TrackerFetchError(
            "download of %s is not a PNG (starts %r). A 200 with HTML means "
            "this token lacks the files:read scope — add it and reinstall the "
            "Slack app." % (url[:80], head))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return dest


def fetch_tracker_pngs(day: dt.date, out_dir: Path
                       ) -> Tuple[List[Tuple[Dict, Path]], List[str]]:
    """Download today's posted tracker images, in channel post order.

    Returns (found, missing): found = [(spec, png_path)], missing = titles not
    in the thread yet (late data / capture failure on Lucy 3). Raises only when
    the thread itself can't be found or read — "no thread" and "no scope" are
    hard stops; one late tracker is not.
    """
    from automations.shared import slack_metrics_post as smp
    from automations.tableau_screenshots import slack_post as sp

    client = smp._client()
    token = smp._load_token()
    channel = cfg.source_channel()

    ts, _legacy = sp.find_thread_ts(client, channel, day)
    if not ts:
        raise TrackerFetchError(
            "no tracker thread in #alphalete-sales for %s yet — the Lucy 3 "
            "morning post hasn't happened. Re-run after it posts." % day)

    replies = sp._image_replies(client, channel, ts)
    found, missing = [], []
    for spec in cfg.tracker_specs():
        msg = next((m for m in replies if sp._reply_matches(m, spec, day)), None)
        fobj = None
        if msg:
            fobj = next((f for f in (msg.get("files") or [])
                         if f.get("url_private")), None)
        if not fobj:
            missing.append(spec.get("title") or spec.get("id"))
            continue
        dest = out_dir / ("%s.png" % spec["id"])
        _download(fobj["url_private"], token, dest)
        found.append((spec, dest))
    return found, missing
