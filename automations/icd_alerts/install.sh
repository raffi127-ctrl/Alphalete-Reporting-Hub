#!/bin/bash
# Install Lucy Reports on this computer. ONE LINE, pasted into Terminal:
#
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/install.sh | bash -s -- KASH-XXXXX-XXXXX-XXXXX
#
# WHY THIS REPLACED THE ZIP. Two offices were enrolled by zip on 2026-09-12 and
# nearly every round of back-and-forth traced to the FILE, not the software:
#
#   * macOS blocks an unsigned .command, and the right-click bypass is gone on
#     current macOS -- it reads as "nothing happened"
#   * the unzipped folder looked like "a bunch of files" with no obvious
#     installer among them
#   * one office ran ANOTHER office's package, because the instruction carried
#     the wrong name
#   * their download was twenty minutes older than the instructions being
#     given, so the paths did not match
#
# Nothing is downloaded here, so nothing is quarantined; there is no folder to
# find; the office is in the line itself; and the code is always current, so
# instructions cannot go stale. The update command has exactly this shape and
# worked first time, which is what settled it.
#
# THE KEY IS THE IDENTITY. It starts with the office name, so one argument
# carries both who this is and the authority to hand numbers in.
set -u

RAW="https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main"
BUST="$(date +%s)"
KEY="${1:-}"

if [ -z "$KEY" ]; then
  echo "This command needs your office's code on the end, like:"
  echo "  ... | bash -s -- KASH-XXXXX-XXXXX-XXXXX"
  echo ""
  echo "Ask the reporting team for yours."
  exit 1
fi

# KASH-8ABCD-... -> kash
OFFICE="$(printf '%s' "$KEY" | cut -d- -f1 | tr '[:upper:]' '[:lower:]')"

echo ""
echo "Setting up Lucy Reports for: $OFFICE"
echo ""

PY=""
for c in python3 /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "This Mac needs Apple's free developer tools first."
  echo "A box will appear now — click Install, wait for it to finish, then"
  echo "paste this same command again."
  xcode-select --install 2>/dev/null
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK" || exit 1

echo "Fetching the program..."
LIST="$(curl -fsSL "$RAW/automations/icd_alerts/agent_files.txt?t=$BUST")" || {
  echo "Could not reach the update server. Nothing was changed."; exit 1; }

fetch() {
  mkdir -p "$(dirname "$2")"
  curl -fsSL "$RAW/$1?t=$BUST" -o "$2" || { echo "  could not fetch $1"; return 1; }
}

fail=0
while IFS= read -r f; do
  case "$f" in ''|'#'*) continue ;; esac
  fetch "$f" "$f" || fail=1
done <<< "$LIST"
fetch "automations/icd_alerts/dist/setup.py" "setup.py" || fail=1
fetch "automations/icd_alerts/dist/ask.py" "ask.py" || fail=1
fetch "automations/icd_alerts/offices_public.json" "offices.json" || fail=1
[ "$fail" -eq 0 ] || { echo ""; echo "Some files did not download. Nothing was changed — try again on a normal wifi network."; exit 1; }

# install.json is what the old zip carried. Built here from the PUBLIC office
# config plus the key from the command line, so the only secret ever in play
# is the one the reporting team sent to this one office.
"$PY" - "$OFFICE" "$KEY" <<'PYEOF' || exit 1
import json, sys
office_key, relay_key = sys.argv[1], sys.argv[2]
pub = json.load(open("offices.json"))
rec = (pub.get("offices") or {}).get(office_key)
if not rec:
    print("\nThat code is for an office I do not recognise (%r)." % office_key)
    print("Check it with the reporting team — nothing has been changed.")
    raise SystemExit(1)
rec = dict(rec)
rec["relay_url"] = pub["relay_url"]
rec["relay_key"] = relay_key
json.dump(rec, open("install.json", "w"), indent=2)
print("This is %s's copy (%s)." % (rec["owner"], office_key))
PYEOF

echo ""
exec "$PY" setup.py
