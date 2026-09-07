"""--channel-only: repair ONE channel without re-posting into the other.

    python -m automations.alphalete_production.test_channel_only

post_all fans every run out to #alphalete-sales AND the mirror
#alphalete-lvl1-chat. A run that dies partway therefore leaves the two channels
at different depths, and on 2026-09-07 there was no way to finish the short one:
#alphalete-sales ended 17/18, the mirror 3/18, and any `--only` rerun would have
duplicated seven images in the channel that was already complete.

Nothing is posted and nothing is rendered: capture_all and the Slack client are
replaced, so this only asks which CHANNELS a run would fan out to.
"""
from __future__ import annotations

import os

from automations.alphalete_production import run as apr
from automations.alphalete_production import slack_post
from automations.shared import slack_metrics_post as smp

# A day every section is gated ON, so `sections_for` reflects --only alone.
import datetime as _dt
_A_TUESDAY = _dt.date(2026, 9, 8)

MIRROR = "C09JG28CD27"          # #alphalete-lvl1-chat
SALES = "C068PH3RFSM"           # #alphalete-sales


def _channels_for(argv) -> list:
    """The channel list post_all would fan out to, after main() parses argv."""
    real_channel = slack_post.CHANNEL
    real_mirror_off = os.environ.get("ALPHALETE_MIRROR_OFF")
    real_capture = apr.capture.capture_all
    real_post = slack_post.post_all
    seen = {}

    apr.capture.capture_all = lambda *a, **k: ([], None, "test tab")

    def _fake_post_all(captures, sections, today=None, **k):
        seen["channels"] = [slack_post.CHANNEL] + smp.mirror_channels(slack_post.CHANNEL)
        return {"ok": True, "thread_ts": "1.1", "created": True, "posted": []}

    slack_post.post_all = _fake_post_all
    try:
        import sys
        real_argv = sys.argv
        sys.argv = ["run"] + argv
        try:
            apr.main()
        finally:
            sys.argv = real_argv
    finally:
        apr.capture.capture_all = real_capture
        slack_post.post_all = real_post
        slack_post.CHANNEL = real_channel
        if real_mirror_off is None:
            os.environ.pop("ALPHALETE_MIRROR_OFF", None)
        else:
            os.environ["ALPHALETE_MIRROR_OFF"] = real_mirror_off
    return seen.get("channels", [])


def _check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got  {got!r}\n        want {want!r}"))
    return ok


def test_default_still_fans_out_to_both():
    """The scheduled run passes no flag and MUST keep mirroring — this is a
    repair flag, not a change to the daily post."""
    return _check("default posts to sales + mirror",
                  _channels_for([]), [SALES, MIRROR])


def test_channel_only_mirror_skips_the_sales_channel():
    """The 9/7 case: finish the mirror, touch nothing in #alphalete-sales."""
    return _check("--channel-only <mirror> posts to the mirror alone",
                  _channels_for(["--channel-only", MIRROR]), [MIRROR])


def test_channel_only_sales_skips_the_mirror():
    """And the reverse — a zero_streak repair aimed at the sales channel must
    not re-post those four images into a mirror that is already correct."""
    return _check("--channel-only <sales> posts to sales alone",
                  _channels_for(["--channel-only", SALES]), [SALES])


def test_combines_with_only():
    """The two repair flags have to compose: the 9/7 zero_streak fix is
    `--channel-only <sales> --only zero_streak`, i.e. these sections, that
    channel. If --channel-only quietly widened the section set it would repost
    the whole thread into a channel that only needed one image."""
    ok = _check("channel is honoured alongside --only",
                _channels_for(["--channel-only", SALES, "--only", "zero_streak"]),
                [SALES])
    ok &= _check("--only still narrows the sections",
                 [s["id"] for s in apr.sections_for(_A_TUESDAY, only=["zero_streak"])],
                 ["zero_streak"])
    return ok


def main() -> int:
    ok = True
    for fn in (test_default_still_fans_out_to_both,
               test_channel_only_mirror_skips_the_sales_channel,
               test_channel_only_sales_skips_the_mirror,
               test_combines_with_only):
        print(f"\n--- {fn.__name__} ---")
        ok &= fn()
    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
