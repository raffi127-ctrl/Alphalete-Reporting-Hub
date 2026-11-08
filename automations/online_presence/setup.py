"""Set up one office's online presence -- the commands for the install call.

    # 1. the office's row (one input per thing; names, not ids)
    python -m automations.online_presence.setup add --office kash \
        --name "Kash Marketing" --room "#kash-online-presence" \
        --approvers "Kash Rai, Jane Doe" --email "hr@kashmarketing.com"

    # 2. after the owner adds alphaletemarketing@gmail.com as Manager
    python -m automations.online_presence.setup invites            # look
    python -m automations.online_presence.setup invites --accept   # take them
    python -m automations.online_presence.setup link-google kash   # find + save

    # 3. Lucy's own login to the office's Zoho (a visible window, once)
    python -m automations.brand_audit.zoho_draft --login --office kash

    # 4. the checklist: everything green = ready for a dry run
    python -m automations.online_presence.setup check kash --zoho

Nothing here posts anything, anywhere. `add` and `link-google` write the
office's row in offices.json; `invites --accept` accepts Google manager
invites; everything else only reads.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from automations.online_presence import offices

SLACK_IDS_DOC = (Path(__file__).resolve().parents[2] / "resources"
                 / "owner-slack-ids.md")
_ID = re.compile(r"^[UW][A-Z0-9]{6,}$")
_CHAN_ID = re.compile(r"^[CG][A-Z0-9]{6,}$")


# ---- names -> Slack ids ----------------------------------------------------
def _doc_people() -> List[Tuple[str, str]]:
    """(name cell, id) for every row of owner-slack-ids.md."""
    out = []
    try:
        text = SLACK_IDS_DOC.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        ids = [c for c in cells if _ID.match(c)]
        if len(cells) >= 2 and ids:
            out.append((cells[0], ids[0]))
    return out


def resolve_person(name: str, cl=None) -> str:
    """A person's Slack id from their name. owner-slack-ids.md first (it flags
    the look-alike accounts); then the workspace, exact full-name match only.
    Raises with a plain reason when it is not exactly one person."""
    name = (name or "").strip()
    if _ID.match(name):
        return name
    words = name.lower().split()
    hits = {i for cell, i in _doc_people()
            if words and all(w in cell.lower() for w in words)}
    if len(hits) == 1:
        return hits.pop()
    if len(hits) > 1:
        raise ValueError(f"{name!r} matches {len(hits)} people in "
                         "owner-slack-ids.md -- use their Slack id")
    if cl is None:
        from automations.brand_audit.social_inbox import _client
        cl = _client()
    found, cursor = set(), None
    while True:
        r = cl.users_list(limit=200, cursor=cursor) if cursor else cl.users_list(limit=200)
        for u in r.get("members") or []:
            if u.get("deleted") or u.get("is_bot"):
                continue
            prof = u.get("profile") or {}
            names = {(prof.get("real_name") or "").lower(),
                     (prof.get("display_name") or "").lower()}
            if name.lower() in names:
                found.add(u["id"])
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    if len(found) == 1:
        return found.pop()
    raise ValueError(f"{name!r}: " + ("nobody on Slack by that exact name"
                                      if not found else
                                      f"{len(found)} Slack accounts share it")
                     + " -- use their Slack id, and add it to owner-slack-ids.md")


def resolve_room(room: str, cl=None) -> str:
    """A channel id from '#name' or an id."""
    room = (room or "").strip().lstrip("#")
    if _CHAN_ID.match(room):
        return room
    if cl is None:
        from automations.brand_audit.social_inbox import _client
        cl = _client()
    cursor = None
    while True:
        kw = dict(types="public_channel,private_channel", limit=500,
                  exclude_archived=True)
        if cursor:
            kw["cursor"] = cursor
        r = cl.conversations_list(**kw)
        for c in r.get("channels") or []:
            if c.get("name") == room.lower():
                return c["id"]
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    raise ValueError(f"no channel #{room} that Lucy can see -- create it and "
                     "invite Lucy first")


# ---- commands ----------------------------------------------------------------
def cmd_add(a) -> int:
    old = offices.get(a.office)
    try:
        room = resolve_room(a.room) if a.room else (old.slack_channel if old else "")
        approvers = (tuple(resolve_person(n) for n in a.approvers.split(",") if n.strip())
                     if a.approvers else (old.approvers if old else ()))
    except ValueError as e:
        print(f"✗ {e}")
        return 1
    base = old or offices.Presence(key=a.office.lower(), business_name="",
                                   slack_channel="")
    from dataclasses import replace
    p = replace(base,
                business_name=a.name or base.business_name,
                slack_channel=room,
                approvers=approvers,
                contact_email=a.email or base.contact_email,
                timezone=a.timezone or base.timezone)
    offices.save(p)
    print(f"✓ saved {p.key}: {p.business_name} · room {p.slack_channel} · "
          f"{len(p.approvers)} approver(s) · mode {p.mode}")
    for prob in p.problems():
        print(f"  still missing: {prob}")
    return 0


def cmd_invites(a) -> int:
    from automations.brand_audit import gbp_api
    inv = gbp_api.pending_invitations()
    if not inv:
        print("No Google invitations waiting. (The owner adds "
              "alphaletemarketing@gmail.com as Manager in their Business Profile.)")
        return 0
    for i in inv:
        print(f"• {i['business'] or '(no name)'} — role {i['role']}")
        if a.accept:
            gbp_api.accept_invitation(i["name"])
            print("  ✓ accepted")
    if not a.accept:
        print("Run again with --accept to take them.")
    return 0


def cmd_link_google(a) -> int:
    from dataclasses import replace
    from automations.brand_audit import gbp_api
    p = offices.get(a.office)
    if not p or p.key == "alphalete":
        print(f"✗ no office {a.office!r} (run `add` first)")
        return 1
    hits = gbp_api.find_location(a.name or p.business_name)
    if len(hits) != 1:
        print(f"✗ {len(hits)} listings match {a.name or p.business_name!r}:")
        for h in hits:
            print(f"   {h['title']}  ({h['path']})")
        if not hits:
            print("  Has the owner added alphaletemarketing@gmail.com as Manager, "
                  "and was the invite accepted (`invites --accept`)?")
        else:
            print("  Re-run with --name exactly as the listing reads.")
        return 1
    h = hits[0]
    offices.save(replace(p, gbp_location=h["path"]))
    print(f"✓ {p.key} → {h['title']} ({h['path']})"
          + ("" if h["verified"] is not False else
             "\n  ⚠ Google says this listing is NOT verified — replies will fail "
             "until the owner finishes verification."))
    return 0


def _slack_room_check(p) -> List[Tuple[bool, str]]:
    out = []
    from automations.brand_audit import credentials
    from automations.brand_audit.social_inbox import _client
    try:
        info = _client().conversations_info(channel=p.slack_channel)["channel"]
        out.append((bool(info.get("is_member")),
                    f"Lucy is in #{info.get('name')}"))
    except Exception as e:
        out.append((False, f"Lucy can't open the room ({str(e)[:80]})"))
        return out
    bot = credentials.optional("slack_bot_token")
    if bot:
        # The bot can only read files (no channels:read), so it can't look the
        # room up itself: ask who IT is, then read the room's members as Lucy.
        label = "@hubposter is in the room (needed to open the photos)"
        try:
            from automations.shared import slack_metrics_post as smp
            bot_id = smp._client(bot).auth_test()["user_id"]
            members, cursor = set(), None
            while True:
                kw = {"channel": p.slack_channel, "limit": 500}
                if cursor:
                    kw["cursor"] = cursor
                r = _client().conversations_members(**kw)
                members |= set(r.get("members") or [])
                cursor = (r.get("response_metadata") or {}).get("next_cursor")
                if not cursor:
                    break
            out.append((bot_id in members, label))
        except Exception as e:
            out.append((False, f"{label} — {str(e)[:60]}"))
    return out


def checklist(p, *, zoho: bool = False) -> List[Tuple[bool, str]]:
    """[(ok, line)] -- the install-call checklist for one office."""
    rows: List[Tuple[bool, str]] = []
    for prob in p.problems():
        rows.append((False, f"Office row: {prob}"))
    if not p.problems():
        rows.append((True, f"Office row: {p.business_name}, {p.timezone}"))
    rows.append((bool(p.approvers),
                 f"Approvers named: {len(p.approvers)}"
                 + ("" if p.approvers else " (Megan + Eve approve until they name someone)")))
    if p.slack_channel:
        rows.extend(_slack_room_check(p))
    if p.reviews:
        if not p.gbp_location:
            rows.append((False, "Google listing linked (run `link-google`)"))
        else:
            try:
                from automations.brand_audit import gbp_api
                revs = gbp_api.list_reviews(p.gbp_location)
                open_ = sum(1 for r in revs if not r.get("has_reply"))
                rows.append((True, f"Google reviews readable: {len(revs)} total, "
                                   f"{open_} without a reply"))
            except Exception as e:
                rows.append((False, f"Google reviews readable ({str(e)[:90]})"))
    if p.social:
        prof = p.zoho_profile
        if not zoho:
            rows.append((prof.exists(), "Zoho login folder exists on this Lucy"
                         + ("" if prof.exists() else
                            " (run zoho_draft --login --office " + p.key + ")")
                         + " — add --zoho to open it and check"))
        else:
            from automations.brand_audit import zoho_draft
            try:
                r = zoho_draft.channel_check(prof)
                rows.append((r["logged_in"], "Zoho is signed in"))
                if r["logged_in"]:
                    rows.append((bool(r["channels"]), "Zoho has socials connected: "
                                 + (", ".join(r["channels"]) or "none")))
            except Exception as e:
                rows.append((False, f"Zoho check failed ({str(e)[:90]})"))
    rows.append((p.is_live, f"Mode: {p.mode}"
                 + ("" if p.is_live else " (nothing posts until this says live)")))
    return rows


def cmd_check(a) -> int:
    p = offices.get(a.office)
    if not p:
        print(f"✗ no office {a.office!r} (run `add` first)")
        return 1
    rows = checklist(p, zoho=a.zoho)
    print(f"\n{p.business_name or p.key} — online presence setup\n")
    for ok, line in rows:
        print(f"  {'✅' if ok else '❌'} {line}")
    blocking = [l for ok, l in rows if not ok and not l.startswith("Mode:")]
    print("\n" + ("Ready for a dry run." if not blocking else
                  f"{len(blocking)} thing(s) to finish."))
    return 0 if not blocking else 1


def main(argv=None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="online_presence.setup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add", help="add or update an office")
    s.add_argument("--office", required=True, help="the office's ECO key, e.g. kash")
    s.add_argument("--name", default="", help="business name exactly as on Google")
    s.add_argument("--room", default="", help="Slack room, e.g. #kash-online-presence")
    s.add_argument("--approvers", default="", help="names, comma separated")
    s.add_argument("--email", default="", help="where complaints are invited to write")
    s.add_argument("--timezone", default="", help="e.g. America/Los_Angeles")
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("invites", help="Google manager invites waiting for us")
    s.add_argument("--accept", action="store_true")
    s.set_defaults(fn=cmd_invites)
    s = sub.add_parser("link-google", help="find and save the office's listing")
    s.add_argument("office")
    s.add_argument("--name", default="", help="listing name if it differs")
    s.set_defaults(fn=cmd_link_google)
    s = sub.add_parser("check", help="the install checklist")
    s.add_argument("office")
    s.add_argument("--zoho", action="store_true",
                   help="also open the office's Zoho and list connected socials")
    s.set_defaults(fn=cmd_check)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
