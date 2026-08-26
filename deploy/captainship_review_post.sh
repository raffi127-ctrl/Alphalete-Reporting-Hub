#!/bin/bash
# EVERY DAY: put the Captainship Reports' REVIEW LINK in the review channel on a
# CLOCK, on the always-on Mac mini via launchd
# (com.alphalete.captainship-review-post).
#
# WHY THIS LEFT THE ORCHESTRATOR (Eve 2026-08-19). captainship_drafts_review sat
# at order 21 of the day orchestrator, whose pass runs every ready report
# SEQUENTIALLY, so its queue position — not any clock — decided when the link
# went up. Measured on the Hub Activity tab:
#   2026-08-17  captainship chain 07:55-09:30, link 09:30
#   2026-08-18  captainship chain 07:40-09:14, link 09:14
# while the Org Sales Board's review link was already up at 07:03 both days. Eve
# asked for the two to be approved and sent together — "que se envien
# practicamente juntos (aprox 7:15/20am central)".
#
# The build stays on the orchestrator, moved to the FRONT of the Tableau wave
# (captainship_activations 4.961 … captainship_drafts 4.968, right behind the
# board fill), so the twelve previews are on disk by ~06:10-06:30. Only the POST
# runs here, at 07:15 — a clock cannot be starved by the queue in front of it,
# and 4.969 in the queue would have put the link up at 06:30, an hour ahead of
# the board's instead of behind it.
#
#   07:15 (then 07:45 / 08:15 / 09:15 as a safety net). The board's own link is
#   at 07:00, so the approvers get both inside a quarter hour, and
#   com.alphalete.captainship-review polls every 15 min from 07:00, so a
#   checkmark at ~07:20 is twelve sent reports by ~07:35.
#
# BLOCKS (Eve, 2026-08-26). One run of this agent puts up the whole day, but in
# pieces: it opens the 'Captainship Reports' thread and posts one link per BLOCK
# inside it — Fiber 1 (Rafael), Fiber 2 (Wayne, Starr), Fiber 3 (Tony, Chan,
# Sahil), B2B, NDS — printing and uploading each block before starting the next,
# so the first link is up in a fraction of the time twelve reports took to
# print. Each link is approved and sent on its own. THE CLOCK IS UNCHANGED:
# still 07:15, still 07:45 / 08:15 / 09:15 as the safety net.
#
# --ensure-posted, NOT --post. It is idempotent PER BLOCK by design: a block
# already posted for today — approved or not — is skipped, so it returns
# without touching Slack for that one. That is what makes the later slots safe
# (they cannot re-post a link under the approvers) AND what makes them useful: a
# block whose morning chain never produced previews gets them BUILT here and
# posted, which is the same path the 10:00 backstop in
# deploy/captainship_review.sh takes. It alerts to
# the corrections channel itself when the build or the post fails, so this
# wrapper stays thin.
#
# SENDS NOTHING. It posts the links; com.alphalete.captainship-review mails a
# block within 15 min of a checkmark ON THAT BLOCK, and only then.
#
# TIME KNOB: com.alphalete.captainship-review-post.plist (StartCalendarInterval
# Hour/Minute, machine LOCAL time — the mini is Central). A plist edit needs
# `lucy rerun install_captainship_review_post_agent` to take effect.
#
# Manual test without posting:  bash deploy/captainship_review_post.sh --dry
set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/captainship-review-post-$(date +%Y-%m-%d).log"

# --dry = a human testing: report what it WOULD do, touch nothing.
DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

echo "[$(date)] captainship review post starting (dry=$DRY)" >> "$LOG_FILE"

# Overlap guard: the 07:45 slot must not fight a 07:15 run still printing the
# PDF, and it must not fight the orchestrator's own build if that is running
# late — mailing/printing twelve reports takes a while.
if pgrep -f "automations.captainship_drafts" > /dev/null 2>&1; then
    echo "[$(date)] SKIPPED — a captainship run is still going" >> "$LOG_FILE"
    exit 0
fi

if [ "$DRY" = "1" ]; then
    echo "[$(date)] dry run — would run: review_gate --ensure-posted" >> "$LOG_FILE"
    echo "dry run — would post the review link (no-op if today is already up)"
    exit 0
fi

"$VENV_PY" -u -m automations.captainship_drafts.review_gate \
    --ensure-posted >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] review_gate --ensure-posted exit=$ST" >> "$LOG_FILE"

if [ "$ST" -eq 0 ]; then
    # Same Hub row the orchestrator wrote when captainship_drafts_review
    # finished, so the card still reads posted -> awaiting the checkmark ->
    # green when the gate records the approval. This id has no entry in
    # hub_publish's card map, so it IS the card id — keep it spelled with
    # underscores, exactly as the orchestrator published it.
    "$VENV_PY" -u -c "from automations.shared import hub_activity as H; \
H.log_completed('captainship_drafts_review', 'Captainship Reports (in review)', \
user='captainship-review-post')" >> "$LOG_FILE" 2>&1 \
      || echo "[$(date)] (Hub row did not land — pill only)" >> "$LOG_FILE"
    exit 0
fi

# Failed. review_gate --ensure-posted already alerted the corrections channel
# (one deduped incident per day, whatever the slot), so there is nothing to
# shout here — record the exit and let the next slot try. Past 09:15 nothing
# else is coming from this agent, but deploy/captainship_review.sh keeps
# calling --ensure-posted every 15 min from 10:00, which is the real last word.
echo "[$(date)] exit $ST — the gate raised its own alert; next slot retries" \
     >> "$LOG_FILE"
exit 0
