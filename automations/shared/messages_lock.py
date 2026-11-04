"""One iMessage send at a time on this machine.

WHY (2026-10-26): Mini Control grew a third lane, 'text', so a long report on
the main lane can no longer hold Carlos's NDS texts for hours. That makes two
processes on one Mac able to drive Messages.app at once: the text lane, and any
report the main lane runs that texts on its own (birthday reminders, sweeps).
Messages uploads attachments asynchronously and DROPS images silently when it
is crowded (text_post leaves IMAGE_SEND_DELAY_S between sends for exactly that
reason), and two senders interleaving AppleScript calls would also split one
post's header from its images. So every live send takes this lock first.

It also makes check-then-send de-dupes safe across processes: send_manifest
reads its .sent marker, sends, and writes the marker all under this lock, so
two drainers handed the same manifest send it once.

flock, released by the kernel if the holder dies, so a crash can't leave it
stuck. Reentrant within a process (send_manifest -> send_to_group nests). On
Windows there is no fcntl and no Messages.app either — it is a no-op there.
"""
from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

try:
    import fcntl as _fcntl
except ImportError:            # Windows — nothing to serialize
    _fcntl = None

LOCK_PATH = Path.home() / ".config" / "recruiting-report" / "messages_send.lock"
#: A post is a text plus a few images with a delay between each — well under a
#: minute. Ten minutes means something is wedged (an unanswered consent dialog
#: holds osascript for 5), and the caller should fail and retry rather than wait.
DEFAULT_WAIT_S = 600.0
_POLL_S = 1.0

_DEPTH = 0
_FD = None


class MessagesBusy(RuntimeError):
    """Another process held the Messages send lock for the whole wait."""


@contextlib.contextmanager
def held(label: str = "send", wait_s: float = DEFAULT_WAIT_S):
    """Hold the machine-wide Messages send lock for the block."""
    global _DEPTH, _FD
    if _DEPTH > 0:                      # already ours (a nested send)
        _DEPTH += 1
        try:
            yield
        finally:
            _DEPTH -= 1
        return
    fd = None
    if _fcntl is not None:
        try:
            LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o644)
        except Exception:  # noqa: BLE001 — never let the lock be the failure
            fd = None
    if fd is not None:
        start = time.monotonic()
        announced = False
        while True:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - start >= wait_s:
                    os.close(fd)
                    raise MessagesBusy(
                        "another process on this machine held Messages for "
                        "%ds — nothing sent; retry" % int(wait_s))
                if not announced:
                    print("[messages-lock] %s: another send is using Messages "
                          "— waiting" % label, flush=True)
                    announced = True
                time.sleep(_POLL_S)
    _DEPTH, _FD = 1, fd
    try:
        yield
    finally:
        _DEPTH, _FD = 0, None
        if fd is not None:
            try:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
            except Exception:  # noqa: BLE001
                pass
            try:
                os.close(fd)
            except Exception:  # noqa: BLE001
                pass
