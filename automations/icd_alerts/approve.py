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


def _me() -> str:
    """Whoever is RUNNING this, by their own token.

    auth_test is exactly right here and exactly wrong for the Lucy check
    below. "Is Lucy in this channel" must be asked by ID, because the token is
    per machine. "Am I in this channel" can only be asked of the token in
    hand -- and hardcoding Megan meant that when Eve ran it she was told
    whether MEGAN was in the room, which is the one thing she did not ask.
    """
    try:
        from automations.shared import slack_metrics_post as smp
        return smp._client().auth_test().get("user_id") or ""
    except Exception:  # noqa: BLE001 — a missing answer must not stop approval
        return ""


def _missing_people(members: List[str], me: str) -> List[str]:
    """Which of the people who should be in this room are not.

    Reported, never enforced. Lucy not being in the channel is fatal -- she
    physically cannot post. A person missing is a thing to fix in Slack in ten
    seconds, and blocking the approval on it would mean an office waits on a
    click that has nothing to do with them.
    """
    want = dict(O.APPROVERS)
    if me and me not in want:
        want[me] = "you"
    return [name for uid, name in want.items() if uid not in members]
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
        # FALL BACK TO THE SIGN-UP. The Office Channels request columns are
        # written by the relay when a machine posts its RECORDS -- and a Box,
        # Energy Wells or NDS office never posts records, because it has no
        # SaraPlus. So a knocks-only office relayed its board all day and
        # still had no row here, which made it impossible to approve and its
        # board impossible to post. Carlos, 2026-09-15.
        #
        # Reading the sign-up directly is also just better: they typed this on
        # OUR form, and needing their laptop to tell us what they told us was
        # always a detour.
        from automations.icd_signup import store as signup_store
        rec = signup_store.get(office_key)
        asked = list(rec.knocks_destinations) if rec else []
        if not asked:
            print("%s has no knocks request waiting. `approve --list` shows "
                  "what does." % office_key)
            return 1
        row = {"office": office_key, "asked": asked, "hours": ""}
    if not row["asked"]:
        print("%s asked for a knocks board but named no channel." % office_key)
        return 1
    if row.get("hours"):
        print("NOTE — they said their field hours differ: %s" % row["hours"])
        print("       (set that with them; it is not stored automatically)\n")

    me = _me()
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
        gone = _missing_people(members, me)
        print("  #%s (%s) every %s min%s"
              % (ch["name"], cid, cadence,
                 "" if not gone else "   [NOT in this one: %s]" % ", ".join(gone)))
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
    # CREATE IT RATHER THAN REFUSING. A knocks-only office has no row here at
    # all -- the relay only writes one when a machine posts records, which
    # these offices never do. Refusing left them permanently unapprovable.
    office = O.get(office_key)
    new_row = [""] * (P.CH_KN_APPROVED + 1)
    new_row[P.CH_OFFICE] = office_key
    new_row[P.CH_OWNER] = office.owner if office else ""
    new_row[P.CH_KN_WANTED] = ", ".join(
        "%s %s" % (d.get("channel_name") or d.get("channel_id"),
                   d.get("cadence_min")) for d in resolved)
    new_row[P.CH_KN_JSON] = json.dumps(resolved)
    new_row[P.CH_KN_APPROVED_JSON] = json.dumps(resolved)
    new_row[P.CH_KN_APPROVED] = "TRUE"
    tab.append_row(new_row)


def ensure_text_columns(tab) -> None:
    """Put the four text columns on the tab if they are not there yet.

    The same lesson as the sign-up tab: values written past the end of a
    header land in unnamed columns, and every reader then serves an empty
    list while the sheet looks full.
    """
    head = tab.row_values(1)
    want = ["Texts: Wanted", "Texts: Groups JSON",
            "Texts Approved JSON", "Texts Approved"]
    if len(head) > P.CH_TX_APPROVED and head[P.CH_TX_WANTED]:
        return
    head = list(head) + [""] * (P.CH_TX_APPROVED + 1 - len(head))
    for off, label in zip(range(P.CH_TX_WANTED, P.CH_TX_APPROVED + 1), want):
        head[off] = label
    tab.update(values=[head], range_name="A1:%s1" % _col_letter(len(head)))


def _col_letter(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def cmd_texts(office_key: str) -> int:
    """Sign off an office's iMessage group(s).

    WHAT THIS CAN AND CANNOT CHECK. A Slack room can be resolved from
    anywhere, so cmd_approve refuses one Lucy is not in. A GROUP CHAT cannot:
    it exists only in Messages on the machine that will send, so run from
    Megan's laptop there is nothing here to look up.

    So it checks when it can -- on a texting machine it resolves the name for
    real -- and when it cannot, it says the name is UNVERIFIED rather than
    printing something that reads like a check. That matters more here than
    almost anywhere: a group name matching no chat does not fail, it delivers
    nothing and reports success.
    """
    office_key = office_key.strip().lower()
    # READ WHAT THEY ASKED FOR FROM THE SIGN-UP, not from a request column the
    # office's own machine has to relay. A text destination is entirely OUR
    # side: their laptop hands in counts and we post, so the name of a group
    # chat never needs to reach that laptop at all. Routing it through there
    # would have meant an Apps Script change, a redeploy, and an office
    # waiting on its own machine to tell us something it already told the
    # form.
    from automations.icd_signup import store as signup_store
    rec = signup_store.get(office_key)
    asked = [g.strip() for g in (rec.text_groups if rec else []) if g.strip()]
    if not asked:
        print("%s did not ask to be texted." % office_key)
        return 1
    can_check = False
    try:
        from automations.gap_alerts import config as gc
        can_check = bool(gc.can_text())
    except Exception:  # noqa: BLE001
        pass

    resolved, problems = [], []
    for name in asked:
        if not can_check:
            print("  %-30s UNVERIFIED (this machine cannot see Messages)"
                  % name)
            resolved.append({"group": name, "cadence_min": 0})
            continue
        try:
            from automations.b2b_dispositions import text_post as tp
            tp.send_to_group(name, "", [], dry_run=True)
            print("  %-30s found" % name)
            resolved.append({"group": name, "cadence_min": 0})
        except Exception as e:  # noqa: BLE001
            problems.append("%s — %s" % (name, str(e)[:160]))

    if problems:
        print("\nNOT APPROVED:")
        for p_ in problems:
            print("  - %s" % p_)
        print("\nNothing was written.")
        return 1

    _write_texts_approval(office_key, resolved)
    print("\nApproved %d group(s) for %s." % (len(resolved), office_key))
    if not can_check:
        print("")
        print("THE NAMES ARE UNVERIFIED. Nothing here could look them up. If "
              "one does not match a real chat it will deliver nothing and "
              "say nothing, so confirm the first board actually arrives.")
    return 0


def _write_texts_approval(office_key: str, resolved) -> None:
    from automations.recruiting_report.fill import open_by_key
    tab = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet(P.CHANNELS_TAB)
    ensure_text_columns(tab)
    for i, row in enumerate(tab.get_all_values()[1:], start=2):
        if (row[P.CH_OFFICE] or "").strip().lower() == office_key:
            tab.update(values=[[", ".join(g["group"] for g in resolved),
                                json.dumps([g["group"] for g in resolved]),
                                json.dumps(resolved), "TRUE"]],
                       range_name="%s%d:%s%d" % (
                           _col_letter(P.CH_TX_WANTED + 1), i,
                           _col_letter(P.CH_TX_APPROVED + 1), i))
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
        print("  %-10s %-18s asked for %-26s (%s)"
              % (r["office"], r["owner"] or "",
                 r["wanted"] or "(left blank)", r["asked_at"] or "?"))
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
    """Sign off the room(s) an office's credit-check alerts post to.

    EVERY ROOM IS CHECKED SEPARATELY, and none is approved unless all of them
    resolve. Half an approval means the pings land in one room and vanish in
    the other, which is worse than nothing happening -- nothing happening gets
    noticed.
    """
    office_key = office_key.strip().lower()
    row = next((r for r in P.pending_requests()
                if r["office"].lower() == office_key), None)
    wanted = [channel] if channel else list((row or {}).get("asked") or [])
    if not wanted:
        print("%s has not named a channel yet, and you did not pass one. "
              "Use --channel to set it anyway." % office_key)
        return 1

    me = _me()
    resolved, problems = [], []
    for name in wanted:
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
        gone = _missing_people(members, me)
        print("  #%s (%s)%s%s"
              % (ch["name"], cid, "  [private]" if ch.get("is_private") else "",
                 "" if not gone else "   [NOT in this one: %s]" % ", ".join(gone)))
        resolved.append({"channel_id": cid, "channel_name": "#" + ch["name"]})

    if problems:
        print("\nNOT APPROVED:")
        for p_ in problems:
            print("  - %s" % p_)
        print("\nFix those and run this again. Nothing was written.")
        return 1

    here = _client().auth_test()
    if here.get("user_id") != LUCY_REPORTING:
        print("  (this machine's Slack token is %s / %s, not Lucy — the "
              "membership answers above are about Lucy either way)"
              % (here.get("user_id"), here.get("user")))

    _write_approval(office_key, resolved)
    print("\nApproved %d channel(s) for %s: %s"
          % (len(resolved), office_key,
             ", ".join(c["channel_name"] for c in resolved)))
    print("Preview what would post:  python -m automations.icd_alerts.post "
          "--office %s" % office_key)
    return 0


def _write_approval(office_key: str, resolved) -> None:
    from automations.recruiting_report.fill import open_by_key
    tab = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet(P.CHANNELS_TAB)
    for i, row in enumerate(tab.get_all_values()[1:], start=2):
        if (row[P.CH_OFFICE] or "").strip().lower() == office_key:
            tab.update(values=[[json.dumps(resolved), "TRUE"]],
                       range_name="F%d:G%d" % (i, i))
            return
    office = O.get(office_key)
    tab.append_row([office_key, office.owner if office else "",
                    ", ".join(c["channel_name"] for c in resolved),
                    json.dumps([c["channel_name"] for c in resolved]),
                    dt.datetime.now().isoformat(timespec="seconds"),
                    json.dumps(resolved), "TRUE"])


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
    rc = cmd_knocks(args.office) if args.knocks \
        else cmd_approve(args.office, args.channel)
    if rc == 0:
        # THE HUB CARD READS A CACHE, NOT THE SHEET (a Sheets read at Hub
        # import hung the whole app). Approving is the only moment an office's
        # channels or cadence actually change, so refreshing here is what keeps
        # "Lucy Eco Relay — ICD Offices" honest without anyone remembering to.
        # Never fatal: the approval already succeeded and must not be undone by
        # a cache write.
        try:
            from automations.icd_alerts import schedule_cache
            schedule_cache.refresh()
        except Exception as e:  # noqa: BLE001
            print("(hub schedule cache not refreshed: %s)" % e)
    return rc


if __name__ == "__main__":
    sys.exit(main())
