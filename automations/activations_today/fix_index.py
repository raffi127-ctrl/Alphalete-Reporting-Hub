"""One-off (Eve 2026-11-20): add the Pending Orders line to the Metrics
index that was ALREADY posted today, so today's thread matches what the
code posts from tomorrow on (slack_metrics_post._default).

Finds every '*Metrics for: <today>' header posted today by THIS token's user
(Lucy) in the D2D metrics channels + their mirrors, and swaps the old
':calendar: Activations Scheduled Today' line for the two new ones. Headers
that already have it are left alone. NDS/email offices never had the line.

    python -m automations.activations_today.fix_index            # dry run
    python -m automations.activations_today.fix_index --live     # edit
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from automations.activations_today import pull

OLD = ":calendar: Activations Scheduled Today\n"
NEW = (":calendar: Activations Scheduled Today (fiber only)\n"
       ":hourglass_flowing_sand: Pending Orders (fiber + wireless, by rep)\n")
_CH = re.compile(r"\bC0[A-Z0-9]{7,10}\b")


def channels() -> list:
    """Every channel id named in the office list, its onboarded file and the
    mirror table — a wide net on purpose: only Lucy's own headers get edited."""
    from automations.office_metrics import offices as om
    from automations.shared import slack_metrics_post as smp
    found = []
    srcs = [Path(om.__file__).read_text(encoding="utf-8")]
    onb = Path(om.__file__).with_name("onboarded_offices.json")
    if onb.exists():
        srcs.append(onb.read_text(encoding="utf-8"))
    srcs.append(json.dumps(smp.MIRROR_CHANNELS))
    srcs.append(smp.CHANNEL_ID)
    for s in srcs:
        for c in _CH.findall(s):
            if c not in found:
                found.append(c)
    return found


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "{}th".format(n)
    return "{}{}".format(n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fix_index")
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    me = client.auth_test()["user_id"]
    day = pull.central_today()
    first = "Metrics for: {} {} {}".format(day.strftime("%B"), _ordinal(day.day), day.year)
    start = dt.datetime.combine(day, dt.time.min, tzinfo=pull.CENTRAL).timestamp()
    print("token user {} — looking for '{}' in {} channels".format(
        me, first, len(channels())))
    edited = skipped = 0
    for ch in channels():
        try:
            msgs = client.conversations_history(channel=ch, oldest=str(start),
                                                limit=200).get("messages") or []
        except Exception as e:  # noqa: BLE001 — not a member / other workspace
            print("  {}: can't read ({})".format(ch, str(e)[:80]))
            continue
        for m in msgs:
            text = m.get("text") or ""
            if first not in text.split("\n", 1)[0] or OLD not in text + "\n":
                continue
            if m.get("user") != me:
                print("  {} {}: header not posted by this token — skip".format(ch, m["ts"]))
                skipped += 1
                continue
            new = (text + "\n").replace(OLD, NEW, 1).rstrip("\n")
            print("  {} {}: {}".format(ch, m["ts"], "EDIT" if args.live else "would edit"))
            if args.live:
                client.chat_update(channel=ch, ts=m["ts"], text=new)
            edited += 1
    print("done: {} header(s) {}, {} skipped".format(
        edited, "edited" if args.live else "to edit", skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
