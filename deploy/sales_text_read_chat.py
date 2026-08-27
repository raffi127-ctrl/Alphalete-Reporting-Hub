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

    python3 sales_text_read_chat.py "Alphalete Partners" [out.json]
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
PAIR_RE = re.compile(r"^\s*([A-Za-z][\w'.\- ]{0,40}?)\s*(?:={1,2}|\bis\b)\s*"
                     r"([A-Za-z][\w'.\- ]{0,40}?)\s*[.!]?\s*$", re.I)


def main(argv):
    needle = argv[1] if len(argv) > 1 else "Alphalete Partners"
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
