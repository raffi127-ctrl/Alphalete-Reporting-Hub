"""A lock two MACHINES can both see, built on the shared control workbook.

WHY THIS EXISTS (2026-08-20). `slack_post._ChannelPostLock` stops two overlapping
runs on ONE machine from double-posting a tracker thread, because `flock` is
local — and that is exactly its limit. Lucy 1 running the trackers while the same
report is kicked off from the laptop is a normal day here, and those two never
see each other's lock. #ambient-sales-1 and #aeon-sales each got all eight boards
twice; a local lock would not have prevented it if the second run had been on the
other machine.

THE SUBSTRATE is the one thing both machines already reach: the Mini Control
workbook (`mini_control.CONTROL_SHEET_ID`) via `recruiting_report.fill._client()`
— gspread, works from any machine, already how the mini takes commands.

THE PROTOCOL is append-then-read-back arbitration, because Sheets has no
compare-and-swap:

  1. read the rows for this key; if a LIVE claim that isn't ours is there, wait
  2. append OUR claim row (an append always gets its own row — two racing
     appends produce two rows, never one clobbered cell)
  3. read back. The winner is the LOWEST ROW INDEX for the key. Both racers read
     the same sheet and compute the same winner, so exactly one proceeds.
  4. loser deletes its own row, backs off, retries from 1
  5. holder deletes its row on release

A LEASE (`ttl_s`) covers the case this is really guarding against: a run that
crashes or is killed mid-post never releases, and without an expiry it would wedge
that report for everyone until someone noticed. A claim older than the lease is
treated as abandoned and stepped over.

BEST-EFFORT, ALWAYS. Every failure path here — no network, no credentials, a
Sheets 429, a malformed row — must end in "carry on without the lock", never in a
report that doesn't post. The failure this prevents is duplicate images; the
failure it must never cause is silence. Same rule the local lock follows.

COST is deliberately ~4 API calls per RUN, not per channel: the thing that must
not overlap is two whole runs. Per-channel claims would be ~60 calls a run, which
on this workbook is how you earn a 429 — a worse outage than the duplicates.
[[reference_sheets_write_quota_429]]
"""
from __future__ import annotations

import datetime as dt
import os
import socket
import time

LOCK_TAB = "Post Locks"
HEADERS = ["Key", "Holder", "Claimed At", "Note"]

DEFAULT_TTL_S = 45 * 60          # a tracker run is minutes; an hour is abandoned
DEFAULT_WAIT_S = 15 * 60
POLL_S = 10.0


def holder_id() -> str:
    """Who we are, specifically enough to tell two machines apart in the sheet."""
    try:
        host = socket.gethostname()
    except Exception:            # noqa: BLE001
        host = "unknown-host"
    return "{}/{}".format(host, os.getpid())


def _ws():
    """The lock worksheet, created on first use. Raises — callers treat any
    exception as 'no shared lock available' and continue unlocked."""
    import gspread

    from automations.day_orchestrator.mini_control import CONTROL_SHEET_ID
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
    try:
        return sh.worksheet(LOCK_TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=LOCK_TAB, rows=200, cols=len(HEADERS))
        ws.update([HEADERS], "A1")
        return ws


def _parse_ts(s: str):
    try:
        return dt.datetime.fromisoformat((s or "").strip())
    except Exception:            # noqa: BLE001 — an unreadable stamp is stale
        return None


class SharedLock:
    """Cross-machine mutual exclusion for `key`, as a context manager.

    `acquired` says whether we actually hold it. It is False both when someone
    else holds it past our patience AND when the sheet was unreachable — the
    caller carries on either way, so the attribute is for logging, not control
    flow. Re-entrant within one process: nested acquisitions of the same key are
    no-ops, so a run that posts to 15 orgs claims once, not fifteen times."""

    _held: set = set()           # keys this PROCESS already holds

    def __init__(self, key: str, *, ttl_s: float = DEFAULT_TTL_S,
                 wait_s: float = DEFAULT_WAIT_S, note: str = "", log=print):
        self.key, self.ttl_s, self.wait_s = key, ttl_s, wait_s
        self.note, self.log = note, log
        self.me = holder_id()
        self.acquired = False
        self._reentrant = False
        self._ws = None

    # -- sheet helpers: every one returns a value, never raises -------------
    def _rows(self):
        """[(row_number, holder, claimed_at_str)] for this key, sheet order."""
        try:
            vals = self._ws.get_all_values()
        except Exception:        # noqa: BLE001
            return None
        out = []
        for i, r in enumerate(vals[1:], start=2):
            if (r[0] if r else "").strip() == self.key:
                out.append((i, (r[1] if len(r) > 1 else "").strip(),
                            (r[2] if len(r) > 2 else "").strip()))
        return out

    def _live(self, rows):
        """Claims that haven't outlived the lease."""
        now, live = dt.datetime.now(), []
        for rownum, who, ts in rows:
            t = _parse_ts(ts)
            if t is not None and (now - t).total_seconds() < self.ttl_s:
                live.append((rownum, who, ts))
        return live

    def _drop(self, rownum: int):
        try:
            self._ws.delete_rows(rownum)
            return True
        except Exception:        # noqa: BLE001
            return False

    # -- context manager ----------------------------------------------------
    def __enter__(self):
        if self.key in SharedLock._held:
            self._reentrant = self.acquired = True
            return self
        try:
            self._ws = _ws()
        except Exception as e:   # noqa: BLE001 — no sheet => no shared locking
            self.log("  ⚠ shared lock unavailable ({}: {}) — continuing without "
                     "cross-machine protection".format(
                         type(e).__name__, str(e)[:80]))
            return self

        start, waited = time.monotonic(), False
        while True:
            rows = self._rows()
            if rows is None:
                self.log("  ⚠ shared lock unreadable — continuing without it")
                return self
            live = self._live(rows)
            mine_live = [r for r in live if r[1] == self.me]
            others = [r for r in live if r[1] != self.me]

            if not others:
                # Clear any duplicate of our own before claiming again.
                for rownum, _, _ in mine_live[1:]:
                    self._drop(rownum)
                if mine_live:
                    self.acquired = True
                    SharedLock._held.add(self.key)
                    return self
                try:
                    self._ws.append_row(
                        [self.key, self.me,
                         dt.datetime.now().isoformat(timespec="seconds"),
                         self.note[:200]],
                        value_input_option="RAW")
                except Exception:  # noqa: BLE001
                    self.log("  ⚠ could not write the shared claim — continuing "
                             "without cross-machine protection")
                    return self
                # READ BACK. If someone appended at the same moment, the lowest
                # row wins and the other stands down — both sides compute this
                # from the same sheet, so they cannot both proceed.
                back = self._rows()
                if back is None:
                    self.acquired = True     # claimed; just can't verify
                    SharedLock._held.add(self.key)
                    return self
                live_back = self._live(back)
                if live_back and live_back[0][1] == self.me:
                    if waited:
                        self.log("  shared lock acquired — the other machine "
                                 "finished")
                    self.acquired = True
                    SharedLock._held.add(self.key)
                    return self
                for rownum, who, _ in reversed(live_back):
                    if who == self.me:
                        self._drop(rownum)   # we lost the race; stand down
            if time.monotonic() - start >= self.wait_s:
                who = others[0][1] if others else "another run"
                self.log("  ⚠ {} has held '{}' for over {:.0f}s — proceeding "
                         "anyway (duplicates possible)".format(
                             who, self.key, self.wait_s))
                return self
            if not waited:
                waited = True
                who = others[0][1] if others else "another run"
                self.log("  {} is already running this on {} — waiting for it "
                         "to finish (avoids a double post)".format(
                             self.key, who))
            time.sleep(POLL_S)

    def __exit__(self, *exc):
        if self._reentrant or not self.acquired:
            return False
        SharedLock._held.discard(self.key)
        try:
            rows = self._rows()
            for rownum, who, _ in reversed(rows or []):
                if who == self.me:
                    self._drop(rownum)
        except Exception:        # noqa: BLE001 — the lease expires regardless
            pass
        return False
