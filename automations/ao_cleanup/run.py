"""AO Slack channel cleanup — the monthly refresh, end to end.

One entry point so the Hub card and `lucy rerun ao_cleanup` do the same thing:

  1. ask Slack who is in each channel on the dropdown (conversations.members —
     the real list, not a replay of join/leave messages);
  2. refresh the id -> name / email cache (users.list, plus users.info for the
     Slack Connect people from other workspaces that users.list never returns);
  3. optionally replay each channel's history, which is the ONLY source for
     two of the notes: "Never posted here" and the join date;
  4. rewrite the tab, carrying Rafael's ticks forward and touching none of
     Eve's formatting.

Runs on the 1st of the month at P3 (the emptiest slot in the queue — no clock).
Everything is idempotent: it rebuilds the same rows from Slack every time.

NEEDS `~/.config/recruiting-report/slack-read-token` on the machine that runs
it — see automations/ao_cleanup/slack_read.py.

    python -m automations.ao_cleanup.run --dry-run
    python -m automations.ao_cleanup.run --skip-history      # ~1 min instead of ~10
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import argparse
import json
import sys
import traceback

from automations.ao_cleanup import fill_tab, names as names_mod, slack_read
from automations.ao_cleanup.channel_members import (
    CACHE_PATH, CHANNELS, replay)


def refresh_membership(cli, channels, skip_history=False):
    """conversations.members for every channel + (optionally) the history
    replay that feeds the 'never posted' note. Merges into the cache, so a
    channel whose history scan is skipped keeps the last one it had."""
    cache = {"channels": {}}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except ValueError:
            pass
    cache.setdefault("channels", {})

    for name, cid in channels:
        info = dict(cache["channels"].get(name) or {})
        members = slack_read.members(cid, cli)
        info.update({"name": name, "channel_id": cid,
                     "members_api": members, "api_count": len(members)})
        if not skip_history:
            try:
                info.update(replay(cli_history(), cid))
            except Exception as exc:              # noqa: BLE001
                # The notes degrade, the roster does not. A history scan that
                # dies (rate limit, a channel the posting token can't read)
                # must never cost us the member list we already have.
                print("  aviso: sin historial para %s (%s: %s)"
                      % (name, type(exc).__name__, str(exc)[:90]))
        print("  %-30s %4d miembros" % (name, len(members)))
        cache["channels"][name] = info

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return cache


def cli_history():
    """History needs the REPORTING token: channels:history / groups:history are
    on that one, and the read-only cleanup token does not carry them."""
    from automations.shared.slack_metrics_post import _client
    return _client()


def refresh_names(cli, cache):
    """users.list for the workspace, then users.info for whoever it left out —
    in practice the Slack Connect members of other workspaces."""
    names_mod.add(slack_read.all_users(cli))
    users = names_mod.load()
    ids = sorted({uid for info in cache["channels"].values()
                  for uid in info.get("members_api", []) or []})
    missing = [i for i in ids if not (users.get(i) or {}).get("team")]
    if missing:
        names_mod.add([slack_read.one_user(i, cli) for i in missing])
    return len(ids), len(missing)


def main(argv=None):
    ap = argparse.ArgumentParser(description="AO Slack channel cleanup")
    ap.add_argument("--dry-run", action="store_true",
                    help="refresh the caches and print the summary, write nothing")
    ap.add_argument("--skip-history", action="store_true",
                    help="skip the join/leave replay (drops the 'never posted' "
                         "note but finishes in about a minute)")
    ap.add_argument("--tab", default=fill_tab.TARGET_TAB)
    args = ap.parse_args(argv)

    try:
        cli = slack_read.client()
    except slack_read.NoReadToken as exc:
        print(exc, file=sys.stderr)
        return 2

    print("1/3  quien esta en cada canal")
    cache = refresh_membership(cli, CHANNELS, skip_history=args.skip_history)

    print("2/3  nombres y emails")
    total, extra = refresh_names(cli, cache)
    print("  %d personas distintas (%d resueltas de a una)" % (total, extra))

    print("3/3  la tab")
    rc = fill_tab.main(["--tab", args.tab] + (["--dry-run"] if args.dry_run else []))
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                              # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
