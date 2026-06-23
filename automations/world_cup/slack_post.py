"""Post the two World Cup bracket PDFs to Slack.

One message per channel — "🏆 World Cup 2026 — Round N" with both PDFs
(Alphalete + Public) attached — to #alphalete-sales and #alphalete-lvl1-chat.
Reuses the shared xoxp user token + WebClient from slack_metrics_post (posts as
Eve / Evelyn Sobrino, same identity as the other report posts).

files_upload_v2's `file_uploads` list uploads both PDFs under a single
`initial_comment`, so each channel gets one message with two attachments.
"""
from __future__ import annotations

from pathlib import Path

# name -> channel id (both private; creator Rafael Hidalgo). Resolved 2026-06-10.
CHANNELS = {
    "alphalete-sales": "C068PH3RFSM",
    "alphalete-lvl1-chat": "C09JG28CD27",
}


def _comment(round_label: str) -> str:
    return f"🏆 World Cup 2026 — {round_label}"


def _resolve_dest(client, dest: str) -> str:
    """A user ID (U…) is resolved to its DM channel via conversations_open so
    files_upload_v2 lands in that DM. Channel/DM/group IDs (C/D/G…) pass
    through unchanged."""
    if dest.startswith("U"):
        resp = client.conversations_open(users=dest)
        return resp["channel"]["id"]
    return dest


def post_round(alpha_pdf: Path, public_pdf: Path, round_num: int,
               dry_run: bool = False, test_channel: str | None = None) -> dict:
    """Post one message ("🏆 World Cup 2026 — Round N" + both PDFs) per target.

    Default targets are the two real channels. `test_channel` overrides them
    with a SINGLE destination (a channel ID, or a user ID — resolved to that
    user's DM) — for a safe test post before going live. dry_run returns the
    plan without posting."""
    comment = _comment(round_num)
    file_specs = [
        {"path": alpha_pdf, "title": alpha_pdf.stem},
        {"path": public_pdf, "title": public_pdf.stem},
    ]
    targets = {"test": test_channel} if test_channel else dict(CHANNELS)

    if dry_run:
        return {
            "dry_run": True,
            "comment": comment,
            "channels": targets,
            "files": [f["path"].name for f in file_specs],
        }

    from automations.shared import slack_metrics_post as smp
    client = smp._client()

    uploads = [
        {"file": str(f["path"]), "filename": f["path"].name, "title": f["title"]}
        for f in file_specs
    ]

    results = {}
    for name, dest in targets.items():
        cid = _resolve_dest(client, dest)
        resp = client.files_upload_v2(
            channel=cid,
            initial_comment=comment,
            file_uploads=uploads,
        )
        results[name] = {"target": dest, "channel": cid, "ok": resp.get("ok")}
    return {"posted": True, "comment": comment, "test": bool(test_channel),
            "results": results}
