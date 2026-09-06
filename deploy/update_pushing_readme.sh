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
echo "[$(date)] readme updater exit $?" >> "$LOG"
