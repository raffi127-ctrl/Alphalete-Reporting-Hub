#!/bin/bash
# Tuesday 10:00am CST — Raf Captainship Bonus, on Lucy 1 (the mini)
# via launchd (com.alphalete.raf-captainship-bonus-tue).
#
# Inserts a fresh leftmost week column on the "Captainship Bonuses" tab of the
# *Alphalete Org/Captainship Reports* sheet, fills each active rep's Total
# Activations for Raf's team (Tableau CaptainsBonus, current cycle), sets the
# team New Internet 60-day Churn % + Activation % (Rolling 4 Weeks), lets the
# Total Sales / Money Made / TOTAL MONEY MADE formulas recompute, re-points the
# performance chart at the Total Sales row, and DMs the PDF to Raf, Dylan + Maud
# on Slack as Lucy (built in a temp file, deleted after — nothing saved to
# Downloads on this unattended runner).
# Idempotent: if this week's column already exists it refreshes in place
# (--force-insert overrides).
#
# Runs off THIS machine's warm Tableau session (patchright), same path the mini's
# other Tableau reports use. The mini holds a seeded + holder-warmed Tableau
# session already; one-time seed if ever needed:
#   python -m automations.shared.tableau_patchright --login.
#
# Tuesday (matching the Carlos twin) so the just-ended week's churn %s have
# settled before we read them; the module defaults to _current_we_sunday (last
# completed week), so Tuesday's run fills the prior Sunday's column.
#
# Manual test without writing:  bash deploy/raf_captainship_bonus_tue.sh --dry-run
# (--dry-run passes through to the module — pulls + shows the plan, writes nothing.)
#
# CADENCE: the plist fires once, Tuesday 10:00am, machine LOCAL time (the mini is
# Central). TIME KNOB: edit StartCalendarInterval in the plist, not this wrapper.
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

LOG_FILE="$LOG_DIR/raf-captainship-bonus-tue-$(date +%Y-%m-%d-%H%M%S).log"
echo "[$(date)] Raf Captainship Bonus weekly run starting (extra args: ${*:-none})" > "$LOG_FILE"

# Close any stray human Chrome before the Tableau pull — this fires outside the
# 4am chrome_guard window, so without it the run dies instantly with "Opening in
# existing browser session". Same gap that killed the Monday headcount job on
# 2026-07-20; the orchestrator and `lucy rerun` already guard, LaunchAgents didn't.
"$VENV_PY" -u -m automations.day_orchestrator.chrome_guard --close >> "$LOG_FILE" 2>&1 || true

# LIVE by default (fills the sheet). Any extra arg (e.g. --dry-run) is appended.
"$VENV_PY" -u -m automations.raf_captainship_bonus.run "$@" >> "$LOG_FILE" 2>&1
ST=$?

echo "[$(date)] Raf Captainship Bonus run finished exit=$ST" >> "$LOG_FILE"

# Report this standalone run to the Hub so the card's pill reflects a REAL
# success/failure (Megan 2026-07-14: the card stayed grey even on a clean run, so
# success looked identical to a silent miss). Skip on --dry-run. Best-effort.
case " $* " in
  *" --dry-run "*) : ;;
  *)
    if [ "$ST" -eq 0 ]; then _PUB=success; else _PUB=failed; fi
    "$VENV_PY" -c "from automations.day_orchestrator import hub_publish; hub_publish.publish_done('raf_captainship_bonus','Raf Captainship Bonus','$_PUB')" >> "$LOG_FILE" 2>&1 || true
    ;;
esac
if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Raf Captainship Bonus failed (exit $ST) — check the log; the Tableau login may have expired or a roster row didn't match\" with title \"Captainship Bonus\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit 0
