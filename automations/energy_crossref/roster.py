"""Board name -> Slack user id, for the tag line.

WHY A LIST AND NOT A LOOKUP. The obvious way to tag someone is `users.list` +
match the name, which is what `slack_metrics_post._resolve_user_id` does. It
can't be the primary route here for two reasons:

  * the Slack token this runs under does not necessarily carry `users:read`
    (the Windows one does not: 'missing_scope, needed: users:read'), and a
    morning check that dies on a scope is a check nobody trusts;
  * the workspace has REAL COLLISIONS. Two active accounts are both "Miguel
    Vargas"; the Energy rep is U0B4HKKSMQA (20 messages in #alphalete-sales in
    three weeks, the other has none). No name match can tell those apart, and
    tagging the wrong one asks a stranger for a webform.

So the ids are pinned here, and `users.list` is only a fallback for a rep who
joins before anyone updates this file. Every id below was read off Slack on
2026-08-14; the five in Evelyn's own 8/13 post (Charley, Edgar, Zoria, Rafael,
Dylan) match hers exactly, which is what says the mapping is the right one.

TO ADD A REP: put their board spelling (col C of the Sales Board) on the left
and their Slack id on the right. A rep with no Slack account is left out — the
post then NAMES them in plain text instead of tagging them, so they are still
called out and the run exits 75.
"""
from __future__ import annotations

import re

# normalised board name -> Slack user id
IDS = {
    # Energy roster, WE 8.16
    "zoria johnson": "U08LSELLCGY",
    "edgar camunez": "U0A80F907N3",
    "thomas crenshaw": "U0AK05E6S11",
    "pranish shrestha": "U0AME3NU5KQ",
    "hayden wilson": "U083XNMHD39",
    "ibukunoluwa olapade ogunlola": "U0AQN5YHV4G",   # Slack: 'Ibukunoluwa Ogunlola'
    "willvim marte": "U0BG5MXP6HZ",
    "miguel angel vargas": "U0B4HKKSMQA",            # NOT U0ACMJ0HHPE — see above
    "ivan soto": "U0BQCJ2BUBS",
    "charley alan perez": "U0BD56X1H40",             # Slack: 'Charley Perez'
    "qilu timothy zhao": "U0BNJ9ZA4GG",              # Slack: 'Timothy Zhao'
    "christian nicholas villarreal": "U0AU0LFR8Q5",  # Slack: 'Christian Villarreal Sr.'
    "juan pablo deleon": "U0A64Q4KZM0",              # Slack: 'Pablo Deleon'
    # Christopher Jacob Rivera has NO Slack account (searched 'Christopher' and
    # 'Rivera', 2026-08-14). He gets named in the post, not tagged.

    # tagged on every post
    "rafael hidalgo": "U045Z8N0ZQC",
    "dylan twaddle": "U048V0YA5FC",
}

_SUFFIX = {"jr", "sr", "ii", "iii"}


def words(s: str) -> set:
    """Name -> its comparable words. Drops '(Wk 2)' / '(NC)' tenure tags, the
    parenthesised English name in 'Qilu(Timothy) Zhao' KEPT (the parens are the
    only place 'Timothy' appears), punctuation and Jr/Sr."""
    s = str(s).lower().replace("(", " ").replace(")", " ")
    s = re.sub(r"\b(wk|week|nc|rt)\s*\d*\b", " ", s)
    return {w for w in re.sub(r"[^a-z ]", " ", s).split() if w not in _SUFFIX}


def _norm(s: str) -> str:
    return " ".join(sorted(words(s)))


_BY_WORDS = {frozenset(words(k)): v for k, v in IDS.items()}


def _from_map(name: str) -> str:
    """The pinned id for `name`, matched on words so a board respelling ('Ivan
    Soto (Wk 2)' -> 'Ivan Soto (Wk 3)', a middle name added or dropped) still
    lands. One side's words have to CONTAIN the other's, and both sides need at
    least two words, so 'Miguel' alone never resolves to anyone."""
    want = words(name)
    if len(want) < 2:
        return ""
    hits = {v for k, v in _BY_WORDS.items()
            if len(k) >= 2 and (k <= want or want <= k)}
    return hits.pop() if len(hits) == 1 else ""


def _from_slack(client, name: str) -> str:
    """Fallback for a rep who isn't pinned yet. Silent when the token has no
    users:read — that is the normal case, not an error."""
    want = words(name)
    if len(want) < 2:
        return ""
    try:
        members, cursor = [], None
        while True:
            resp = client.users_list(limit=200, cursor=cursor)
            members.extend(resp.get("members", []))
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception:
        return ""
    hits = set()
    for u in members:
        if u.get("deleted") or u.get("is_bot"):
            continue
        p = u.get("profile", {})
        for cand in (u.get("real_name", ""), p.get("real_name", ""),
                     p.get("display_name", "")):
            cw = words(cand)
            if len(cw) >= 2 and (cw <= want or want <= cw):
                hits.add(u["id"])
    return hits.pop() if len(hits) == 1 else ""


def resolve(client, names: list[str]) -> list[tuple[str, str]]:
    """[(name, slack id or '')] in order, deduped by id. An empty id means the
    post names them in text — never that they're dropped."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        uid = _from_map(name) or _from_slack(client, name)
        if uid and uid in seen:
            continue
        if uid:
            seen.add(uid)
        out.append((name, uid))
    return out


def display(name: str) -> str:
    """Board name trimmed for a message: 'Ivan Soto (Wk 2)' -> 'Ivan Soto'."""
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", name)).strip()
