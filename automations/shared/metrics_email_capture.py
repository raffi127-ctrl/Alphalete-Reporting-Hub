"""Catch the boards a metric run would have posted to Slack, so they can be
emailed instead.

WHY AN INTERCEPT AND NOT A SECOND DELIVERY PATH IN EVERY MODULE. An office's
daily metrics are eleven-ish SEPARATE subprocesses (runner.metrics_for), each of
which pulls Tableau, fills the office's Sheet, renders a PNG and posts it through
shared.slack_metrics_post. Teaching each of those modules to also email would be
eleven copies of the same decision, drifting the moment one is edited — and the
runner would have no way to send ONE message for the day, which is the whole point
(an inbox has no thread to collapse eleven mails into).

So the delivery point is intercepted instead, at the ONE function every board
already goes through. With METRICS_EMAIL_DIR set in the environment, the post
helpers in slack_metrics_post hand the board here rather than to Slack: the PNG is
copied into that directory and a line is appended to manifest.jsonl. Every metric
still runs its FULL live path — the Tableau pull, the Sheet fill, the render, the
per-board error handling — and the runner mails the captured set when they finish.
A module that never learns it exists is a module that cannot get this wrong.

The env var is the switch because the metrics are subprocesses: an env var is the
only thing that crosses that boundary without every call site passing a flag.

Not a dry run. --dry-run means "don't do the work"; this means "do all of it and
deliver it somewhere else", which is why capture happens after the render rather
than instead of it.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path

ENV_DIR = "METRICS_EMAIL_DIR"
MANIFEST = "manifest.jsonl"


def active() -> "Path | None":
    """The capture directory when this run delivers by email, else None.

    Created on demand: the runner sets the variable, and whichever subprocess
    posts first makes the directory, so no ordering between them matters.
    """
    raw = (os.environ.get(ENV_DIR) or "").strip()
    if not raw:
        return None
    d = Path(raw)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _append(d: Path, row: dict) -> None:
    row.setdefault("at", dt.datetime.now().isoformat(timespec="seconds"))
    with (d / MANIFEST).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _next_seq(d: Path) -> int:
    """Position in the day's set. Read off the manifest rather than kept in
    memory because each board is written by a DIFFERENT process — the sequence
    has to live where all of them can see it."""
    f = d / MANIFEST
    if not f.exists():
        return 1
    return sum(1 for line in f.read_text(encoding="utf-8").splitlines()
               if line.strip()) + 1


def _safe(name: str) -> str:
    keep = [c if (c.isalnum() or c in " -_.") else "-" for c in str(name)]
    return "".join(keep).strip().replace(" ", "-")[:70] or "board"


def record_header(text: str, *, sections=None) -> dict:
    """The thread header. Kept because it is the day's promise of what is coming:
    the email's intro lists the same boards, so a board that never rendered is
    still visibly owed rather than silently absent."""
    d = active()
    if d is None:
        return {}
    row = {"kind": "header", "seq": 0, "text": text,
           "sections": list(sections or [])}
    # The header is written once per run; a re-run of a single metric must not
    # append a second one (it would double the intro).
    f = d / MANIFEST
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("kind") == "header":
                    return {"captured": True, "header": True, "existed": True}
            except Exception:                        # noqa: BLE001
                continue
    _append(d, row)
    return {"captured": True, "header": True, "existed": False}


# Suffixes a mail client can draw inline. Everything else is a FILE — the
# Order Log posts an .xlsx, and slack_metrics_post.post_reply_with_file routes
# through here for exactly those: spreadsheets, CSVs, PDFs. Recording one as
# kind "image" made the digest embed it, PIL raised UnidentifiedImageError, and
# the whole send died with five good boards already on disk (Joseph, 2026-09-14
# — his office's first week on the email path, and the first time a non-image
# board reached this function).
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def is_drawable(file_name) -> bool:
    """Can a mail client draw this, by its name alone? The one definition, used
    both when a board is captured and when the digest reads a directory back —
    a capture written before this distinction existed still has to be read
    correctly, and that older directory is what a recovery re-send works from."""
    return Path(str(file_name or "")).suffix.lower() in _IMAGE_SUFFIXES


def record_image(image_path, *, comment: str = "", react_emoji: str = "",
                 file_name: str = "") -> dict:
    """Copy a board into the capture directory and log its caption.

    COPIED, not referenced: the renderers write into shared output/ paths that a
    later office (or tomorrow's run) overwrites, so a path recorded now can point
    at someone else's board by the time the mail is built.

    Records kind "image" for something drawable and kind "file" for anything
    else, so the digest can attach a spreadsheet instead of trying to draw it.
    """
    d = active()
    if d is None:
        return {}
    src = Path(image_path)
    seq = _next_seq(d)
    dest = d / f"{seq:02d}-{_safe(comment or file_name or src.stem)}{src.suffix or '.png'}"
    try:
        shutil.copyfile(src, dest)
    except Exception as e:                           # noqa: BLE001
        # A board we could not copy is a MISSING board, not a crashed run — the
        # mail says so on its own line and the other boards still go out.
        _append(d, {"kind": "missing", "seq": seq, "label": comment,
                    "error": f"{type(e).__name__}: {e}"})
        return {"captured": True, "ok": False, "error": str(e)}
    kind = "image" if is_drawable(dest.name) else "file"
    _append(d, {"kind": kind, "seq": seq, "label": comment,
                "file": dest.name, "react": react_emoji})
    return {"captured": True, "ok": True, "file": str(dest)}


def record_text(text: str, *, react_emoji: str = "") -> dict:
    """A text-only reply — the 'nothing new today' one-liner some boards post
    instead of an empty image. It is a real section of the day, so it belongs in
    the mail; dropping it would make the board look like it never ran."""
    d = active()
    if d is None:
        return {}
    seq = _next_seq(d)
    _append(d, {"kind": "text", "seq": seq, "text": text, "react": react_emoji})
    return {"captured": True, "ok": True}


def entries(d: "Path | str") -> list:
    """Everything captured, in post order. Malformed lines are skipped rather
    than raising — a half-written line must not cost the whole day's email."""
    d = Path(d)
    f = d / MANIFEST
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:                            # noqa: BLE001
            continue
    return sorted(out, key=lambda r: r.get("seq", 0))


def header_row(d: "Path | str") -> dict:
    for r in entries(d):
        if r.get("kind") == "header":
            return r
    return {}


def board_rows(d: "Path | str") -> list:
    """The boards, in order — images, text replies and misses alike."""
    return [r for r in entries(d) if r.get("kind") != "header"]
