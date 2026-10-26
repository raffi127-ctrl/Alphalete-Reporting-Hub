"""Local text outbox — a sheet-free handoff from a capture job to the poller.

Why this exists (2026-10-26): text_dispositions rows ride the Mini Control
Google Sheet, and that workbook stopped answering (every read and write timed
out at 180s). Lucy 2's NDS/Box texts sat 'queued' for hours, and every nds_oof
tick spent ~9 minutes per enqueue, so the knocks boards posted 20-40 minutes
late. Slack never broke — it doesn't touch the sheet. This gives texts the
same property.

Both halves live on the same machine (the capture job and the poller), so a
directory is all the queue we need: the job drops a ticket naming the manifest,
the poller drains the directory every loop — before AND after the sheet poll —
and sends through _action_text_dispositions, the identity that holds the
macOS Messages grant. Sends are idempotent (text_post drops a .sent marker),
so a retry after a crash can't double-text.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Callable, List, Tuple

OUTBOX_DIR = Path.home() / ".config" / "recruiting-report" / "text_outbox"
MAX_ATTEMPTS = 30          # ~1h of 2-min polls before a ticket is parked
_Send = Callable[[str], Tuple[bool, str]]


def drop(manifest_path, by: str, day: str | None = None) -> Path:
    """Queue one manifest for the poller. Returns the ticket path."""
    p = Path(manifest_path)
    day = day or p.parent.name          # manifests live under <out>/<YYYY-MM-DD>/
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    ticket = OUTBOX_DIR / ("%s_%s.json" % (stamp, p.stem))
    ticket.write_text(json.dumps({
        "manifest": p.name, "day": day, "by": by,
        "queued_at": dt.datetime.now().isoformat(timespec="seconds"),
        "attempts": 0, "last_error": ""}, indent=1))
    return ticket


def pending() -> List[Path]:
    if not OUTBOX_DIR.is_dir():
        return []
    return sorted(p for p in OUTBOX_DIR.glob("*.json") if p.is_file())


def drain(send: _Send, *, log: Callable[[str], None] = print,
          max_attempts: int = MAX_ATTEMPTS) -> Tuple[int, int]:
    """Send every pending ticket, oldest first. Returns (sent, still_pending).

    `send` is the poller's text_dispositions action: it takes "<manifest> <day>"
    and returns (ok, message). A ticket is removed on ok (including "already
    sent"); otherwise its attempt count is bumped and it is retried next loop,
    until max_attempts parks it under failed/ so a bad manifest can't block
    the ones behind it."""
    sent = left = 0
    for ticket in pending():
        try:
            info = json.loads(ticket.read_text())
        except Exception as e:  # noqa: BLE001 — a half-written ticket
            log("[outbox] %s unreadable (%s) — parked" % (ticket.name, type(e).__name__))
            _park(ticket)
            continue
        args = "%s %s" % (info.get("manifest", ""), info.get("day", ""))
        try:
            ok, msg = send(args.strip())
        except Exception as e:  # noqa: BLE001
            ok, msg = False, "%s: %s" % (type(e).__name__, str(e)[:200])
        if ok:
            log("[outbox] %s (by %s): %s" % (info.get("manifest"), info.get("by"), msg))
            ticket.unlink(missing_ok=True)
            sent += 1
            continue
        info["attempts"] = int(info.get("attempts") or 0) + 1
        info["last_error"] = msg[:300]
        log("[outbox] %s attempt %d FAILED: %s" % (info.get("manifest"), info["attempts"], msg[:200]))
        if info["attempts"] >= max_attempts:
            ticket.write_text(json.dumps(info, indent=1))
            _park(ticket)
            log("[outbox] %s parked after %d attempts" % (info.get("manifest"), info["attempts"]))
            continue
        ticket.write_text(json.dumps(info, indent=1))
        left += 1
    return sent, left


def _park(ticket: Path) -> None:
    failed = OUTBOX_DIR / "failed"
    failed.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ticket), str(failed / ticket.name))
