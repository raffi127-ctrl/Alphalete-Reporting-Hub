"""Slack READS, retried through a truncated response body.

WHAT THIS IS FOR. Slack sometimes hands back a response that stops in the
middle: the headers promise 178,741 bytes and the connection closes after
74,352. Python surfaces that as `http.client.IncompleteRead`, and because it
comes up out of the socket rather than out of Slack's API, there is no
`ok: false` to check and no error code to branch on -- it is simply an
exception through the middle of whatever was reading.

It happened three times inside half an hour on 2026-09-20, to three different
callers (the mini's `slack_thread` action twice, and New-Start Thread Replies
at 08:01 and again at 08:32), which is what says it was Slack having a moment
rather than any one report being wrong.

TWO TRANSPORTS, AND THIS COVERS BOTH -- which it did not, for one commit, and
that cost a run. `slack_metrics_post._client` also installs a slack_sdk retry
handler for the same fault, and on 2026-09-20 the call sites here were unwrapped
on the reasoning that the handler made them redundant. The 09:30 run died anyway,
in `thread.find_anchor`, on `conversations.history`:

    File ".../automations/new_start_followup/thread.py", line 116, in find_anchor
    http.client.IncompleteRead: IncompleteRead(74352 bytes read, 104398 more expected)

and slack_sdk never logged its own "Failed to send a request to Slack API
server", which it emits on every attempt that reaches the branch where retry
handlers are consulted. So on that machine the handler was never asked.

The likeliest reason is version skew: `requirements.txt` says `slack_sdk>=3.21`,
unpinned, and the generic `except Exception` branch that consults retry handlers
is a later addition -- the fleet's py3.9 venvs were built at different times, so
"the client retries this" is a claim about whatever slack_sdk that box happens
to have. Not something to bet a report on. Retry HERE, in code we ship, and let
the handler be a bonus where it exists. A read is idempotent, so the worst case
of both firing is a few extra seconds on a path that is already failing.

The file download needs this for a plainer reason: `url_private_download` is
fetched with `requests`, outside slack_sdk entirely, where no handler of any
version can reach it.

READS ONLY, AND THAT IS THE WHOLE POINT. A truncated read can be asked for
again with no consequence -- nobody sees a second download. A truncated WRITE
cannot: the request may well have landed before the body came apart, so
retrying it is how one post becomes two in front of the team. Nothing here is
safe to wrap around a post, an upload, or a reaction, and the helper
deliberately does not offer a version that is.

WHAT IS NOT RETRIED. An HTTP error (a 403 from a token without files:read, a
sign-in page instead of the image) is a real fault that retrying only makes
slower, and a timeout is a different signal -- the caller's own timeout already
bounds it, and tripling a 60-second wait to chase a case we have not actually
seen costs more than it saves. Only the transport coming apart mid-body is
retried here.
"""
from __future__ import annotations

import http.client
import time
from typing import Callable, Optional

# Matched by NAME as well as by type, because the same fault arrives wearing a
# different class depending on which HTTP stack the caller used: slack_sdk goes
# through urllib and raises `http.client.IncompleteRead` bare, while `requests`
# wraps it in ChunkedEncodingError (or ProtocolError, from urllib3). Importing
# requests/urllib3 here to name those types would put a hard dependency into a
# shared module that some callers reach on the stdlib alone.
_TRANSIENT_NAMES = frozenset({
    "IncompleteRead",           # the one actually observed, 2026-09-20
    "ChunkedEncodingError",     # requests' wrapper around it
    "ProtocolError",            # urllib3's
    "RemoteDisconnected",       # the connection closed before the body started
    "ConnectionResetError",
    "ConnectionError",          # requests' (and the builtin)
})

_TRIES = 3
_BASE_DELAY = 1.0          # 1s, 2s — ~3s worst case, inside any report's tick


def _chain(err: BaseException):
    """`err` and everything it was raised from, deepest last.

    Walked because the interesting exception is usually the INNER one: requests
    raises ChunkedEncodingError `from` the IncompleteRead, and a wrapper two
    layers up would otherwise hide the only name we can recognise.
    """
    seen, cur = [], err
    while cur is not None and cur not in seen:
        seen.append(cur)
        cur = cur.__cause__ or cur.__context__
    return seen


def is_transient(err: BaseException) -> bool:
    """True when this is the body coming apart, not Slack saying no."""
    for e in _chain(err):
        if isinstance(e, http.client.IncompleteRead):
            return True
        if type(e).__name__ in _TRANSIENT_NAMES:
            return True
    return False


def describe(err: BaseException) -> str:
    """One line naming the fault, for a log that a person reads later."""
    for e in _chain(err):
        if isinstance(e, http.client.IncompleteRead):
            return ("Slack's response stopped early ({} of {} bytes)"
                    .format(len(e.partial),
                            len(e.partial) + (e.expected or 0)))
    return "{}: {}".format(type(err).__name__, str(err)[:160])


# HOW MANY MESSAGES TO ASK FOR IN ONE GO. 50, not Slack's 200 maximum.
#
# WHY (2026-09-20, after the retry above turned out not to be enough). The
# roster finder asks #11280 for `limit=200`, which on that channel is now a
# ~180 KB response, and on Lucy 1 it truncates at ~66-75 KB EVERY TIME:
#
#   17:03  74040 of 180027 — retrying in 1s (1/2)
#          74664 of 180037 — retrying in 2s (2/2)
#          then INCOMPLETE
#
# Three attempts, three truncations at the same size. That is not a wobble a
# retry can ride out, and the same call answers 5/5 from a laptop, so it is the
# size of the response on that machine's network stack -- not Slack refusing.
# The response is also GROWING (178,741 bytes this morning, 180,037 by evening)
# as the channel fills, so the day it started failing was the day it crossed
# whatever that box's ceiling is, and it will not come back on its own.
#
# 50 keeps a page near 45 KB, comfortably under the ~66 KB floor of every
# truncation seen. The retry stays for the genuinely transient case.
PAGE = 50


def read_paged(fn: Callable, *, limit: int, page: int = PAGE,
               _log: Optional[Callable[[str], None]] = None,
               **kwargs) -> dict:
    """`fn` with cursor paging, returning one merged {"messages": [...]}.

    Asks for `limit` messages in pages of `page`, following Slack's
    `response_metadata.next_cursor`, and stops early when a page comes back
    short (that is the end of the channel). Each page is retried by read()
    above, so a genuine wobble on one page still recovers.

    The caller sees exactly what a single `limit=` call would have returned, so
    this is a drop-in for one -- only the wire traffic changes.
    """
    out: list = []
    cursor = None
    while len(out) < limit:
        want = min(page, limit - len(out))
        call = dict(kwargs, limit=want)
        if cursor:
            call["cursor"] = cursor
        resp = read(fn, _log=_log, **call)
        batch = resp.get("messages") or []
        out.extend(batch)
        cursor = ((resp.get("response_metadata") or {}).get("next_cursor") or "")
        if not cursor or len(batch) < want:
            break          # end of the channel, not a short read
    return {"messages": out[:limit]}


def read(fn: Callable, *args,
         _tries: int = _TRIES,
         _base_delay: float = _BASE_DELAY,
         # Resolved at CALL time, not bound as a default: a default argument is
         # evaluated once at import, so `time.sleep` captured here could never
         # be patched out and every test would really sleep.
         _sleeper: Optional[Callable[[float], None]] = None,
         _log: Optional[Callable[[str], None]] = None,
         **kwargs):
    """Call `fn(*args, **kwargs)`, again if the response body came apart.

    The knobs are underscore-prefixed so they can never collide with the Slack
    parameter names that go through **kwargs (`channel`, `ts`, `limit`, ...).

    Re-raises the last error once the retries are spent, and re-raises anything
    non-transient immediately, so the caller still sees the real exception --
    this widens the number of attempts, never the number of failures that get
    swallowed.
    """
    last = None
    for attempt in range(1, max(1, _tries) + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — re-raised below either way
            if not is_transient(exc):
                raise
            last = exc
            if attempt >= _tries:
                break
            delay = _base_delay * (2 ** (attempt - 1))
            if _log:
                _log("  {} — retrying in {:.0f}s ({}/{})".format(
                    describe(exc), delay, attempt, _tries - 1))
            (_sleeper or time.sleep)(delay)
    raise last
