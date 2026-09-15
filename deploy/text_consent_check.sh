#!/bin/bash
# Grant this machine permission to send iMessage, from the identity that will
# actually be sending -- and prove it delivered.
#
#   bash deploy/text_consent_check.sh                      # list the chats
#   bash deploy/text_consent_check.sh "Exact Chat Name"    # send one test
#
# WHY A SCRIPT AND NOT "just send one from a terminal". macOS grants "control
# Messages" per EXECUTABLE IDENTITY. On Lucy 1 the Allow was clicked for
# /bin/bash on a wrapper, which is the identity that job runs as, so it texts.
# On Lucy 2 the Allow went to the mini_control poller instead -- which is
# exactly why b2b_dispositions still cannot send from its scheduled job.
#
# So the consent has to be granted to a BASH WRAPPER, because that is what the
# ICD poster is. Running osascript straight from your shell grants it to your
# terminal and teaches this machine nothing.
#
# AN UNCONSENTED SEND DOES NOT FAIL -- it blocks on a dialog nobody clicks,
# for about five minutes, every tick. That is why gap_alerts asks
# TEXTING_MACHINES first and skips the route out loud. Do not add a machine to
# that set until this script has actually delivered.
#
# AND A WRONG NAME DID NOT FAIL EITHER. The first version fell back to walking
# `chats` looking for a matching name; when none matched, the repeat loop
# simply ended, osascript exited 0 and nothing was sent. Run on Lucy 3 on
# 2026-09-15 against "Alphalete Partners" it reported success and delivered
# nothing. So this version refuses to guess: with no argument it prints every
# chat Messages can actually see, and a send that matches nothing is an error
# with a non-zero exit, not a quiet no-op.

set -u

CHAT="${1:-}"

# --- what can this machine actually see? ------------------------------------
# Group chats frequently have NO name at all -- the display name in the window
# is assembled from the participants. Those can only be addressed by id, which
# is why the id is printed beside every row.
list_chats() {
  osascript <<'APPLESCRIPT'
tell application "Messages"
    set out to ""
    repeat with c in chats
        set theName to ""
        try
            set theName to name of c as string
        end try
        set theId to ""
        try
            set theId to id of c as string
        end try
        if theName is "" then set theName to "(no name -- address it by id)"
        set out to out & theName & "   |   " & theId & linefeed
    end repeat
    return out
end tell
APPLESCRIPT
}

if [ -z "$CHAT" ]; then
  echo ""
  echo "Chats this machine's Messages can see:"
  echo ""
  list_chats
  echo ""
  echo "Run again with one of those names in quotes, exactly as printed."
  echo "If the chat you want shows \"(no name)\", pass its id instead."
  echo ""
  exit 0
fi

MSG="Lucy test — this machine can now text this chat. Ignore."

echo ""
echo "Sending one test message to: $CHAT"
echo ""
echo "macOS may ask whether Terminal can control Messages. Click ALLOW."
echo ""

# Prints SENT on success and nothing on failure, so the shell can tell the
# difference. The old version could not.
RESULT="$(osascript <<APPLESCRIPT
tell application "Messages"
    -- By id first: it is the only handle a nameless group chat has.
    try
        send "$MSG" to chat id "$CHAT"
        return "SENT by id"
    end try
    try
        send "$MSG" to chat "$CHAT"
        return "SENT by chat name"
    end try
    repeat with c in chats
        set theName to ""
        try
            set theName to name of c as string
        end try
        if theName is "$CHAT" then
            send "$MSG" to c
            return "SENT by matching name"
        end if
    end repeat
    return "NO MATCH"
end tell
APPLESCRIPT
)"
rc=$?

echo ""
if [ "$rc" -ne 0 ]; then
  echo "  osascript exited $rc -- it did not send."
  echo ""
  echo "  If you saw no permission dialog, open:"
  echo "    System Settings > Privacy & Security > Automation"
  echo "  find Terminal, and switch Messages ON."
  echo ""
  exit "$rc"
fi

case "$RESULT" in
  SENT*)
    echo "  $RESULT"
    echo ""
    echo "  CHECK MESSAGES: did the text actually arrive in that chat?"
    echo "  Even a successful send is worth one look before this machine is"
    echo "  trusted with a route."
    echo ""
    ;;
  *)
    echo "  NOTHING WAS SENT — no chat matched \"$CHAT\"."
    echo ""
    echo "  This is the failure that used to report success. Run this script"
    echo "  with no arguments to see the exact names Messages has, and use"
    echo "  one of those."
    echo ""
    exit 2
    ;;
esac
