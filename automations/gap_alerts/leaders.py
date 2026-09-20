"""Who gets tagged on the day's KNOCKS & DISPOSITIONS post.

Megan's Loom, 2026-09-20: *"from the sales board, just take everyone who's
ranked as a leader, and then tag them in the chat... it only needs to tag them
one time, on the first post... so it just tags every single leader that's on
the sales board that is not terminated. So if it counts as terminated, don't
tag them."*

SOURCE IS THE SALES BOARD, not OwnerVille. The rest of gap_alerts reads
OwnerVille (who is knocking, who has gone dark); leadership rank and
termination only exist on the 'Alphalete SALES BOARD 2025' workbook, the same
one terminated_reps files from. Read ONCE a day -- the parent post is created
once, so this costs one worksheet read per office per day, not one per tick.

WHY IT GOES THROUGH terminated_reps.board. Terminated is marked THREE different
ways on that tab (a filled 'Termination Date', a bare 'T' anywhere in a day
block, and 'Terminated' in the New Starts box) and that reader is the only
place in the repo that knows all three. Reading just the date column would have
tagged 15 of the 15 people WE 8.23 terminated. A second, simpler reader here
would drift from it silently -- and the cost of drifting is @-pinging somebody
who was let go, in front of the whole room.

EVERY COLUMN BY LABEL: the rep names by the roster's '#'/'WE m/d-' anchor,
'Leadership Status' and 'Termination Date' by their ROW 1 titles. The board
gains and loses columns weekly. [[feedback_no_hardcoded_columns]]

THE NEW STARTS BOX IS DELIBERATELY NOT READ. Everyone in it is 'In Training'
by definition (alphalete_sales_board.fill.LEADERSHIP_NEW), so it can only ever
contribute non-leaders -- and its rows carry no Leadership Status column at all.

Python 3.9-safe.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from automations.terminated_reps import board as BD

# Row-1 title of the rank column. Folded the same way BD folds its own titles.
COL_LEADERSHIP = "leadership status"

# What counts as "ranked as a leader". The board's ladder is
# In Training -> Entry Level -> Level 1 -> Level 2 -> Mastermind
# (automations.promotion_checkin.config.LADDER). The first two are the people
# the board is ABOUT -- reps still being trained and reps with nobody under
# them. Tagging them would make the tag line the whole roster, which is the
# thing this post exists to stop.
LEADER_LEVELS = ("level 1", "level 2", "mastermind")

# The report name suppression is scoped by. [[shared.slack_suppression]]
REPORT = "gap_alerts"

# Trailing tenure markers the board hangs off a name: '(Wk 2)', '(NC)', '(RT)'.
# Stripped for DISPLAY only -- an internal nickname like '(Ivette)' stays,
# because that is often the name Slack knows them by.
_TENURE = re.compile(r"\s*\((?:wk\s*\d+|nc|rt)\)\s*$", re.I)


@dataclass(frozen=True)
class Leader:
    name: str     # as the board spells it, tenure marker stripped
    level: str    # folded: 'level 1' / 'level 2' / 'mastermind'
    row: int      # the roster row, so a surprise is traceable to a cell


def display_name(raw: str) -> str:
    """'Ivan Soto (Wk 2)' -> 'Ivan Soto'. Case preserved: this is the string a
    human reads in the post when we could not tag them."""
    return _TENURE.sub("", " ".join(str(raw or "").replace("\xa0", " ").split())).strip()


def leaders_from_grid(grid: list) -> List[Leader]:
    """One week tab -> its non-terminated leaders, in board order."""
    lay = BD.find_layout(grid)
    titles = {BD._norm(v): i for i, v in enumerate(grid[0], 1) if BD._norm(v)}
    col = titles.get(COL_LEADERSHIP)
    if not col:
        # Raise rather than return nothing: an empty list and a missing column
        # look identical in the post (no tags), and only one of them is a bug.
        raise BD.BoardLayoutError(
            "Row 1 has no %r column -- can't tell who is a leader. Found: %s"
            % (COL_LEADERSHIP, sorted(t for t in titles if t)[:25]))

    out = []  # type: List[Leader]
    for r in lay.roster_rows:
        raw = str(BD._cell(grid, r, lay.name_col) or "").strip()
        if not raw:
            continue
        level = BD._norm(BD._cell(grid, r, col))
        if level not in LEADER_LEVELS:
            continue
        # Terminated, both ways the roster says it. A CONTRADICTED 'T' (what
        # terminated_reps files as a Check) still drops the tag: the board is
        # saying it does not know, and "don't ping" is the safe side of that.
        if BD.to_date(BD._cell(grid, r, lay.term_col)) is not None:
            continue
        if BD.day_marks(grid, r, lay.day_blocks):
            continue
        out.append(Leader(name=display_name(raw), level=level, row=r))
    return out


def read_leaders(today: Optional[dt.date] = None, *, tab: Optional[str] = None,
                 logfn=print) -> Tuple[List[Leader], str]:
    """(leaders, tab title) off the current 'Sales Board WE m.d' tab.

    ONE tab, not the two terminated_reps reads: this asks "who is a leader
    RIGHT NOW", and last week's tab can only answer for last week's roster.
    """
    today = today or dt.date.today()
    sh = BD.open_by_key(BD.SHEET_ID)
    title = BD.pick_tab(sh, today, tab)
    grid = sh.worksheet(title).get_values(value_render_option="UNFORMATTED_VALUE")
    found = leaders_from_grid(grid)
    logfn("  %r: %d leader(s) not terminated" % (title, len(found)))
    return found, title


# --------------------------------------------------------------- slack tags
def _fold(s: str) -> str:
    """Drop the ACCENT, keep the LETTER: 'Vázquez' -> 'Vazquez',
    "De'Avioñ" -> "De'Avion", 'Anh Đinh' -> 'Anh dinh'.

    This is the whole reason Lemsy Vázquez came back "no Slack account" on the
    first live read (Megan's screenshot, 2026-09-20): the board writes her
    'Lemsy Vazquez', Slack writes 'Lemsy Vázquez', and stripping the accented
    character took the letter with it — 'vazquez' vs 'v zquez', which share no
    word at all. Same bug new_start_followup fixed on 2026-08-03 and
    slack_tag_learning carries the fix for; `energy_crossref.roster.words`,
    which this folding was copied from, still has it.
    """
    s = unicodedata.normalize("NFKD", s or "")
    # A few letters NFKD does not decompose to ASCII + a combining mark.
    s = (s.replace("đ", "d").replace("Đ", "d").replace("ø", "o")
          .replace("Ø", "o").replace("ł", "l").replace("Ł", "l"))
    return "".join(c for c in s if not unicodedata.combining(c))


def _words(s: str) -> set:
    """A name's comparable words: accents FOLDED, parentheses opened up (the
    only place 'Timothy' appears in 'Qilu(Timothy) Zhao'), tenure tags and
    punctuation dropped."""
    s = _fold(str(s or "")).lower().replace("(", " ").replace(")", " ")
    s = re.sub(r"\b(wk|week|nc|rt)\s*\d*\b", " ", s)
    return {w for w in re.sub(r"[^a-z ]", " ", s).split()
            if w not in {"jr", "sr", "ii", "iii"}}


# users.list is Slack Tier 2 and this walks it a page at a time, so a workspace
# this size can trip the limit mid-walk. `slack_metrics_post`'s client installs
# slack_sdk's DEFAULT retry handlers, which cover a dropped connection and NOT a
# 429 -- so the page-through has to wait out its own rate limit or the day's tag
# line silently loses everyone the curated sources did not already cover.
_RATELIMIT_TRIES = 3
_RATELIMIT_FALLBACK_SLEEP = 30.0


def _retry_after(exc) -> float:
    """Slack's own Retry-After, in seconds. Its header is authoritative --
    guessing shorter just burns the next attempt on another 429."""
    try:
        return float((exc.response.headers or {}).get("Retry-After"))
    except Exception:  # noqa: BLE001
        return _RATELIMIT_FALLBACK_SLEEP


def _is_ratelimited(exc) -> bool:
    try:
        return (exc.response or {}).get("error") == "ratelimited"
    except Exception:  # noqa: BLE001
        return False


def _workspace(client, *, logfn=print, sleeper=None) -> List[dict]:
    """Every active human in the workspace. One page-through, done once a day
    -- this is the expensive half."""
    import time
    members, cursor = [], None
    while True:
        for attempt in range(1, _RATELIMIT_TRIES + 1):
            try:
                resp = client.users_list(limit=200, cursor=cursor)
                break
            except Exception as exc:  # noqa: BLE001 -- re-raised below
                if not _is_ratelimited(exc) or attempt == _RATELIMIT_TRIES:
                    raise
                wait = _retry_after(exc)
                logfn("  users.list rate-limited — waiting %.0fs (%d/%d)"
                      % (wait, attempt, _RATELIMIT_TRIES - 1))
                (sleeper or time.sleep)(wait)
        members.extend(resp.get("members", []))
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return [u for u in members if not u.get("deleted") and not u.get("is_bot")]


def _from_workspace(members: Sequence[dict], name: str) -> str:
    """The one active account whose name means `name`, or ''.

    REFUSES ON 2+ HITS rather than guessing. The workspace has real collisions
    (two live 'Miguel Vargas' accounts -- see energy_crossref.roster), and a
    wrong tag @-pings a stranger into somebody else's sales room every day
    until a human notices.
    """
    want = _words(name)
    if len(want) < 2:      # 'Miguel' alone must never resolve to anyone
        return ""
    hits = set()
    for u in members:
        p = u.get("profile") or {}
        for cand in (u.get("real_name", ""), p.get("real_name", ""),
                     p.get("display_name", "")):
            got = _words(cand)
            if len(got) >= 2 and (got <= want or want <= got):
                hits.add(u["id"])
    return hits.pop() if len(hits) == 1 else ""


def _new_start_roster():
    """The New-Start leader roster, or None.

    Megan 2026-09-20: *"tag every lvl 1 leader and above LIKE IT DOES IN THE
    NEW START TEXT FUNCTION."* That roster is the curated answer to the exact
    problem here -- three name-spaces that do not agree. The board says
    'Elijah Rodriguez', Slack says 'Eli Rodriguez'; the board says 'Noemi
    (Ivette) Ontiveros', Slack says 'Noemi Rivera'. No name matcher gets those,
    and a human already wrote them down in leaders.json as `obcl_names`.

    It is the FIRST source for that reason, and it is the same file the roll
    call tags off -- so the two posts name the same person the same way, and a
    leader added there is picked up by both.
    """
    try:
        from automations.new_start_followup import roster as NSR
        return NSR.load()
    except Exception:  # noqa: BLE001 -- a missing roster falls through
        return None


def resolve_tags(names: Sequence[str], *, client=None,
                 logfn=print) -> Tuple[List[str], List[str]]:
    """-> (slack ids to tag, names we could not tag).

    Order, and it matters: SUPPRESSION FIRST. A do-not-ping person is dropped
    silently and is not reported as untagged either -- listing them would just
    move the nagging from the person to the room.
    [[shared.slack_suppression]] beats every lookup below it.

    Then the curated sources before the guessing one: the New-Start leader
    roster (hand-written aliases), then ids learned from a human hand-tag
    ([[shared.slack_tag_learning]]), and only then a users.list name match.

    An id we resolve off the workspace is REMEMBERED, so the next machine that
    posts this does not have to page users.list to find the same person.
    """
    from automations.shared import slack_suppression as sup
    from automations.shared import slack_tag_learning as tl

    kept, dropped = sup.filter_names([display_name(n) for n in names], REPORT)
    if dropped:
        logfn("  not tagging %d suppressed name(s): %s"
              % (len(dropped), ", ".join(dropped)))

    nsr = _new_start_roster()
    ids, missing, seen = [], [], set()
    members = None  # paged lazily: a fully-resolved roster never calls users.list
    for name in kept:
        hit = nsr.by_obcl_name(name) if nsr is not None else None
        uid = hit.slack_id if hit else ""
        if not uid:
            uid = tl.lookup(name)
        if not uid:
            if members is None:
                try:
                    members = (_workspace(client, logfn=logfn)
                               if client is not None else [])
                except Exception as e:  # noqa: BLE001
                    # A token without users:read is the normal case on some
                    # boxes, not an error -- say it once and name the rest in
                    # plain text. [[energy_crossref.roster]]
                    logfn("  users.list unavailable (%s: %s) -- the untagged "
                          "are named in the post instead"
                          % (type(e).__name__, str(e)[:100]))
                    members = []
            uid = _from_workspace(members, name)
            if uid:
                try:
                    tl.remember(name, uid, source="gap_alerts leader tag")
                except Exception:  # noqa: BLE001 -- learning must never fail a post
                    pass
        if not uid:
            missing.append(name)
            continue
        if uid in seen:
            continue
        seen.add(uid)
        ids.append(uid)
    return ids, missing


def tag_line(ids: Sequence[str], missing: Sequence[str] = ()) -> str:
    """The mention block that goes under the title on the day's parent post.

    A leader with no Slack account is NAMED, never dropped: the whole ask is
    "tag every leader", and a name silently missing from the line is
    indistinguishable from a leader who was never on the board.
    """
    parts = [" ".join("<@%s>" % i for i in ids)] if ids else []
    if missing:
        parts.append("_(no Slack account: %s)_" % ", ".join(missing))
    return "\n".join(p for p in parts if p)
