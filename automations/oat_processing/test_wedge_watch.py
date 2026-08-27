"""Browser-free, Slack-free checks on the office-11580 wedge alarm. Run:

    python -m automations.oat_processing.test_wedge_watch

WHY THIS EXISTS (2026-08-26): the alarm had two independent faults, and each one
hid the other.

  1. It had no channel. The id came only from `output/.corrections_channel_id`, a
     gitignored sidecar that was never written on Lucy 2, so every alert printed
     "NO CHANNEL — would post:" and went nowhere — 252 times in one day.
  2. It cried wolf. "no next-pager control found" is logged on a perfectly healthy
     walk (a 1-2 applicant queue has no next page). That same 2026-08-26 log
     carried 252 wedge signatures AND 74 "✅ SENT to AI" lines — so the moment the
     channel was wired, the alarm would have paged "both pipelines are stalled" on
     a day that sent 74 applicants.

The first fix for (2) was to gate weak signatures behind "only when nothing looks
healthy". That was NOT enough, and it paged the channel for real the same evening:
once the queue empties there are no sends to look healthy WITH, so the pager line
prints with nothing to counter it. The alert claimed both pipelines were stalled
while the flow was fine.

So the rule is stricter now: a line that appears during ordinary operation is not a
signature at all, at any gate. "no next-pager control found" (end of queue) and
"menu click miss N/3" (one attempt of a retry) are gone. What's left is the hard
pair — always authoritative — plus "no rqst token in url", which only prints when
the walk genuinely couldn't reach the queue.

Nothing here touches Slack — assess() is pure log reading and the post path is only
exercised in dry-run, which builds no client.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import pathlib
import tempfile

from . import session_wedge_watch as w

# The real shape of 2026-08-26's log: healthy sends interleaved with the noisy
# weak signature.
BUSY_DAY = """\
[oat] walk start
    ✅ SENT to AI: Noni Brown
[oat] no next-pager control found
    ✅ SENT to AI: Jazlyn Soza
[oat] no next-pager control found
"""
# A session that really is frozen: the hard signature, nothing getting done.
FROZEN = """\
[cdp][STOP] stale cloudflare clearance on office 11580
[oat] no next-pager control found
"""
# The nastiest case — frozen NOW, but the tail still holds a send from before it
# froze. The hard signature has to win.
FROZE_MIDWAY = """\
    ✅ SENT to AI: Eden Ocanas
[rp] extractor stalled
"""
QUIET = "[oat] walk start\n[oat] nothing in the queue\n"


def _assess(body: str):
    """Run assess() against a scratch log dir holding exactly this text."""
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="wedge-"))
    (tmp / "applicant-push-2026-08-26.log").write_text(body)
    orig = w.LOG_DIR
    try:
        w.LOG_DIR = tmp
        return w.assess()
    finally:
        w.LOG_DIR = orig


def _check(label, got, expected) -> bool:
    ok = got == expected
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}"
          f"{'' if ok else f'  (expected {expected!r})'}")
    return ok


def main() -> int:
    results = []

    print("state from the logs:")
    results.append(_check("busy day with the noisy pager line → healthy",
                          _assess(BUSY_DAY)[0], "healthy"))
    # THE CASE THAT ACTUALLY PAGED MEGAN (2026-08-26 evening): an empty queue means
    # no sends, so there is nothing "healthy" to outvote the pager line. Gating it
    # behind healthy-wins was not enough — it must not be a signature at all.
    results.append(_check("quiet evening, empty queue, no sends → quiet",
                          _assess("[oat] walk start\n"
                                  "[oat] no next-pager control found\n")[0],
                          "quiet"))
    results.append(_check("menu miss that retries → quiet",
                          _assess("[oat] menu click miss 1/3 (TimeoutError)\n")[0],
                          "quiet"))
    results.append(_check("hard signature → wedged",
                          _assess(FROZEN)[0], "wedged"))
    results.append(_check("froze after a send → wedged (hard signature wins)",
                          _assess(FROZE_MIDWAY)[0], "wedged"))
    results.append(_check("weak signature alone, nothing working → wedged",
                          _assess("[oat] no rqst token in URL — cannot direct-nav "
                                  "to p=604\n")[0],
                          "wedged"))
    results.append(_check("nothing to judge → quiet", _assess(QUIET)[0], "quiet"))
    # The watcher writes its verdict into the same log it reads. That line quotes
    # the signature, so without filtering it re-detects its own echo forever and
    # the wedge can never clear.
    results.append(_check("its own echo is not evidence",
                          _assess(QUIET + "[wedge-watch] state=wedged evidence="
                                          "'no next-pager control found'\n")[0],
                          "quiet"))

    print("channel:")
    results.append(_check("falls back to #claudecorrections-and-requests",
                          w.CHANNEL, "C0BK5PRG259"))
    orig_cache = w.CHANNEL_CACHE
    try:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="wedge-ch-"))
        sidecar = tmp / "chan"
        sidecar.write_text("C0THEROVERRIDE\n")
        w.CHANNEL_CACHE = sidecar
        results.append(_check("sidecar overrides the constant",
                              w._channel(), "C0THEROVERRIDE"))
        w.CHANNEL_CACHE = tmp / "missing"
        results.append(_check("missing sidecar still resolves",
                              w._channel(), "C0BK5PRG259"))
    finally:
        w.CHANNEL_CACHE = orig_cache

    print("dry-run posts nothing:")
    results.append(_check("dry-run reports success without a Slack client",
                          w._post("title", ["body"], True), True))

    # RECOVERY MUST CLOSE THE THREAD OR SAY NOTHING (Megan 2026-08-26).
    # The old healthy branch fell back to a hand-rolled "recovered" post when the
    # close didn't take. That fallback went through _post(), which stamps the
    # WEDGE headline and an `open` marker on whatever it is handed — so the
    # all-clear OPENED a fresh incident saying "office 11580 session wedged",
    # with "session recovered" 246ms under it and no ✅ on either. The parent
    # stayed open forever, because the same pass then cleared its state file and
    # never tried again.
    print("recovery path:")
    # ensure_closed IS STUBBED IN BOTH CASES, and that is not optional. The
    # first draft of this test stubbed only the success case and let the failure
    # case "fail naturally" for want of a Slack client. On a laptop that HAS a
    # token there is no such failure: the run reached the live channel and
    # posted a real resolution into a real thread (2026-08-26 20:34). A test in
    # this repo never gets to discover whether it can reach Slack.
    import automations.shared.incident_thread as _inc
    orig_state, orig_assess = w.STATE, w.assess
    orig_post, orig_ensure = w._post, _inc.ensure_closed
    posted = []
    try:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="wedge-st-"))
        w.STATE = tmp / "state"
        w.assess = lambda: ("healthy", "", "test.log")
        w._post = lambda *a, **k: posted.append(a) or True

        # 1. Close fails: post NOTHING, and KEEP the episode so the next pass —
        #    five minutes away — tries again.
        _inc.ensure_closed = lambda *a, **k: False
        w._save_state({"alerted_at": "2026-08-26T19:12:00"})
        w.run()
        results.append(_check("failed close posts no message", posted, []))
        results.append(_check("failed close keeps the episode for a retry",
                              bool(w._load_state().get("alerted_at")), True))

        # 2. Close succeeds: the episode is forgotten, and still nothing is
        #    posted by the watcher — the ✅ and the reply are the thread's job.
        _inc.ensure_closed = lambda *a, **k: True
        w.run()
        results.append(_check("closed episode is forgotten",
                              w._load_state().get("alerted_at"), None))
        results.append(_check("a successful close posts no message either",
                              posted, []))
    finally:
        w.STATE, w.assess = orig_state, orig_assess
        w._post, _inc.ensure_closed = orig_post, orig_ensure

    passed = sum(results)
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
