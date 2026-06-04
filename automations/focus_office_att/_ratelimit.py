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
    Transient Google 5xx errors (500/502/503 "service unavailable"/504)
    are also retried with a short backoff — they're momentary server
    blips that succeed on a quick re-try, so one shouldn't fail a run.
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

# On a transient 5xx (Google-side blip, not a quota issue): short exponential
# backoff instead of the full per-minute wait — these clear in seconds. Give
# it a deeper budget than 429 so a longer outage (~1.5 min of 503s) still
# rides through instead of failing the run. Backoff: 1,2,4,8,16,30,30s.
_5XX_BACKOFF_CAP = 30.0
_5XX_MAX_RETRIES = 8

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


def _is_transient_5xx(exc: Exception) -> bool:
    """Transient Google-side server errors that succeed on a quick retry
    (e.g. APIError: [503]: The service is currently unavailable)."""
    s = str(exc)
    return any(code in s for code in ("[500]", "[502]", "[503]", "[504]"))


def install() -> None:
    """Wrap gspread's HTTP layer with pacing + retry + a read-cache.
    Idempotent — safe to call from every entrypoint."""
    global _installed
    if _installed:
        return
    import gspread.http_client as _hc

    _orig_request = _hc.HTTPClient.request

    def _call(self, method, args, kwargs):
        """Do the real request; retry transient failures.
        A 429 waits out the per-minute quota window (up to _MAX_RETRIES);
        a 5xx server blip gets a short exponential backoff with a deeper
        budget (_5XX_MAX_RETRIES). Anything else raises immediately."""
        attempt = 0
        while True:
            try:
                return _orig_request(self, method, *args, **kwargs)
            except Exception as exc:
                if _is_quota_429(exc) and attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_SLEEP)
                    attempt += 1
                    continue
                if _is_transient_5xx(exc) and attempt < _5XX_MAX_RETRIES - 1:
                    time.sleep(min(2 ** attempt, _5XX_BACKOFF_CAP))
                    attempt += 1
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

    # Marker so other entrypoints' lighter retry-only wrappers (e.g.
    # recruiting_report.fill) detect this fuller pacing+cache+retry layer
    # is already active and don't double-wrap the same chokepoint.
    _wrapped_request._sheets_retry_wrapped = True  # type: ignore[attr-defined]
    _hc.HTTPClient.request = _wrapped_request
    _installed = True
