"""Put the cross-reference in the day's ':wolf: Alphalete Production' thread.

ONE message carrying BOTH images, which is what `files_upload_v2` does when it's
handed a `file_uploads` list — uploading them one at a time would put the text in
one reply and the pictures in two more, and the tagged reps would get three
notifications for one check.

The thread is found, never created. It is the daily production post's own thread
(slack_post.find_thread_ts, which paginates a busy channel's whole day), and if
it isn't there yet this holds rather than starting a second 🐺 thread for the
same morning — a duplicate thread splits the day's images in half and nobody can
tell which one is the real one.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from automations.alphalete_production import slack_post as SP

CHANNEL = SP.CHANNEL              # #alphalete-sales


def thread_ts(client, day: dt.date, channel: str) -> str:
    """The 🐺 thread for the MORNING AFTER `day` — the post is a reply in the
    thread whose images cover that sale day."""
    posted_on = day + dt.timedelta(days=1)
    ts = SP.find_thread_ts(client, channel, posted_on)
    if not ts:
        raise RuntimeError(
            f"no {SP.header_title(posted_on)!r} thread in {channel} — the daily "
            "production post hasn't gone out yet. Holding: this reply belongs "
            "in that thread, and starting a second one would split the morning.")
    return ts


def post(client, res, text: str, images: list[Path], *,
         channel: str | None = None) -> dict:
    """One threaded reply: the text plus every image, as the token's own user."""
    ch = channel or CHANNEL
    ts = thread_ts(client, res.day, ch)
    uploads = [{"file": str(p), "filename": p.name} for p in images]
    resp = client.files_upload_v2(
        channel=ch, thread_ts=ts, initial_comment=text, file_uploads=uploads)
    return {"ok": resp.get("ok"), "channel": ch, "thread_ts": ts,
            "files": [f.get("id") for f in (resp.get("files") or [])]}


def dm(client, user: str, text: str, images: list[Path]) -> dict:
    """The same message + images, to ONE person's DM instead of the thread.

    This is the sandbox: the post is mrkdwn with mentions and two attachments,
    and the only way to know it renders right is to look at it in Slack. A DM is
    the one place that can be done without notifying five people. NOTE the tags
    in the text stay real — a mention inside a DM does not notify the person
    mentioned, so this is safe to send to yourself.
    """
    from automations.shared.slack_metrics_post import _resolve_user_id
    uid = _resolve_user_id(client, user) if not user.startswith(("U", "W")) else user
    ch = client.conversations_open(users=uid)["channel"]["id"]
    banner = ("*(PREVIEW — this is what will post in the day's 🐺 thread; "
              "nothing has posted to the channel.)*\n\n")
    resp = client.files_upload_v2(
        channel=ch, initial_comment=banner + text,
        file_uploads=[{"file": str(p), "filename": p.name} for p in images])
    return {"ok": resp.get("ok"), "channel": ch, "thread_ts": "", "dm_to": uid}
