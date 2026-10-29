#!/bin/zsh
# Daily README publisher (launchd: com.alphalete.readmes-sync, 7:30am + 8:00pm).
#
# Gathers every operational README on this Mac into ~/alphalete-readmes-hub,
# builds an index README.md, commits, and pushes to the PRIVATE repo
#   https://github.com/Vantura/carlos-readmes
# so every device can read them. Runs after the 7pm README-updater tasks.
#
# Pure copy job — never edits a source file. Sources that go missing are
# skipped (and logged), not treated as errors.
#
#   zsh ~/alphalete-readmes-hub/sync_readmes.sh           # normal run
#   NO_PUSH=1 zsh ~/alphalete-readmes-hub/sync_readmes.sh # build + commit, no push
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
HUB="$HOME/alphalete-readmes-hub"
REMOTE="git@github.com:Vantura/carlos-readmes.git"
BRANCH="main"
LOG="$HOME/Library/Logs/alphalete-readmes-sync.log"
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
echo "[$(date '+%F %T')] sync start"

cd "$HUB" || { echo "no hub dir"; exit 1; }

# Follow whatever is on GitHub (in case another machine pushed), then rebuild.
if [ -z "${NO_PUSH:-}" ] && git fetch -q "$REMOTE" "$BRANCH" 2>/dev/null; then
  git reset -q --hard FETCH_HEAD
fi
# Wipe everything except .git and this script, then re-copy from sources.
find . -mindepth 1 -maxdepth 1 ! -name .git ! -name sync_readmes.sh -exec rm -rf {} +

RR="$HOME/recruiting-report"
AIR="$HOME/Desktop/Desktop - Carlos’s MacBook Air"

# copy <src> <dest-relative-to-hub>  — silent skip if src is missing
copy() {
  local src="$1" dst="$2"
  [ -f "$src" ] || { echo "  skip (missing): $src"; return 0; }
  mkdir -p "$(dirname "$dst")"
  cp -p "$src" "$dst"
}

# 1. The living operational docs (the 7pm Claude tasks rewrite these).
for f in "$HOME"/alphalete-readmes/*.md; do
  copy "$f" "ops/$(basename "$f")"
done

# 2. Alphalete-Reporting-Hub repo docs, from the laptop working tree.
copy "$RR/README.md"                      "recruiting-report/README.md"
copy "$RR/PUSHING-OPERATIONS-README.md"   "recruiting-report/PUSHING-OPERATIONS-README.md"
for f in "$RR"/docs/*.md; do
  copy "$f" "recruiting-report/docs/$(basename "$f")"
done
for d in "$RR"/automations/*/; do
  n="$(basename "$d")"
  [ -f "$d/README.md" ] && copy "$d/README.md" "recruiting-report/automations/$n/README.md"
done
for n in disposition_signup tracker_onboarding icd_signup pay_structure document_builder office_onboarding; do
  copy "$RR/$n/README.md" "recruiting-report/$n/README.md"
done
for d in "$RR"/resources/*/; do
  n="$(basename "$d")"
  for r in "$d"/README.md "$d"/README.txt; do
    [ -f "$r" ] && copy "$r" "recruiting-report/resources/$n/$(basename "$r")"
  done
done

# 3. Standalone projects outside the repo.
copy "$HOME/shikamaru/README.md"                          "other/shikamaru-README.md"
copy "$HOME/hv-commissions/README.txt"                    "other/hv-commissions-README.txt"
copy "$AIR/captainship-sales-boards/README.md"            "other/captainship-sales-boards-README.md"
copy "$AIR/checkin-bot/README.md"                         "other/checkin-bot-README.md"
copy "$HOME/Desktop/Carlos PNL README/README.md"          "other/carlos-pnl-rebuild-README.md"

# 4. Build the index.
/usr/bin/python3 - <<'PY'
import time, pathlib
hub = pathlib.Path.home() / "alphalete-readmes-hub"
sections = [
    ("ops", "Operating docs (living, rewritten nightly at 7pm)", "ops"),
    ("recruiting-report", "Alphalete-Reporting-Hub repo (code + Lucy 2 automations)", "recruiting-report"),
    ("other", "Standalone projects", "other"),
]
def title(p):
    try:
        for line in p.read_text(errors="replace").splitlines()[:15]:
            s = line.strip()
            if s.startswith("#"):
                return s.lstrip("#").strip()
            if s and p.suffix == ".txt":
                return s[:90]
    except Exception:
        pass
    return ""
src_hint = {"ops": "~/alphalete-readmes/", "recruiting-report": "~/recruiting-report/", "other": "see table"}
other_src = {
    "shikamaru-README.md": "~/shikamaru/README.md",
    "hv-commissions-README.txt": "~/hv-commissions/README.txt",
    "captainship-sales-boards-README.md": "~/Desktop/Desktop - Carlos’s MacBook Air/captainship-sales-boards/README.md",
    "checkin-bot-README.md": "~/Desktop/Desktop - Carlos’s MacBook Air/checkin-bot/README.md",
    "carlos-pnl-rebuild-README.md": "~/Desktop/Carlos PNL README/README.md",
}
out = ["# Carlos's READMEs\n",
       "Every operational README from Carlos's MacBook, gathered in one place so any device can read them. "
       "Synced twice a day (7:30am and 8:00pm Central) by `sync_readmes.sh`, after the 7pm README-updater tasks have run.\n",
       f"_Last sync: {time.strftime('%Y-%m-%d %H:%M %Z')}_\n",
       "**Read-only mirror.** Edit the source file on the MacBook (path shown per section), not this repo; "
       "the next sync overwrites everything here.\n"]
total = 0
for key, heading, folder in sections:
    root = hub / folder
    files = sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []
    if not files:
        continue
    out += [f"\n## {heading}\n", f"Source: `{src_hint[key]}`\n", "| File | What it is | Last edited |", "|---|---|---|"]
    for p in files:
        rel = p.relative_to(hub).as_posix()
        mtime = time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
        t = title(p).replace("|", "\\|")
        if key == "other":
            t = (t + " — " if t else "") + "`" + other_src.get(p.name, "") + "`"
        out.append(f"| [{rel.split('/',1)[1]}]({rel}) | {t} | {mtime} |")
        total += 1
out += [f"\n_{total} files._\n", "\n## How this works\n",
        "- `sync_readmes.sh` (in this repo) copies the sources listed above into this folder, rebuilds this index, commits, and pushes.",
        "- It runs from launchd job `com.alphalete.readmes-sync` on the MacBook; log at `~/Library/Logs/alphalete-readmes-sync.log`.",
        "- To add a README: add one `copy` line to the script. To run it now: `zsh ~/alphalete-readmes-hub/sync_readmes.sh`.\n"]
(hub / "README.md").write_text("\n".join(out))
PY

# 5. Commit + push only if something changed.
git add -A
if git diff --cached --quiet; then
  echo "  no changes"
else
  git -c user.name="$(git config user.name || echo 'Carlos Hidalgo')" \
      -c user.email="$(git config user.email || echo carloshidalgo349@gmail.com)" \
      commit -q -m "readmes sync $(date '+%Y-%m-%d %H:%M')" \
                -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
  if [ -n "${NO_PUSH:-}" ]; then
    echo "  committed $(git rev-parse --short HEAD) (NO_PUSH)"
  elif git push -q "$REMOTE" "HEAD:$BRANCH"; then
    echo "  pushed $(git rev-parse --short HEAD)"
  else
    echo "  PUSH FAILED"
    exit 2
  fi
fi
echo "[$(date '+%F %T')] sync done"
