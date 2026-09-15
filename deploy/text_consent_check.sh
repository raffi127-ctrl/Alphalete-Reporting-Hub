#!/bin/bash
# Grant this machine permission to send iMessage, from the identity that will
# actually be sending. Run it ON the machine, with somebody at the keyboard.
#
#   bash deploy/text_consent_check.sh "Some Group Chat Name"
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

set -u

CHAT="${1:-}"
if [ -z "$CHAT" ]; then
  echo ""
  echo "Usage: bash deploy/text_consent_check.sh \"Exact Group Chat Name\""
  echo ""
  echo "The name has to match what Messages shows, exactly -- the send"
  echo "resolves it by name and a near-miss finds nothing."
  echo ""
  exit 1
fi

echo ""
echo "Sending one test message to: $CHAT"
echo ""
echo "macOS should ask whether Terminal may control Messages."
echo "Click ALLOW. If no dialog appears and nothing arrives, this machine"
echo "has already refused it once -- see the note at the end."
echo ""

osascript <<APPLESCRIPT
tell application "Messages"
    set targetChat to a reference to text chat id "$CHAT"
    try
        send "Lucy test — this machine can now text this chat. Ignore." to chat "$CHAT"
    on error
        -- Named group chats resolve differently across macOS versions; fall
        -- back to matching on the chat's display name.
        repeat with c in chats
            if name of c is "$CHAT" then
                send "Lucy test — this machine can now text this chat. Ignore." to c
                exit repeat
            end if
        end repeat
    end try
end tell
APPLESCRIPT
rc=$?

echo ""
if [ "$rc" -eq 0 ]; then
  echo "  osascript exited 0."
  echo ""
  echo "  CHECK MESSAGES: did the text actually arrive in that chat?"
  echo "  Exit 0 is not delivery -- a wrong chat name exits 0 and sends"
  echo "  nothing, which is how a route looks healthy and is not."
  echo ""
  echo "  If it arrived, this machine can text. Tell Claude and it will add"
  echo "  the machine to TEXTING_MACHINES."
else
  echo "  osascript exited $rc -- it did not send."
  echo ""
  echo "  If you saw no permission dialog, open:"
  echo "    System Settings > Privacy & Security > Automation"
  echo "  find Terminal, and switch Messages ON."
fi
echo ""
