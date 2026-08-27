#!/bin/bash
# Day orchestrator — the readiness-gated daily report scheduler. Runs once each
# morning on the always-on Mac mini via launchd (com.alphalete.day-orchestrator).
# It probes each Tableau source for readiness, runs what's ready, circles back
# every 25 min, emails a 7:30 checkpoint, keeps retrying to a noon backstop, then
# emails a final completion summary. Reconciles by re-reading the sheet.
#
# Requires the ownerville session holder warm (com.alphalete.session-holder) —
# Tableau pulls SSO through ownerville. Fails CLOSED + alerts if it's stale.
#
# Manual test (NO sheet writes, NO real emails — writes .eml + simulates):
#   bash deploy/day_orchestrator.sh --dry-run --simulate --once
# Real dry-run on the mini (runs reports with their own --dry-run; .eml emails):
#   bash deploy/day_orchestrator.sh --dry-run
#
# Extra flags pass straight through to the orchestrator.

set -u
cd "$(dirname "$0")/.." || exit 1

VENV_PY=".venv/bin/python"
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"

# Activate the code-change → Hub-restart git hooks (idempotent). Must run BEFORE
# the pull so the very next pull that lands new code fires post-merge and bounces
# a stale Hub server on this box (Lucy 1 getsource crash, 2026-07-07).
git config core.hooksPath deploy/git-hooks 2>/dev/null || true

# Self-update: fast-forward to latest before the run so config/code changes land
# without a manual pull (the source of all the babysitting on 2026-06-24).
#
# --autostash, NOT a clean-tree gate (Megan 2026-08-20). The old test required
# `git status --porcelain -uno` to be EMPTY, so ANY tracked modification made
# this silently skip — and the runner then ran all day on stale code with no
# signal. Lucy 2 had been stuck 3 commits behind on exactly that: two deploy
# scripts showed as modified with ZERO changed lines, a file-MODE change from a
# chmod during an install. A metadata difference with no content behind it was
# blocking every deploy.
#
# autostash is what `lucy update` already uses successfully: stash, fast-forward,
# restore. Still best-effort — a failure never blocks the run.
if [ -d .git ]; then
  git pull --ff-only --autostash --quiet origin main 2>/dev/null || true
fi

# macOS Sequoia fork-safety + proxy workarounds (mirrors appstream_morning.sh so
# subprocess.Popen / patchright don't crash post-fork on the mini).
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
export NO_PROXY='*'
export _PYTHON_DEFAULT_USE_POSIX_SPAWN=1
export NO_COLOR=1
export PYTHONPATH="$(pwd)"

# PROBE_SHARED_SESSION is DISABLED (2026-08-19). It was correct about the data
# — the A/B/A' proof showed the 3 downloading probes are byte-identical under one
# shared login — but the WIRING was wrong and it broke the 4am batch.
#
# ReadinessCache.probe_pass() wrapped the WHOLE pass, including _run_pass, which
# launches every report as a subprocess. So once any probe opened the shared
# context, the orchestrator process held a lock on
# automations/uploaded/.browser_profile for the rest of the pass, and every
# browser report that wanted that profile blocked until its timeout. That is the
# 2026-08-19 tableau_screenshots incident (04:52 run, 30m timeout on a stuck
# .browser_profile).
#
# This is the SAME collision already documented in captain_pull: a shared context
# holds the profile, so anything else opening a session on it collides. It was
# applied inside that one report and missed at the orchestrator level.
#
# The fix is NOT to re-enable this line. Probes need either their own profile_dir
# (tableau_session(profile_dir=...), the way session_holder keeps
# .browser_profile_holder separate) or a context closed immediately after each
# probe rather than held across the pass.

EXTRA_ARGS="$*"
LOG_FILE="$LOG_DIR/day-orchestrator-$(date +%Y-%m-%d-%H%M%S).log"

echo "[$(date)] day orchestrator starting (args: ${EXTRA_ARGS:-none})" > "$LOG_FILE"

# --- config pre-flight + self-heal -----------------------------------------
# registry.load_config() is the FIRST thing main() does, so an unparseable
# schedule_config.json takes out the entire day: 2026-08-27 the autostash pop
# from a 00:47 `lucy update` left this file unmerged (UU, conflict markers), the
# 04:00 run died at 04:00:05 having run NOTHING, and `lucy rerun` was dead too
# (it loads the same config), so it could not even be recovered remotely.
#
# The file is a COMMITTED artifact — origin/main is always the truth for it and
# no runner is supposed to carry local edits to it. So a corrupt copy is always
# safe to replace from origin, and doing it here turns that outage into a log
# line. Scoped to this ONE path on purpose: not `git checkout .`, which would
# discard real work elsewhere in the tree.
CFG="automations/day_orchestrator/schedule_config.json"
if ! "$VENV_PY" -c "import json,sys; json.load(open(sys.argv[1]))" "$CFG" >/dev/null 2>&1; then
  echo "[$(date)] PRE-FLIGHT: $CFG is NOT valid JSON — self-healing from origin/main" >> "$LOG_FILE"
  git status --short -- "$CFG" >> "$LOG_FILE" 2>&1
  git fetch origin main --quiet >> "$LOG_FILE" 2>&1 || true
  # `checkout <tree-ish> -- <path>` rewrites index AND worktree, which is what
  # clears an unmerged (UU) entry; git_stash cannot touch one and a plain pull
  # refuses while it exists.
  git checkout origin/main -- "$CFG" >> "$LOG_FILE" 2>&1 || true
  if "$VENV_PY" -c "import json,sys; json.load(open(sys.argv[1]))" "$CFG" >/dev/null 2>&1; then
    echo "[$(date)] PRE-FLIGHT: recovered — $CFG parses again, continuing" >> "$LOG_FILE"
    "$VENV_PY" -u -m automations.orchestrator_heartbeat.run --alert-healed \
        >> "$LOG_FILE" 2>&1 || true
  else
    echo "[$(date)] PRE-FLIGHT: STILL broken after restore — aborting before the run" >> "$LOG_FILE"
    # Exit non-zero WITHOUT running: a batch on a config we can't trust is worse
    # than no batch. The 04:20 heartbeat sees the missing day_state and pages.
    echo "[$(date)] day orchestrator finished exit=78" >> "$LOG_FILE"
    osascript -e "display notification \"Orchestrator config unparseable\" with title \"Reports\" sound name \"Sosumi\"" 2>/dev/null || true
    exit 78
  fi
fi
"$VENV_PY" -m automations.day_orchestrator.run $EXTRA_ARGS >> "$LOG_FILE" 2>&1
ST=$?
echo "[$(date)] day orchestrator finished exit=$ST" >> "$LOG_FILE"

if [ "$ST" -ne 0 ]; then
  osascript -e "display notification \"Day orchestrator exited $ST\" with title \"Reports\" sound name \"Sosumi\"" 2>/dev/null || true
fi
exit "$ST"
