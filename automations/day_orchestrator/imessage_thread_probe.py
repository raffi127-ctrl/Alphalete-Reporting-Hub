"""Read-only probe of THIS machine's Messages DB to find the CURRENT A-Team
group thread GUID vs the one Texas de Brazil is configured to send to.

WHY: TdB's iMessage step reports "sent" with no error, but the text doesn't
arrive. The likely cause: the configured chat GUID
(iMessage;+;chat72256665735645227) points at a STALE copy of the group — a
membership change mints a NEW chat GUID, so osascript keeps "sending" into a
defunct thread nobody sees. This finds where the live group actually is.

STRICTLY READ-ONLY + METADATA ONLY. Opens ~/Library/Messages/chat.db in
read-only mode and reads only: chat GUID, chat_identifier, display name,
participant COUNT, and the last-message TIMESTAMP. It NEVER reads message text
and NEVER sends anything. Needs Full Disk Access for the running process; if the
DB won't open it says so and prints the one-liner to run by hand instead.

    lucy rerun probe_imessage_threads            # run on the mini (Lucy 1)
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import sys

DB = os.path.expanduser("~/Library/Messages/chat.db")
CONFIGURED = "chat72256665735645227"    # token inside TdB's IMESSAGE_CHAT_ID
APPLE_EPOCH = 978307200                 # 2001-01-01 UTC, in unix seconds


def _local(apple) -> str:
    if not apple:
        return "(never)"
    secs = apple / 1e9 if apple > 1e11 else float(apple)   # ns (modern) vs s (legacy)
    try:
        return dt.datetime.fromtimestamp(APPLE_EPOCH + secs).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return "(unparseable %r)" % apple


_OSA = '''
tell application "Messages"
  set r to ""
  try
    set cfg to (chats whose id contains "chat72256665735645227")
    set r to r & "CONFIGURED_chat_count: " & (count of cfg) & linefeed
    repeat with c in cfg
      set r to r & "  cfg_id: " & (id of c) & linefeed
    end repeat
  on error e
    set r to r & "CONFIGURED lookup error: " & e & linefeed
  end try
  try
    set named to (chats whose name contains "A-Team" or name contains "A Team" or name contains "Alphalete")
    set r to r & "NAMED_match_count: " & (count of named) & linefeed
    repeat with c in named
      set nm to ""
      try
        set nm to name of c as text
      end try
      set pc to 0
      try
        set pc to count of participants of c
      end try
      set r to r & "  named_id: " & (id of c) & " || name=" & nm & " || participants=" & pc & linefeed
    end repeat
  on error e
    set r to r & "NAMED lookup error: " & e & linefeed
  end try
  return r
end tell
'''


def _osascript_fallback() -> int:
    """Ask Messages.app directly (osascript / Automation permission — the same
    grant TdB uses to SEND, NOT Full Disk Access). Returns GUIDs for the
    configured chat + any A-Team/Alphalete-named chats. No message text, no send.
    Limited: AppleScript can't give last-message timestamps and may not expose
    group display names on every macOS — if it comes back empty, the group name
    isn't queryable this way and the chat.db one-liner is the only path."""
    print("--- osascript -> Messages fallback (Automation permission, not FDA) ---")
    try:
        r = subprocess.run(["osascript", "-e", _OSA],
                           capture_output=True, text=True, timeout=90)
    except Exception as e:  # noqa: BLE001
        print("osascript failed to launch:", repr(e))
        return 1
    if r.returncode != 0:
        print("osascript FAILED (likely no Automation permission for the poller "
              "process, or Messages not running):")
        print("  " + (r.stderr or "").strip()[:400])
        return 1
    out = (r.stdout or "").strip()
    if not out:
        print("osascript returned NOTHING — AppleScript can't see the group name "
              "on this macOS. Use the chat.db one-liner below.")
        return 1
    print(out)
    return 0


def main() -> int:
    if not os.path.exists(DB):
        print("chat.db NOT found at", DB)
        print("=== done ===")
        return 1
    try:
        con = sqlite3.connect("file:%s?mode=ro&immutable=1" % DB, uri=True, timeout=20)
        cur = con.cursor()
    except Exception as e:  # noqa: BLE001
        print("CANNOT open chat.db — no Full Disk Access for this process:", repr(e))
        print()
        rc = _osascript_fallback()   # different permission (Automation, not FDA)
        print()
        print("If both paths failed, run this on the mini (Terminal with FDA):")
        print("  sqlite3 \"file:$HOME/Library/Messages/chat.db?mode=ro\" \\")
        print("    \"SELECT chat_identifier, display_name FROM chat WHERE display_name "
              "LIKE '%A-Team%' OR display_name LIKE '%Alphalete%';\"")
        print("=== done ===")
        return rc

    def rows(where, params=()):
        cur.execute("""
            SELECT c.guid, c.chat_identifier, c.display_name,
                   (SELECT COUNT(*) FROM chat_handle_join j WHERE j.chat_id = c.ROWID),
                   (SELECT MAX(m.date) FROM chat_message_join cmj
                      JOIN message m ON m.ROWID = cmj.message_id
                     WHERE cmj.chat_id = c.ROWID)
            FROM chat c %s
        """ % where, params)
        return cur.fetchall()

    print("CONFIGURED token:", CONFIGURED)
    print()

    print("=== 1. Does the CONFIGURED chat still exist here? ===")
    conf = rows("WHERE c.chat_identifier = ? OR c.guid LIKE ?",
                (CONFIGURED, "%" + CONFIGURED))
    if not conf:
        print("  NOT FOUND — the configured thread no longer exists in this DB.")
    for g, cid, dn, n, last in conf:
        print("  name=%r  participants=%s  last_msg=%s" % (dn, n, _local(last)))
        print("    guid=%s" % g)
    print()

    print("=== 2. Chats whose NAME looks like the A-Team / Alphalete group ===")
    named = rows("WHERE c.display_name LIKE '%A-Team%' OR c.display_name LIKE '%A Team%' "
                 "OR c.display_name LIKE '%ATeam%' OR c.display_name LIKE '%Alphalete%'")
    if not named:
        print("  (none matched by name)")
    for g, cid, dn, n, last in sorted(named, key=lambda r: (r[4] or 0), reverse=True):
        print("  last_msg=%s  participants=%s  name=%r" % (_local(last), n, dn))
        print("    guid=%s" % g)
    print()

    print("=== 3. Top 10 most-recently-active GROUP chats (>=3 participants) ===")
    print("    (catches a re-formed group that lost/changed its display name)")
    grp = rows("WHERE (SELECT COUNT(*) FROM chat_handle_join j WHERE j.chat_id = c.ROWID) >= 3")
    for g, cid, dn, n, last in sorted(grp, key=lambda r: (r[4] or 0), reverse=True)[:10]:
        print("  last_msg=%s  participants=%s  name=%r" % (_local(last), n, dn))
        print("    guid=%s" % g)

    con.close()
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
