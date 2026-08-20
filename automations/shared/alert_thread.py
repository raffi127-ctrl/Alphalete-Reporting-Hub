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

import re
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


# --------------------------------------------------------------- headline ---
# NO EMOJI IN THE CHANNEL, AND ONE SHORT LINE (Megan 2026-08-18)
#
# The channel had become unreadable a second way. The parent posts carried their
# own emoji — 🚨 / ✅ / 🕐 / 📋 / ❌ — and Megan works these tickets by REACTION:
# :pending: on what someone has taken, ✅ on what's done. When the message text
# is full of emoji too, the reactions stop standing out and the list has to be
# read word by word instead of scanned. Her words: "when an emoji is in the
# actual alert that you send, it gets confusing and all bogged up … that way I
# can just see the emojis that we're using as reactions."
#
# And the parent was still too long: split_for_thread's ~420-char budget let 3-4
# full sentences stay up top. So the channel line is now exactly one thing —
# WHAT broke and a few words on WHY — and everything else (the full headline,
# the error, the missing list, the re-run, the paste-to-Claude block) lives in
# the thread. Nothing is dropped; it moves.
#
#   before   🚨 *Alphalete Org Sales Board* — ran, but 1 didn't fill
#            *Error:* Didn't fill: section: BOX — 1 part(s) missing this run.
#            🕐 2 new captainship rep(s) waiting for a ✅ in #revision-emails: …
#   after    *Alphalete Org Sales Board* — ran, but 1 didn't fill
#
# Bold stays: it is not an emoji, and it is what makes the report name findable
# when twenty of these are stacked in the channel.

# Emoji, both spellings Slack accepts. The shortcode half must only fire at a
# word boundary — `~7:00` and `Error: boom` are not emoji and must survive.
_EMOJI_CHARS = re.compile(
    "["
    "\U0001F000-\U0001FAFF"     # pictographs, transport, symbols, faces
    "\u2600-\u27BF"             # ✅ ⚠ ❌ ⛔ ☑ ✉ ...
    "\u2B00-\u2BFF"             # ⬛ ⭐ ...
    "\u2122\u2139\u3030\u303D"
    "\uFE0E\uFE0F\u20E3\u200D"  # variation selectors, keycap, ZWJ joiner
    "]+")
_EMOJI_CODE = re.compile(r"(?:(?<=\s)|(?<=^)):[a-z0-9][a-z0-9_+'-]*:(?=\s|$|[.,;!?])")

# How much of a reason may stay in the channel. Megan asked for "a three to five
# word breakdown of why it failed"; the CHAR cap is what actually holds the line
# short (eight one-syllable words are not the problem, one 90-char sentence is),
# and the word cap stops a run-on of tiny words sneaking under it. The caps are
# deliberately a little looser than "five words" — cutting "1 of 12 office(s) did
# not sync" down to five loses the verb, and a reason that no longer says what
# went wrong costs more than the four characters it saved.
REASON_CHARS = 52
REASON_WORDS = 8
# Where a reason ENDS. The first of these closes the clause: what follows is
# elaboration, and elaboration belongs in the thread.
_CLAUSE = (" — ", " – ", " · ", "; ", ". ", " (")


def strip_emoji(text: str) -> str:
    """`text` with every emoji removed — unicode ones and `:shortcodes:` alike.

    Leaves ordinary punctuation alone (a `:` inside `Error:` or `7:00` is not a
    shortcode), and collapses the double spaces the removal leaves behind."""
    s = _EMOJI_CODE.sub("", str(text))
    s = _EMOJI_CHARS.sub("", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


# Slack italics: `_like this_`. The underscores have to sit on a WORD BOUNDARY —
# which is exactly what tells them apart from the ones inside `out_of_bounds`.
# The lookarounds are the whole point of this regex, so don't "simplify" them:
#   (?<!\w)_  the opener may not follow a word character  → `out_of` never opens
#   (?=\S)    no `_ spaced _`; italics hug their text
#   _(?!\w)   the closer may not precede one              → `of_bounds` never closes
_ITALIC = re.compile(r"(?<!\w)_(?=\S)([^_]+?)(?<=\S)_(?!\w)")


def demarkup(text: str) -> str:
    """`text` with Slack's formatting characters dropped — but NOT the ones that
    are part of a name.

    WHY THIS IS NOT `re.sub(r"[*_`]", "", …)` (Megan 2026-08-20). It was, and it
    ate every underscore it found, identifiers included: the channel line for a
    dropped out-of-bounds section came out as "jamis: outofbounds", and
    `b2b_box` as `b2bbox`. Half our report and section ids are snake_case, so
    that fires constantly — headline() builds the channel line for every alert
    that doesn't pass an explicit channel_line, so this was mangling live posts,
    not just the incident_reformat catch-up pass. (It also made that pass unsafe
    to run: on 2026-08-20 it wanted to rewrite two perfectly good posts purely to
    strip those underscores.)

    `*` and backtick are still dropped outright — no id we alert about contains
    either, so there is nothing to protect and a stray one is just noise."""
    return _ITALIC.sub(r"\1", str(text)).replace("*", "").replace("`", "")


def _clause(reason: str) -> str:
    """The FIRST clause of `reason` — everything up to the first ' — ', ' · ',
    '. ', etc. "Didn't fill: section: BOX — 1 part(s) missing this run." is
    "Didn't fill: section: BOX"."""
    cut = len(reason)
    for sep in _CLAUSE:
        i = reason.find(sep)
        if 0 < i < cut:
            cut = i
    return reason[:cut].strip()


def _drop_scope(reason: str, max_chars: int, max_words: int) -> str:
    """Shed a short SCOPE prefix if that's what makes the reason fit whole.

    "morning run: 1 of 12 office(s) did not sync" cut to the caps loses the verb
    — "morning run: 1 of 12 office(s)…" — while dropping the two-word scope keeps
    the entire sentence. Only tried when the reason overflows, so a clause that
    already fits ("Didn't fill: section: BOX") is never taken apart."""
    if _fits(reason, max_chars, max_words) or ": " not in reason:
        return reason
    prefix, rest = reason.split(": ", 1)
    if len(prefix.split()) <= 3 and _fits(rest, max_chars, max_words):
        return rest.strip()
    return reason


def _fits(s: str, max_chars: int, max_words: int) -> bool:
    return len(s) <= max_chars and len(s.split()) <= max_words


def _trim(reason: str, max_chars: int = REASON_CHARS,
          max_words: int = REASON_WORDS) -> str:
    """Cut `reason` to the caps, on a WORD boundary, marking the cut with '…' so
    nobody reads a chopped line as the whole story (the rest is in the thread)."""
    reason = _drop_scope(reason, max_chars, max_words)
    words = reason.split()
    cut = " ".join(words[:max_words])
    short = len(cut) < len(reason)
    while len(cut) > max_chars and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
        short = True
    cut = cut.rstrip(" ,;:-–—")
    if len(cut) > max_chars:                 # one very long word — hard cut
        cut, short = cut[:max_chars], True
    return (cut + "…") if short and cut else cut


def _reason_from(body: Sequence[str]) -> str:
    """The best one-line WHY out of an alert body: the `*Error:*` line if there
    is one (every orchestrator failure has it), otherwise the first real line."""
    plain = [strip_emoji(l) for l in body]
    for l in plain:
        m = re.match(r"^[*_]*Error:?[*_]*\s*[:\-–—]?\s*(.+)$", l.strip(), re.I)
        if m:
            return m.group(1)
    for l in plain:
        if l.strip():
            return l.strip()
    return ""


def headline(title: str, body: Sequence[str] = ()) -> str:
    """The ONE line the channel gets: `*What broke* — a few words on why`.

    No emoji, no second sentence, no list — see the note above. The full text is
    never lost: incident_thread posts it as the first reply in the thread.
    """
    t = strip_emoji(title).strip()
    name, rest = "", t
    m = re.match(r"^\*([^*]+)\*\s*(.*)$", t)      # `*Report Name* — why`
    if m:
        name, rest = m.group(1).strip(), m.group(2).strip()
    else:
        for sep in (" — ", " – ", " - "):
            i = t.find(sep)
            if i > 0:
                name, rest = t[:i].strip(), t[i + len(sep):].strip()
                break
    reason = rest.lstrip(" -–—:·").strip()
    if len(reason) < 3 and name:
        # The WHOLE headline was bolded — "*Daily Recruiting Focus — 1 ICD(s)
        # not pulled today*" — so the name swallowed the reason and the body's
        # first bullet would have been promoted in its place. Split the bold.
        for sep in (" — ", " – ", " - "):
            i = name.find(sep)
            if i > 0:
                name, reason = name[:i].strip(), name[i + len(sep):].strip()
                break
    if len(reason) < 3:                            # the title was just a name
        reason = _reason_from(body)
    reason = _trim(_clause(demarkup(reason).strip()))
    if not name:
        return _trim(_clause(demarkup(t)), max_chars=90,
                     max_words=12) or t[:90]
    return "*{}* — {}".format(name, reason) if reason else "*{}*".format(name)


def same_story(head: str, lines: Sequence[str]) -> bool:
    """True when `head` already IS the whole alert — a one-line ping whose text
    the headline kept verbatim. Threading a copy of it under itself is noise."""
    body = [strip_emoji(l) for l in lines]
    body = [l for l in body if l.strip()]
    if len(body) != 1:
        return False
    return re.sub(r"[*_`\s]+", " ", strip_emoji(head)).strip() == \
        re.sub(r"[*_`\s]+", " ", body[0]).strip()
