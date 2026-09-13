#!/bin/bash
# Birthday Reminders — text the Admin Staff chat the day before a rep's birthday.
#
# RUNS ON LUCY 1, and only there: the "Admin Staff" iMessage chat resolves on
# Lucy 1 (9 participants, verified 2026-09-13) and NOT on Megan's laptop, which
# is not in it. Anywhere else this exits 1 at group resolution.
#
# Raf's ask (l10-alphalete 2026-09-13): ping the day prior so somebody gets a
# photo and the birthday social post is ready to go out on the day.
#
# Manual dry test (resolves the chat, sends nothing):
#   bash deploy/birthday_reminders.sh
# Real send:
#   bash deploy/birthday_reminders.sh --send
set -u
cd "$(dirname "$0")/.." || exit 1

# Overlap guard: a slow board read shouldn't be fought by a second copy. A dead
# pgrep guard is a classic silent no-run, so match the module, not the word.
if pgrep -f "automations.birthday_reminders.run" > /dev/null 2>&1; then
    echo "[$(date)] birthday-reminders SKIPPED — previous pass still running"
    exit 0
fi

VENV_PY=".venv/bin/python3.14"
[ -x "$VENV_PY" ] || VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

LOG_FILE="$LOG_DIR/birthday-reminders-$(date +%Y-%m-%d).log"
echo "[$(date)] birthday-reminders starting: $*" > "$LOG_FILE"

"$VENV_PY" -u -m automations.birthday_reminders.run "$@" >> "$LOG_FILE" 2>&1
# CAPTURED BEFORE ANY $(date): a `$(...)` between the run and `$?` overwrites the
# exit status with the subshell's, so a crashed job logs 0 and reads green.
# [[exit code clobbered by $(date)]]
ST=$?

echo "[$(date)] birthday-reminders finished exit=$ST" >> "$LOG_FILE"

# The card publishes ITSELF from run.py (success on a clean pass, including the
# ordinary "nobody has a birthday tomorrow"; problem when the chat can't be
# reached). Nothing to publish here -- a second publish would double-count the
# daily pill. [[a LaunchAgent report publishes to the Hub]]

# No-show marker: the agent FIRED. A missing marker past the slot means launchd
# never ran it, which is the only silent-no-fire signal there is.
[ "$ST" = "0" ] && touch "output/logs/.birthday-reminders-ran-$(date +%Y-%m-%d)" 2>/dev/null || true

# PROPAGATE the real status. Several wrappers here end `exit 0` so launchd never
# marks them failed; that is wrong for this one. A run that couldn't reach the
# chat is a real miss somebody has to see, and `exit 0` is exactly how a failure
# reads green. [[exit-0 alone is not green]]
exit "$ST"
