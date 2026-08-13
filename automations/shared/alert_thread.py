"""Keep #claudecorrections-and-requests skimmable: short parent, detail in-thread.

WHY THIS EXISTS (2026-08-13): the Vantura board audit's "dropped 13 sections"
alert dumped all 13 full-sentence findings — plus the note and the fix — into the
CHANNEL message. One alert filled the whole screen, so every other report's alert
was pushed out of view (Megan: "this error is too long in the slack channel — it
should be in the reply on the thread"). Some alerts already split parent/reply by
hand (day_orchestrator.notify); these helpers make it the default for ANY alert,
including long ones nobody has written yet.

Two pure text helpers, no Slack calls — the posting stays with each caller:
  split_for_thread(lines) -> (parent_lines, detail_lines)
      Keeps the headline + a couple of one-line facts up top and pushes the bulk
      down. A ``` fence ALWAYS starts the detail: a paste-to-Claude block or a log
      tail is never what the channel should show at a glance.
  chunk(lines)             -> ["msg", "msg", ...]
      Packs the detail into as many replies as it takes to stay under Slack's
      per-message limit — chunked, never truncated, so no finding is lost. Fenced
      blocks that straddle a chunk are re-opened, so a split never leaks raw
      backticks into the rendered text.

3.9-safe (the mini runs 3.9). [[project_corrections_slack_channel]]
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

# Slack hard-caps a message at 4000 chars. Stay well under: the API counts the
# text AFTER our join, and a chunk that comes back "msg_too_long" is a LOST
# finding, which is exactly the failure this module exists to prevent.
CHUNK_LIMIT = 2800

# How much of the body may stay in the channel. ~4 short lines: enough for a
# headline + the one-line fix, not enough for a list of 13 findings.
PARENT_LIMIT = 420

FENCE = "```"
MORE = "_… full detail in the thread ↓_"


def _fence_line(s: str) -> bool:
    return str(s).strip().startswith(FENCE)


def split_for_thread(lines: Sequence[str], limit: int = PARENT_LIMIT,
                     more: str = MORE) -> Tuple[List[str], List[str]]:
    """Split an alert body into (channel parent, threaded detail).

    The first line (the headline) always stays, however long it is — a parent
    with no title reads as a stray reply. After that, lines join the parent only
    while the running length fits `limit`, and a fenced block ends the parent
    outright. When anything is deferred, the parent gets a pointer line so the
    channel says where the rest went.
    """
    lines = [l for l in lines]
    if not lines:
        return [], []
    parent = [lines[0]]
    used = len(str(lines[0]))
    i = 1
    while i < len(lines):
        ln = str(lines[i])
        if _fence_line(ln) or used + len(ln) + 1 > limit:
            break
        parent.append(lines[i])
        used += len(ln) + 1
        i += 1
    detail = list(lines[i:])
    # A trailing blank line left on the parent is just a gap above nothing.
    while parent and not str(parent[-1]).strip():
        parent.pop()
    while detail and not str(detail[0]).strip():
        detail.pop(0)
    if detail and more:
        parent.append(more)
    return parent, detail


def _hard_split(line: str, limit: int) -> List[str]:
    """Break one over-long line at a space near the limit (never mid-word if it
    can be helped) — a single 3000-char finding still has to reach the thread."""
    out = []
    s = str(line)
    while len(s) > limit:
        cut = s.rfind(" ", 0, limit)
        if cut < int(limit * 0.6):      # no sane break point — split hard
            cut = limit
        out.append(s[:cut])
        s = s[cut:].lstrip()
    if s:
        out.append(s)
    return out


def chunk(lines: Sequence[str], limit: int = CHUNK_LIMIT,
          label: bool = True) -> List[str]:
    """Pack `lines` into as few messages as possible under `limit` chars each.

    Nothing is dropped: an over-long single line is split, and a ``` block that
    spans a boundary is closed and re-opened so both halves still render as code.
    With more than one message each gets a `(1/3)` marker so a reader can tell a
    continuation from a new problem.
    """
    # Expand embedded newlines FIRST: a caller that hands over a whole log tail
    # as one string should still break at line ends, not mid-word (and a ``` on
    # its own line has to be visible to the fence tracking below).
    flat: List[str] = []
    for l in lines:
        for s in str(l).split("\n"):
            if len(s) > limit:
                flat.extend(_hard_split(s, limit - 40))
            else:
                flat.append(s)

    msgs: List[str] = []
    cur: List[str] = []
    cur_len = 0
    in_fence = False          # fence state at the END of `cur`
    open_fence = False        # this message started inside a fence

    def flush():
        nonlocal cur, cur_len, open_fence
        if not cur:
            return
        body = list(cur)
        if in_fence:                      # straddling a code block — close it
            body.append(FENCE)
        if open_fence:
            body.insert(0, FENCE)
        msgs.append("\n".join(body))
        cur = []
        cur_len = 0
        open_fence = in_fence

    for s in flat:
        add = len(s) + 1
        # +8 headroom for the fence lines / part marker flush() may add.
        if cur and cur_len + add + 8 > limit:
            flush()
        cur.append(s)
        cur_len += add
        if _fence_line(s):
            in_fence = not in_fence
    flush()

    if label and len(msgs) > 1:
        n = len(msgs)
        msgs = ["_(%d/%d)_\n%s" % (i + 1, n, m) for i, m in enumerate(msgs)]
    return msgs
