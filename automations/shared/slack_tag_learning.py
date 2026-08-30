"""Learn a Slack ID from a human's hand-tag, so a name is only ever unlisted once.

THE PROBLEM (Megan 2026-08-30, and Raf in the same thread): a report posts
"⚠️ Unable to tag — needs a manual reach-out" with five names, somebody replies
tagging those people by hand, and the NEXT pass posts the very same five names
— in the same thread, under the tags. Worse for New-Start: a person with no
roster entry can't be matched to their own "Sent" reply either, so Raf sees
"Aimee and Ana haven't sent anything, but they have."

Megan asked for this to be UNIVERSAL — "this should be universal for any slack
chat report you do" — so the learning, the store and the matching live here in
shared/ rather than inside one report. A report supplies the names it couldn't
tag; this module reads the thread, resolves the hand-tags, and hands back the
ones that matched.

THE SAFETY RULE, and it is the whole design: a mention is only learned when the
person it resolves to MATCHES A NAME THE REPORT SAID IT COULDN'T TAG. Never
"every mention in the thread". Two reasons, both of which have already bitten:
  * A roll call is the bot's OWN post. Feeding its mentions back in makes a bad
    tag self-sustaining — that is exactly how Bill Hirwa got re-tagged every
    pass on 2026-08-08.
  * People get tagged in threads for unrelated reasons. Learning them would
    quietly enroll them into a report they have nothing to do with.
A human tagging a name the bot just said it couldn't reach is an unambiguous
signal: that person exists, is in the channel, and is the right person.

WHAT MADE THIS POSSIBLE: Lucy's Slack token now HAS `users:read` — verified on
Lucy 1 on 2026-08-30 (`lucy_reporting`/U0BCG8F9B5Z resolved a users.info call).
Older notes in this repo say it doesn't and that a static roster is the only
option; that is now stale. Without users:read a mention is an opaque ID and
none of this works — the count of hand-tags does NOT reliably line up with the
count of unlisted names (Raf tagged 4 of the 5 on 8/30), so position matching
would silently mislabel people.

The store is COMMITTED: Slack IDs and display names are not secrets, and git is
the only channel that reaches the mini.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# The COMMITTED base: hand-curated, and the only copy that reaches other
# machines (git is the only channel to the mini).
STORE_PATH = Path(__file__).resolve().parent / "slack_known_users.json"

# What a RUN writes. Never the committed file: a report dirties this store
# every time it learns somebody, and a dirty tracked file on Lucy 1 makes
# `lucy update`'s autostash conflict -- which exits 0 and takes the whole 4am
# batch down with it. output/ is gitignored, so a learning write can never
# collide with a deploy. Promote entries into the committed file with
# `python -m automations.shared.slack_tag_learning --promote`.
LOCAL_PATH = (Path(__file__).resolve().parents[2] / "output" / "shared"
              / "slack_known_users.local.json")

# <@U123ABC> and the <@U123ABC|display name> form Slack still emits in places.
MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")


def _norm(name: str) -> str:
    """Casefold + FOLD accents + drop punctuation.

    Folded, NOT stripped: "De'Avioñ Allen" -> 'deavion allen' and 'Anh Đinh' ->
    'anh dinh'. Stripping took the letter with the accent and broke every
    accented name (new_start_followup fixed the same bug on 2026-08-03).
    """
    s = unicodedata.normalize("NFKD", name or "")
    s = (s.replace("đ", "d").replace("Đ", "d").replace("ø", "o")
          .replace("Ø", "o").replace("ł", "l").replace("Ł", "l"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]+", "", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _read(path: Path) -> dict:
    if not path.exists():
        return {"users": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a corrupt store must not kill a report
        return {"users": {}}


def _save_local(data: dict) -> None:
    data["_note"] = (
        "MACHINE-LOCAL. Slack IDs this machine learned from hand-tags. "
        "Gitignored on purpose: writing to the committed store would dirty a "
        "tracked file and break `lucy update`. Promote with: python -m "
        "automations.shared.slack_tag_learning --promote"
    )
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")


def known() -> Dict[str, dict]:
    """normalized name -> {id, name, source, learned}, committed + local."""
    users = dict(_read(STORE_PATH).get("users", {}) or {})
    users.update(_read(LOCAL_PATH).get("users", {}) or {})
    return users


def local_only() -> Dict[str, dict]:
    """Learned on this machine but not yet committed — surfaced by callers so
    a learned id isn't invisible to every other machine forever."""
    base = _read(STORE_PATH).get("users", {}) or {}
    return {k: v for k, v in (_read(LOCAL_PATH).get("users", {}) or {}).items()
            if k not in base}


def lookup(name: str) -> Optional[str]:
    """The Slack ID for `name`, or None. What other reports call."""
    return (known().get(_norm(name)) or {}).get("id")


def remember(name: str, slack_id: str, source: str = "") -> None:
    data = _read(LOCAL_PATH)
    users = data.setdefault("users", {})
    users[_norm(name)] = {
        "id": slack_id,
        "name": name,
        "source": source,
        "learned": dt.date.today().isoformat(),
    }
    _save_local(data)


def promote() -> int:
    """Fold the local overlay into the committed store. -> count promoted.

    Run on the LAPTOP and commit the result; that is how a learned id reaches
    every other machine.
    """
    base = _read(STORE_PATH)
    users = base.setdefault("users", {})
    new = local_only()
    users.update(new)
    base["_note"] = (
        "Slack IDs learned from humans hand-tagging people a report said it "
        "could not tag. Committed so every machine shares them. Runtime writes "
        "go to the gitignored local overlay instead (see LOCAL_PATH) and are "
        "folded in here with --promote."
    )
    STORE_PATH.write_text(
        json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(new)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Learned Slack ids")
    ap.add_argument("--promote", action="store_true",
                    help="fold this machine's learned ids into the committed "
                         "store (then commit it)")
    a = ap.parse_args(argv)
    if a.promote:
        n = promote()
        print("Promoted {} learned id(s) into {}.".format(n, STORE_PATH))
        print("Commit it so the other machines get them." if n else
              "Nothing new to promote.")
        return 0
    for key, rec in sorted(known().items()):
        mark = " (local, uncommitted)" if key in local_only() else ""
        print("{:<26} {}{}".format(rec.get("name", key), rec.get("id"), mark))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())


def _display_names(client, user_id: str) -> List[str]:
    """Every name Slack knows this user by — real, display, and profile names.

    All of them, because which one matches the report's spelling varies: OBCL
    says "Lakeaih Gregory", Slack shows "Keaih", and the roll call renders
    "thomas crenshaw" in lower case.
    """
    try:
        prof = (client.users_info(user=user_id) or {}).get("user") or {}
    except Exception as exc:  # noqa: BLE001 — one bad id must not stop the rest
        # Say WHY. Swallowing this returns an empty name list, which looks
        # exactly like "nobody was hand-tagged" — the report then re-posts the
        # same unreachable names and nothing anywhere says the lookup failed.
        # That cost a debugging round on 2026-08-30 (the caller was passing a
        # None client), and a token missing `users:read` would look identical.
        print("[tag-learning] couldn't resolve {}: {}".format(
            user_id, str(exc)[:120]))
        return []
    p = prof.get("profile") or {}
    out = [prof.get("real_name"), prof.get("name"), p.get("real_name"),
           p.get("display_name"), p.get("real_name_normalized"),
           p.get("display_name_normalized")]
    return [n for n in out if n]


def _matches(candidate: str, names: Iterable[str]) -> bool:
    """Does any of Slack's names for this person mean `candidate`?

    Exact on the normalized form, then first-name + last-initial — the same
    loose rule the New-Start roster already uses, so "Thomas C" matches "Thomas
    Crenshaw" but "Jordan Castillo" never matches "Jordan Ruiz".
    """
    want = _norm(candidate)
    if not want:
        return False
    for raw in names:
        got = _norm(raw)
        if not got:
            continue
        if got == want:
            return True
        wp, gp = want.split(), got.split()
        if wp and gp and wp[0] == gp[0] and len(wp) > 1 and len(gp) > 1 \
                and wp[-1][0] == gp[-1][0]:
            return True
    return False


def learn_from_replies(client, replies: List[dict], candidates: Iterable[str],
                       *, after_ts: Optional[str] = None, source: str = "",
                       save: bool = True) -> Dict[str, str]:
    """-> {candidate name: slack id} for every candidate a human hand-tagged.

    `candidates` is the report's own "couldn't tag" list. `after_ts` limits the
    scan to replies after a given message (pass the post that carried the
    list, so an unrelated older mention can't be read as an answer to it).
    """
    wanted = [c for c in candidates if c and c.strip()]
    if not wanted:
        return {}

    # Collect mention ids first so users.info is called once per PERSON, not
    # once per (person x candidate).
    ids = []  # type: List[str]
    for msg in replies or []:
        if after_ts and float(msg.get("ts", 0)) <= float(after_ts):
            continue
        for uid in MENTION_RE.findall(msg.get("text", "") or ""):
            if uid not in ids:
                ids.append(uid)
    if not ids:
        return {}

    resolved = {uid: _display_names(client, uid) for uid in ids}
    found = {}  # type: Dict[str, str]
    for cand in wanted:
        for uid, names in resolved.items():
            if _matches(cand, names):
                found[cand] = uid
                if save:
                    remember(cand, uid, source=source or "hand-tag in thread")
                break
    return found
