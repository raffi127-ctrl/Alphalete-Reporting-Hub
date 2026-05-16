"""Google Sheets API pacing + retry + read-cache for the focus-office run.

The focus-office design pass fires hundreds of Sheets calls per run and
re-reads the same ranges repeatedly. Left alone it blows past Google's
per-minute quota and 429s — failing ops or, with the old op-level
retries, grinding for 20 minutes.

This wraps gspread's single HTTP chokepoint (HTTPClient.request) with
three layers, all invisible to callers:

  * PACE  — keep calls under the per-minute quota so most 429s never
    happen in the first place.
  * RETRY — if a 429 slips through anyway (other tabs/teammates also
    consume the same quota), wait out the window and retry. So a 429
    can never reach the design code — worst case it's a short wait.
  * CACHE — a repeated GET for the same range is served from memory.
    ANY write clears the whole cache first, so a read after a write is
    always fresh; the cache can never serve stale data.

It never alters a request or a response. Install once via install().
"""
from __future__ import annotations

import threading
import time

# Google Sheets API v4: ~300 read + ~300 write requests / minute / user.
# Pace each bucket to 270 — under quota, with headroom.
_LIMIT_PER_MIN = 270
_WINDOW = 60.0

# On a 429 that slips past pacing: wait this long (quota is per-minute) and
# retry, up to this many times.
_RETRY_SLEEP = 40.0
_MAX_RETRIES = 5

_lock = threading.Lock()
_calls: dict[str, list[float]] = {"read": [], "write": []}
_cache: dict[str, object] = {}
_installed = False


def _pace(method: str) -> None:
    """Block until issuing one `method` call stays under quota.
    Sliding 60s window, separate buckets for reads (GET) and writes."""
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


def _is_quota_429(exc: Exception) -> bool:
    s = str(exc)
    return "429" in s and "quota" in s.lower()


def install() -> None:
    """Wrap gspread's HTTP layer with pacing + retry + a read-cache.
    Idempotent — safe to call from every entrypoint."""
    global _installed
    if _installed:
        return
    import gspread.http_client as _hc

    _orig_request = _hc.HTTPClient.request

    def _call(self, method, args, kwargs):
        """Do the real request; on a 429, wait out the window and retry."""
        for attempt in range(_MAX_RETRIES):
            try:
                return _orig_request(self, method, *args, **kwargs)
            except Exception as exc:
                if _is_quota_429(exc) and attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_SLEEP)
                    continue
                raise

    def _wrapped_request(self, method, *args, **kwargs):
        if str(method).lower() == "get":
            key = repr((args, tuple(sorted(kwargs.items()))))
            with _lock:
                if key in _cache:
                    return _cache[key]
            _pace("get")
            resp = _call(self, method, args, kwargs)
            with _lock:
                _cache[key] = resp
            return resp
        # Any write (non-GET) invalidates every cached read first, so a
        # read after a write is always fresh — the cache can't go stale.
        with _lock:
            _cache.clear()
        _pace(method)
        return _call(self, method, args, kwargs)

    _hc.HTTPClient.request = _wrapped_request
    _installed = True
