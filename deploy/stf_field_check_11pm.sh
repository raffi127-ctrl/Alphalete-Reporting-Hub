#!/bin/bash
# 11:00pm CST — STF Field Check, on Lucy 1 (the mini) via launchd
# (com.alphalete.stf-field-check-11pm).
#
# For the CURRENT day: reads the Sales Board WE tab, finds the reps marked STF
# (Straight To Field), pulls that same day's ownerville Time Tracker (p=510,
# Raf's master view — no impersonation), and overwrites STF with X for any rep
# who worked < 3:00 (last knock − first knock) or never showed (no knocks). Keeps
# Raf's "reps-scheduled-in-the-field" count honest before the 4am board post.
#
# 11pm (Megan 2026-07-17): late enough that reps are out of the field and the
# day's knocks are final, but before the morning post. The harvested Daily Rep
# Breakdown can't be used — it fills the next morning, so it has no same-day
# knocks; this scrapes Time Tracker live off the mini's warm ownerville session.
#
# Manual test without writing:  bash deploy/stf_field_check_11pm.sh --dry-run
# (--dry-run is appended and WINS over the default --write below.)
#
# CADENCE / TIME KNOB: edit StartCalendarInterval in the plist, not this wrapper.
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

LOG_FILE="$LOG_DIR/stf-field-check-11pm-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] STF Field Check nightly run starting (extra args: ${*:-none})" > "$LOG_FILE"

# The live path drives ownerville through patchright (imported lazily in run.py),
# so a stray human Chrome collides the same way it does for the Tableau reports.
# 11pm is outside the 4am chrome_guard window — guard here. Same gap that killed
# the Monday headcount job on 2026-07-20.
"$VENV_PY" -u -m automations.day_orchestrator.chrome_guard --close >> "$LOG_FILE" 2>&1 || true

# --write by default (flips STF→X on the board). Any extra arg (e.g. --dry-run)
# is appended and wins.
"$VENV_PY" -u -m automations.stf_field_check.run --write "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] STF Field Check run finished exit=$ST" >> "$LOG_FILE"

# Report this standalone run to the Hub so the card's pill reflects a REAL
# success/failure (a launchd report that never publishes leaves the card grey,
# so a clean run looks identical to a silent miss). Skip on --dry-run. Best-effort.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('stf_field_check','STF Field Check','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"STF Field Check failed (exit $ST) — check the log; the ownerville login may have expired\" with title \"STF Field Check\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
