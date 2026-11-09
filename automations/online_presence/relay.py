"""Lucy's side of the relay for online presence: queue jobs, read answers.

Same admin key and the same 'Office Jobs' lane as office_admin and the
headshots (headshots/eco._call). The office's computer picks the job up on
its next ask (icd_alerts/office_jobs.py -> social_post.py).

ONLY OUR KINDS ARE EVER MARKED COLLECTED. The lane is shared with Sterling
invites and Apex weeks; marking one of theirs read would hide it from the
office admin flow that waits on it.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Dict, List

KINDS = ("zoho_signin", "social_check", "social_post")


def _call(extra: Dict) -> Dict:
    from automations.headshots import eco
    return eco._call(extra)


def enqueue(office: str, kind: str, payload: Dict, *, live: bool) -> str:
    if kind not in KINDS:
        raise ValueError(f"not an online-presence job: {kind!r}")
    out = _call({"office_job_enqueue": {"office": office, "kind": kind,
                                        "mode": "live" if live else "dry",
                                        "payload": payload}})
    if not out.get("ok"):
        raise RuntimeError(f"relay refused the {kind} job: {out.get('error')}")
    return str(out["job_id"])


def enqueue_post(office: str, caption: str, photo: Path, pages, *,
                 live: bool, thread_ts: str = "", media: str = "photo") -> str:
    """`photo` is the file to post -- a .jpg, or the reel's .mp4 with
    media="video". It rides the relay's existing photo field (bytes are
    bytes), so a reel needs no relay change."""
    return enqueue(office, "social_post", {
        "caption": caption, "pages": list(pages), "thread_ts": thread_ts,
        "media": media,
        "photo_b64": base64.b64encode(Path(photo).read_bytes()).decode()},
        live=live)


def answered() -> List[Dict]:
    """Our kinds that the office's computer has answered and we haven't read."""
    rows = _call({"office_job_results": True}).get("results") or []
    return [r for r in rows if r.get("kind") in KINDS and r.get("answered")]


def mark_read(job_ids: List[str]) -> None:
    if job_ids:
        _call({"office_job_collected": list(job_ids)})
