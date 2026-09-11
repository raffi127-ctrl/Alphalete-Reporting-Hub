"""Opening the AUTOMATION MASTER workbook, with the retry it has always needed.

Every Lucy job, every queue tab, every diag dump and all three ICD-facing
Streamlit forms read the SAME workbook. Google's per-user read quota is shared
across all of them, so a plain `open_by_key` is a coin flip at busy moments: it
comes back 429 (rate limited) or a transient 5xx, and whatever called it blows
up. On 2026-09-11 that took out both finalize links for Joseph Logan's
onboarding at once — the tracker form showed a redacted traceback, the metrics
form showed an empty form (it swallowed the error into "no requests").

A rate limit is not an outage, it's a "wait a second". So: back off and retry
the retryable codes, and when it really is dead, hand the caller a sentence a
non-technical person can act on instead of a stack trace.

[[reference_sheets_write_quota_429]]
"""
from __future__ import annotations

import time
from typing import Callable, Optional

# 429 = per-minute read/write quota. 5xx = Google's backend wobbling. Both clear
# on their own. Everything else (403 lost access, 404 wrong id, 401 dead token)
# is a real fault that retrying only makes slower — surface it immediately.
RETRYABLE = (429, 500, 502, 503, 504)

_TRIES = 4
_BASE_DELAY = 1.0          # 1s, 2s, 4s — ~7s worst case, under any form's patience


def status_code(err: BaseException) -> Optional[int]:
    """The HTTP status behind a gspread APIError, or None if it isn't one.

    gspread has moved this around between versions (`.code` in 6.x, only
    `.response.status_code` in 5.x), so read both rather than pinning a version.
    """
    code = getattr(err, "code", None)
    if isinstance(code, int):
        return code
    resp = getattr(err, "response", None)
    code = getattr(resp, "status_code", None)
    return code if isinstance(code, int) else None


def is_retryable(err: BaseException) -> bool:
    return status_code(err) in RETRYABLE


def explain(err: BaseException) -> str:
    """One plain sentence for a form to show an ICD or Megan. No stack trace,
    no redacted-error boilerplate — what happened and what to do about it."""
    code = status_code(err)
    if code == 429:
        return ("Google rate-limited us reading the master sheet (too many "
                "requests at once). Nothing is lost — wait a few seconds and "
                "reload this page.")
    if code in (500, 502, 503, 504):
        return ("Google Sheets is having a moment (server error {}). Nothing "
                "is lost — reload this page in a minute.".format(code))
    if code == 403:
        return ("This app's Google login can't open the master sheet anymore "
                "(permission denied). That needs Megan — the sheet's sharing "
                "or the app's saved login has changed.")
    if code == 404:
        return ("The master sheet id this app is pointed at doesn't exist. "
                "That needs Megan.")
    if code == 401:
        return ("This app's saved Google login has expired. That needs Megan "
                "— the app's `gcp_oauth` secret has to be re-minted.")
    return "Couldn't read the master sheet: {}: {}".format(
        type(err).__name__, str(err)[:200])


def open_sheet(client, sheet_id: str, *, tries: int = _TRIES,
               base_delay: float = _BASE_DELAY,
               sleeper: Callable[[float], None] = time.sleep):
    """`client.open_by_key(sheet_id)`, retried through the transient failures.

    Re-raises the last error once the retries are spent (or immediately, for a
    non-retryable one) so the caller still sees the real exception — callers
    that face a human should catch it and show `explain(err)`.
    """
    last: BaseException
    for attempt in range(tries):
        try:
            return client.open_by_key(sheet_id)
        except Exception as e:                        # noqa: BLE001
            last = e
            if attempt == tries - 1 or not is_retryable(e):
                raise
            sleeper(base_delay * (2 ** attempt))
    raise last                                        # pragma: no cover
