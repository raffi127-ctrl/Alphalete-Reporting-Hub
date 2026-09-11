"""Review what offices asked for, and sign off where their alerts go.

  python -m automations.icd_alerts.approve                    # what is waiting
  python -m automations.icd_alerts.approve kash               # use what they asked for
  python -m automations.icd_alerts.approve kash --channel "#palace-ops"

THE OFFICE ASKS, A PERSON DECIDES. The installer relays the owner's answer into
'They Asked For' on the 'Office Channels' tab and nothing else; a laptop cannot
write the Channel ID, so it cannot aim its own alerts anywhere. This is the
other half of that: the only way a channel becomes real.

IT CHECKS BEFORE IT WRITES, because the two ways this fails are both silent.
Lucy not being in the room means every post dies -- and for a PRIVATE channel
Slack answers `channel_not_found` rather than `not_in_channel`, because it will
not admit a private channel exists to a non-member. So a missing membership
looks exactly like a wrong id. It also reports whether MEGAN is in the room,
since being able to post there is not the same as being able to read it
(Megan 2026-09-11: "I still need to also be added to the channel").
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Dict, List, Optional

from automations.icd_alerts import offices as O, post as P

MEGAN = O.HOLDING_DM                 # U04G5HJBGFN
# 'Lucy Reporting' -- the identity the POSTER runs as, on a Lucy box.
#
# NOT whatever auth_test() says here. The Slack token is per MACHINE: a Lucy
# holds Lucy Reporting's, and Megan's laptop holds MEGAN's. Running this from
# the laptop and asking "is Lucy in the channel?" answers about Megan, says
# yes, and approves a room the poster cannot actually reach. Checked by id
# instead, so the answer is the same wherever this is run from.
LUCY_REPORTING = "U0BCG8F9B5Z"


def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def _looks_like_an_id(s: str) -> bool:
    s = s.strip()
    return (len(s) >= 9 and s[0] in "CGD"
            and s.isalnum() and s.upper() == s)


def _known_channel_ids() -> Dict[str, str]:
    """{'#name': 'Cxxxx'} from the maps this repo already keeps.

    Checked BEFORE asking Slack, because conversations.list is rate limited
    (it answered `ratelimited` the first time this ran) and paging a workspace
    this size to find a channel we already have the id for is the expensive
    way to learn nothing.
    """
    out = {}
    try:
        from automations.office_metrics import offices as om
        for off in getattr(om, "OFFICES", {}).values():
            name = getattr(off, "channel_name", "")
            cid = getattr(off, "channel_id", "")
            if name and cid:
                out[name.lower()] = cid
    except Exception:  # noqa: BLE001
        pass
    return out


def find_channel(name: str) -> Optional[Dict]:
    """Resolve a channel from an id, a name we already know, or Slack itself."""
    raw = name.strip()
    want = raw.lstrip("#").lower()
    client = _client()

    if _looks_like_an_id(raw):
        try:
            return client.conversations_info(channel=raw).get("channel")
        except Exception:  # noqa: BLE001
            return None

    known = _known_channel_ids().get("#" + want)
    if known:
        try:
            return client.conversations_info(channel=known).get("channel")
        except Exception:  # noqa: BLE001
            pass

    # Last resort: page the workspace, backing off when Slack says to. Without
    # the retry this raises SlackApiError('ratelimited') and reads as "no such
    # channel", which is the opposite of what it means.
    import time
    cursor, attempts = None, 0
    while True:
        try:
            resp = client.conversations_list(
                types="public_channel,private_channel", limit=200,
                cursor=cursor, exclude_archived=True)
        except Exception as e:  # noqa: BLE001
            if "ratelimited" in str(e) and attempts < 3:
                attempts += 1
                time.sleep(20 * attempts)
                continue
            raise
        for ch in resp.get("channels", []):
            if (ch.get("name") or "").lower() == want:
                return ch
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return None


def members_of(channel_id: str) -> List[str]:
    out, cursor = [], None
    while True:
        resp = _client().conversations_members(channel=channel_id, limit=200,
                                               cursor=cursor)
        out.extend(resp.get("members", []))
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return out


def cmd_knocks(office_key: str) -> int:
    """Sign off an office's knocks destinations, resolving each channel.

    EVERY ROOM IS CHECKED SEPARATELY. An office can ask for two, and one of
    them being a channel Lucy was never invited to must not quietly approve
    the other half into working while the board silently fails in the first.
    """
    office_key = office_key.strip().lower()
    row = next((r for r in P.pending_knocks() if r["office"].lower() == office_key),
               None)
    if not row:
        print("%s has no knocks request waiting. `approve --list` shows what does."
              % office_key)
        return 1
    if not row["asked"]:
        print("%s asked for a knocks board but named no channel." % office_key)
        return 1
    if row.get("hours"):
        print("NOTE — they said their field hours differ: %s" % row["hours"])
        print("       (set that with them; it is not stored automatically)\n")

    resolved, problems = [], []
    for dest in row["asked"]:
        name = str(dest.get("channel") or "").strip()
        cadence = dest.get("cadence_min")
        print("looking up %s ..." % name)
        ch = find_channel(name)
        if not ch:
            problems.append("%s — no such channel (if it is private, Lucy has "
                            "to be invited before she can even see it)" % name)
            continue
        cid = ch["id"]
        try:
            members = members_of(cid)
        except Exception as e:  # noqa: BLE001
            problems.append("%s — could not read the member list (%s)" % (name, e))
            continue
        if LUCY_REPORTING not in members:
            problems.append("%s — Lucy Reporting is not in it" % name)
            continue
        print("  #%s (%s) every %s min%s"
              % (ch["name"], cid, cadence,
                 "" if MEGAN in members else "   [you are NOT in this one]"))
        resolved.append({"channel_id": cid, "channel_name": "#" + ch["name"],
                         "cadence_min": cadence})

    if problems:
        print("\nNOT APPROVED:")
        for p_ in problems:
            print("  - %s" % p_)
        print("\nFix those and run this again. Nothing was written.")
        return 1

    _write_knocks_approval(office_key, resolved)
    print("\nApproved %d destination(s) for %s." % (len(resolved), office_key))
    print("Preview:  python -m automations.icd_alerts.knocks_post --office %s "
          "--force" % office_key)
    return 0


def _write_knocks_approval(office_key: str, resolved) -> None:
    from automations.recruiting_report.fill import open_by_key
    tab = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet(P.CHANNELS_TAB)
    for i, row in enumerate(tab.get_all_values()[1:], start=2):
        if (row[P.CH_OFFICE] or "").strip().lower() == office_key:
            tab.update(values=[[json.dumps(resolved), "TRUE"]],
                       range_name="K%d:L%d" % (i, i))
            return
    raise SystemExit("no row for %r on the '%s' tab"
                     % (office_key, P.CHANNELS_TAB))


def cmd_list() -> int:
    pending = P.pending_requests()
    approved = P.approved_channels()
    if approved:
        print("Already approved:")
        for key, chans in sorted(approved.items()):
            print("  %-10s -> %s" % (key, ", ".join(c.name for c in chans)))
        print()
    if not pending:
        print("Nothing waiting for approval.")
        return 0
    print("Waiting on you:")
    for r in pending:
        print("  %-10s %-18s asked for %-22s (%s)"
              % (r["office"], r["owner"] or "", r["asked"] or "(left blank)",
                 r["asked_at"] or "?"))
    print("\nApprove one with:  python -m automations.icd_alerts.approve <office>")

    kn = P.pending_knocks()
    if kn:
        print("\nKnocks boards waiting on you:")
        for r in kn:
            print("  %-10s %-18s %s" % (r["office"], r["owner"] or "", r["wanted"]))
        print("\nApprove one with:  python -m automations.icd_alerts.approve "
              "<office> --knocks")
    return 0


def cmd_approve(office_key: str, channel: Optional[str]) -> int:
    office_key = office_key.strip().lower()
    pending = {r["office"].lower(): r for r in P.pending_requests()}
    row = pending.get(office_key)
    asked = channel or (row or {}).get("asked") or ""
    if not asked:
        print("%s has not asked for a channel yet, and you did not name one. "
              "Pass --channel to set it anyway." % office_key)
        return 1

    print("looking up %s ..." % asked)
    ch = find_channel(asked)
    if not ch:
        print("No channel called %r in this workspace.\n"
              "If it is PRIVATE, Lucy has to be invited before she can even "
              "see it -- Slack hides private channels from non-members, so "
              "'not found' and 'not a member' look identical here.\n"
              "You can also pass the channel ID instead of the name: open the "
              "channel in Slack, click its name, and the ID is at the bottom "
              "of the About tab." % asked)
        return 1

    cid, cname = ch["id"], "#" + ch["name"]
    print("  found %s (%s)%s" % (cname, cid,
                                 "  [private]" if ch.get("is_private") else ""))

    try:
        members = members_of(cid)
    except Exception as e:  # noqa: BLE001
        print("  could not read the member list: %s" % e)
        members = []

    here = _client().auth_test()
    lucy_in = LUCY_REPORTING in members
    megan_in = MEGAN in members
    print("  Lucy Reporting is in it: %s" % ("yes" if lucy_in else "NO"))
    print("  Megan is in it         : %s" % ("yes" if megan_in else "NO"))
    if here.get("user_id") != LUCY_REPORTING:
        print("  (this machine's Slack token is %s / %s, not Lucy -- the "
              "membership answer above is about Lucy either way)"
              % (here.get("user_id"), here.get("user")))

    if not lucy_in:
        print("\nNOT APPROVED. Lucy Reporting has to be in the channel or "
              "every post fails -- and for a private channel the failure is "
              "`channel_not_found`, which reads like a bad id. Invite her, "
              "then run this again.")
        return 1
    if not megan_in:
        print("\n  (you are not in that channel yet -- you would not see the "
              "alerts land. Worth adding yourself before this goes live.)")

    _write_approval(office_key, cid, cname)
    print("\nApproved: %s -> %s" % (office_key, cname))
    print("Preview what would post:  python -m automations.icd_alerts.post "
          "--office %s" % office_key)
    return 0


def _write_approval(office_key: str, channel_id: str, channel_name: str) -> None:
    from automations.recruiting_report.fill import open_by_key
    tab = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet(P.CHANNELS_TAB)
    rows = tab.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if (row[P.CH_OFFICE] or "").strip().lower() == office_key:
            tab.update(values=[[channel_id, channel_name, "TRUE"]],
                       range_name="E%d:G%d" % (i, i))
            return
    office = O.get(office_key)
    tab.append_row([office_key, office.owner if office else "", "",
                    dt.datetime.now().isoformat(timespec="seconds"),
                    channel_id, channel_name, "TRUE"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Approve where an office's alerts post")
    ap.add_argument("office", nargs="?", help="office key, e.g. kash")
    ap.add_argument("--channel", help="override what they asked for")
    ap.add_argument("--knocks", action="store_true",
                    help="approve the KNOCKS board destinations instead of "
                         "the credit-check channel")
    args = ap.parse_args(argv)
    if not args.office:
        return cmd_list()
    if args.knocks:
        return cmd_knocks(args.office)
    return cmd_approve(args.office, args.channel)


if __name__ == "__main__":
    sys.exit(main())
