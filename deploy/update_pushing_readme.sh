#!/bin/zsh
# Daily 7 PM README updater (launchd: com.alphalete.pushing-readme).
# Runs a headless Claude with the brief in update_pushing_readme_prompt.md.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd /Users/carloshidalgo/recruiting-report || exit 1
LOG=/Users/carloshidalgo/recruiting-report/output/readme-update-$(date +%F).log
claude -p "$(cat deploy/update_pushing_readme_prompt.md)" \
  --permission-mode acceptEdits \
  --allowedTools "Bash(git *) Bash(cd *) Read Edit Write Bash(*venv/bin/python*)" \
  >> "$LOG" 2>&1
# GRAB $? FIRST — the $(date) in the same echo runs before $? is expanded,
# and command substitution RESETS it, so this used to log the status of
# `date` (always 0) instead of the job's. A crashed run read as "exit 0".
# Cost three silent hours on gap_alerts, 2026-09-07.
rc=$?
echo "[$(date)] readme updater exit (exit $rc)" >> "$LOG"
exit $rc
