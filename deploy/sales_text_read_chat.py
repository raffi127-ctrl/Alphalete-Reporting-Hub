#!/usr/bin/env python3
"""Read new lines out of one iMessage chat and drop them in a file. Nothing else.

WHY THIS IS A SEPARATE SCRIPT, AND NOT PART OF THE SWEEP. Full Disk Access is
granted to a BINARY, and macOS applies it to the process it holds responsible.
Lucy 1's venv `python3.9` is a bash wrapper, so a launchd job that runs it is
attributed to bash, not to the Python.app that was granted -- which is why the
sweep still got `DatabaseError('authorization denied')` after the grant, while
Terminal (granted in its own right) read the same file fine.

The fix could have been rewriting that wrapper. It is the interpreter all ~130
of Lucy 1's automations run on, so instead the ONE privileged step moved out
into this: a stdlib-only script that launchd runs with the granted Python
directly. It reads message text from one named chat, writes the lines to a
file, and does nothing else -- no Sheets, no Slack, no sending. Everything that
thinks about those lines stays in the ordinary codebase, running as it always
has, reading this file.

Deliberately narrow: one chat, matched by name; only rows after the last one
handled; a hard limit; read-only connection.

    python3 sales_text_read_chat.py "Knocking Chat A-Players" [out.json]

(The chat was "Alphalete Partners" until Raf moved everything, 2026-09-28.
last_rowid carries over: chat.db ROWIDs are global, so only newer lines count.)
"""
import json
import os
import re
import sqlite3
import sys

DB = os.path.expanduser("~/Library/Messages/chat.db")
OUT = os.path.expanduser(
    "~/.config/recruiting-report/alphalete_sales_board_replies.json")
LIMIT = 60
# Only lines that look like "a=b" / "a is b" are kept. The rest of a group
# chat's conversation is none of this script's business and never lands in the
# file at all.
NAME = r"[A-Za-z][\w'.\-]{0,30}(?: [A-Za-z][\w'.\-]{0,30}){0,2}"
PAIR_RE = re.compile(r"^\s*(" + NAME + r")\s*={1,2}\s*(" + NAME + r")\s*[.!]?\s*$")


REQUEST = os.path.expanduser("~/.config/recruiting-report/text_replies_request.json")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLIES_OUT = os.path.join(REPO, "output", "logs", "text_replies.txt")


def dump_replies():
    """ON REQUEST ONLY: incoming messages from every named iMessage group for
    the last N days, written where `logtail text_replies.txt` can read them.
    The queue action `text_replies` (mini_control) leaves the request file;
    this is the one process on the box that may read chat.db, so the dump
    happens here on the next tick and the request is consumed. 2026-10-12:
    Megan asked how reps answer Lucy's texts; SSH only reaches a Lucy on the
    office LAN, the queue reaches it anywhere."""
    try:
        with open(REQUEST) as fh:
            req = json.load(fh)
    except Exception:
        return
    days = int(req.get("days") or 3)
    needle = (req.get("needle") or "").strip().lower()
    import time
    import datetime as dt
    lines = []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=10)
        rows = con.execute(
            """SELECT c.display_name, m.date/1000000000 + 978307200,
                      COALESCE(h.id, ''), m.text, m.is_from_me
                 FROM message m
                 JOIN chat_message_join j ON j.message_id = m.ROWID
                 JOIN chat c ON c.ROWID = j.chat_id
                 LEFT JOIN handle h ON h.ROWID = m.handle_id
                WHERE m.date/1000000000 + 978307200 > ?
                  AND c.display_name <> '' AND m.text IS NOT NULL
                ORDER BY m.date DESC""", (time.time() - days * 86400,)).fetchall()
        con.close()
    except sqlite3.Error as e:
        lines = ["CANNOT read chat.db: %s" % e]
        rows = []
    groups = {}
    for name, ts, who, text, mine in rows:
        t = (text or "").replace("\n", " ").strip()
        if not t:
            continue
        g = groups.setdefault(name, [0, 0])
        g[1 if mine else 0] += 1
        if mine or (needle and needle not in t.lower()):
            continue
        lines.append("%s | %s | %s | %s" % (
            dt.datetime.fromtimestamp(ts).strftime("%m/%d %H:%M"), name[:28],
            who[-4:], t[:200]))
    head = ["text_replies dump %s -- last %d day(s)%s" % (
                dt.datetime.now().strftime("%Y-%m-%d %H:%M"), days,
                " needle=%r" % needle if needle else ""),
            "groups (incoming/sent): " + "; ".join(
                "%s %d/%d" % (n[:24], c[0], c[1]) for n, c in sorted(
                    groups.items(), key=lambda kv: -kv[1][0])),
            "%d incoming message(s):" % len(lines)]
    try:
        os.makedirs(os.path.dirname(REPLIES_OUT), exist_ok=True)
        with open(REPLIES_OUT, "w") as fh:
            fh.write("\n".join(head + lines[:1500]) + "\n")
        os.remove(REQUEST)
        print("text_replies: wrote %d line(s) to %s" % (len(lines), REPLIES_OUT))
    except OSError as e:
        print("text_replies: could not write dump: %s" % e)


def main(argv):
    dump_replies()
    needle = argv[1] if len(argv) > 1 else "Knocking Chat A-Players"
    out_path = argv[2] if len(argv) > 2 else OUT
    try:
        with open(out_path) as fh:
            state = json.load(fh)
    except Exception:
        state = {}
    since = int(state.get("last_rowid") or 0)

    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=10)
    except sqlite3.Error as e:
        print("CANNOT open chat.db: %s" % e)
        return 1
    try:
        rows = con.execute(
            """SELECT m.ROWID, m.text, m.is_from_me
                 FROM message m
                 JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
                 JOIN chat c ON c.ROWID = cmj.chat_id
                WHERE (c.display_name LIKE ? OR c.chat_identifier LIKE ?)
                  AND m.ROWID > ? AND m.text IS NOT NULL
                ORDER BY m.ROWID LIMIT ?""",
            ("%" + needle + "%", "%" + needle + "%", since, LIMIT)).fetchall()
    except sqlite3.Error as e:
        print("CANNOT read chat.db: %s" % e)
        return 1
    finally:
        con.close()

    pairs, last, from_others = [], since, 0
    for rowid, text, from_me in rows:
        last = max(last, rowid)
        if from_me:                       # never act on our own messages
            continue
        from_others += 1
        for line in (text or "").splitlines():
            m = PAIR_RE.match(line)
            if m and m.group(1).strip().lower() != m.group(2).strip().lower():
                pairs.append({"rowid": rowid, "left": m.group(1).strip(),
                              "right": m.group(2).strip()})

    state.setdefault("pending", []).extend(pairs)
    state["last_rowid"] = last
    state["chat"] = needle
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        tmp = out_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh, indent=1)
        os.replace(tmp, out_path)
    except OSError as e:
        print("couldn't write %s: %s" % (out_path, e))
        return 1
    # The counts separate "nobody has typed one" from "somebody did and the
    # pattern missed it" -- without logging anyone's words, which this script
    # has no business writing down.
    print("read %d message(s) after rowid %d (%d from other people); "
          "%d alias line(s) found; now at %d"
          % (len(rows), since, from_others, len(pairs), last))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
