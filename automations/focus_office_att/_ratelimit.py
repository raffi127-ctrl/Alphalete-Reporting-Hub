"""Proactive Google Sheets API rate limiter.

The focus-office design pass fires hundreds of Sheets calls per run; left
unpaced it blows past Google's per-minute quota and 429-storms (which the
65s-retry then turns into a 20-minute grind).

This paces calls to stay UNDER the quota so 429s never happen in the first
place. It only ever sleeps — it never alters a request or a response, so it
cannot affect correctness. Worst case it waits; it can never corrupt data.

Install once per process via install(); it wraps gspread's single HTTP
chokepoint (HTTPClient.request), so every read and write is paced.
"""
from __future__ import annotations

import threading
import time

# Google Sheets API v4 allows ~300 read + ~300 write requests / minute / user.
# We pace each bucket to 270 — comfortably under, leaving headroom for the
# Hub itself and other teammates hitting the same project.
_LIMIT_PER_MIN = 270
_WINDOW = 60.0

_lock = threading.Lock()
_calls: dict[str, list[float]] = {"read": [], "write": []}
_installed = False


def _pace(method: str) -> None:
    """Block until issuing one `method` call keeps us under the quota.

    Sliding 60s window, separate buckets for reads (GET) and writes.
    """
    bucket = "read" if str(method).lower() == "get" else "write"
    while True:
        with _lock:
            now = time.time()
            q = _calls[bucket]
            cutoff = now - _WINDOW
            drop = 0
            while drop < len(q) and q[drop] < cutoff:
                drop += 1
            if drop:
                del q[:drop]
            if len(q) < _LIMIT_PER_MIN:
                q.append(now)
                return
            wait = q[0] + _WINDOW - now
        time.sleep(max(wait, 0.05))


def install() -> None:
    """Monkeypatch gspread so every Sheets API call is paced. Idempotent —
    safe to call from every entrypoint."""
    global _installed
    if _installed:
        return
    import gspread.http_client as _hc

    _orig_request = _hc.HTTPClient.request

    def _paced_request(self, method, *args, **kwargs):
        _pace(method)
        return _orig_request(self, method, *args, **kwargs)

    _hc.HTTPClient.request = _paced_request
    _installed = True
