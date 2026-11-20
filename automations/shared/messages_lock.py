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

# SALE ALERTS GO NEXT (Carlos 2026-11-19). The lock is not a queue: whoever
# polls first after a release wins, so a sale text could sit behind picture
# after picture of the half-hourly knocks boards (~18s each on Lucy 1). A
# process holding a text a rep is waiting on marks itself with priority();
# every other sender, before it takes the lock for its NEXT post, stands aside
# while that mark is live. Nothing is cut mid-post -- a board's header and its
# pictures still travel together -- it only changes who goes next.
#: How long a sender stands aside before going anyway. A sale burst is a few
#: texts; this only stops a wedged priority holder from starving the boards.
PRIORITY_YIELD_MAX_S = 120.0
#: A mark older than this is a crash leftover, not a text in hand.
PRIORITY_STALE_S = 600.0

_DEPTH = 0
_FD = None


class MessagesBusy(RuntimeError):
    """Another process held the Messages send lock for the whole wait."""


def _priority_path() -> Path:
    # From LOCK_PATH at call time, so a test that moves the lock moves this.
    return LOCK_PATH.with_suffix(".priority")


def _priority_holder() -> "int | None":
    """The pid of ANOTHER live process with a fresh priority mark, else None."""
    path = _priority_path()
    try:
        if time.time() - path.stat().st_mtime > PRIORITY_STALE_S:
            return None
        pid = int(path.read_text().split()[0])
    except Exception:  # noqa: BLE001 — no mark, or an unreadable one
        return None
    if pid == os.getpid():
        return None
    try:
        os.kill(pid, 0)
    except PermissionError:
        pass                      # alive, just not ours to signal
    except Exception:  # noqa: BLE001 — gone: a crash leftover
        return None
    return pid


@contextlib.contextmanager
def priority(label: str = "sale alerts"):
    """Ask every other sender on this machine to let this process go next.

    Hold it only while a text is actually in hand (resolving the group and
    sending it): the mark makes everyone else wait, so holding it idle would
    stall the boards for nothing. One holder at a time is assumed -- the
    credit-check poster, which its own run lock already keeps single.
    """
    if _fcntl is None:            # Windows: no Messages, nothing to order
        yield
        return
    path = _priority_path()
    mine = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("%d %s\n" % (os.getpid(), label))
        mine = True
    except Exception:  # noqa: BLE001 — never let the mark be the failure
        pass
    try:
        yield
    finally:
        if mine:
            try:
                if int(path.read_text().split()[0]) == os.getpid():
                    path.unlink()
            except Exception:  # noqa: BLE001
                pass


def _stand_aside(label: str) -> None:
    start = time.monotonic()
    told = False
    while (_priority_holder() is not None
           and time.monotonic() - start < PRIORITY_YIELD_MAX_S):
        if not told:
            print("[messages-lock] %s: a sale alert is texting — letting it "
                  "go first" % label, flush=True)
            told = True
        time.sleep(_POLL_S)


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
        _stand_aside(label)       # before the clock: yielding is not "busy"
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
