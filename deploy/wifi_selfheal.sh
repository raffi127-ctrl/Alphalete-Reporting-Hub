#!/bin/bash
# Wi-Fi self-heal — every Lucy, every 2 min (com.alphalete.wifi-selfheal).
#
# WHY (2026-10-20, Megan: "this can't keep happening"). Lucy 1 stayed JOINED to
# the office Wi-Fi with full bars but "not on internet" from 17:56 to ~20:12 —
# no sales texts, a dead queue, gap alerts down — while Lucy 2/3/4 on the same
# Wi-Fi were fine. Nothing remote could reach it; the fix was a person at the
# box turning Wi-Fi off and on to get a fresh address. This does that by itself.
#
# Every run: one internet check. 3 failed checks in a row (~6 min) -> turn the
# Wi-Fi off, wait, turn it on, and try again; keeps doing that every 3 more
# failures until it is back. Silent when the internet is fine. No root needed
# (networksetup works for an admin user). Never touches a wired connection.
#
# Manual:  bash deploy/wifi_selfheal.sh --check   (report only, changes nothing)

set -u
cd "$(dirname "$0")/.." || exit 1
mkdir -p output/logs
STATE="output/.wifi_selfheal_fails"
LOG="output/logs/wifi-selfheal.log"
CHECK_ONLY=0; [ "${1:-}" = "--check" ] && CHECK_ONLY=1

online() {
  # Two independent hosts, so one site being down is never read as "offline".
  for url in https://www.google.com/generate_204 https://www.apple.com/library/test/success.html; do
    code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)
    case "$code" in 2*|3*) return 0 ;; esac
  done
  return 1
}

stamp() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

WIFI=$(networksetup -listallhardwareports 2>/dev/null \
       | awk '/Hardware Port: Wi-Fi/{getline; print $2; exit}')
fails=$(cat "$STATE" 2>/dev/null || echo 0)
case "$fails" in ''|*[!0-9]*) fails=0 ;; esac

if online; then
  [ "$fails" -ge 3 ] && stamp "internet back after $fails failed checks"
  echo 0 > "$STATE"
  [ "$CHECK_ONLY" = 1 ] && echo "online (wifi device: ${WIFI:-none})"
  exit 0
fi

fails=$((fails + 1))
echo "$fails" > "$STATE"
stamp "no internet (check $fails in a row; wifi device ${WIFI:-none}, ip $(ipconfig getifaddr "${WIFI:-en1}" 2>/dev/null || echo none))"
[ "$CHECK_ONLY" = 1 ] && { echo "OFFLINE — check $fails in a row (would toggle at every 3rd)"; exit 0; }

if [ -z "$WIFI" ]; then
  stamp "no Wi-Fi device on this machine — nothing to toggle"
  exit 0
fi
# Only act when Wi-Fi is this box's active link: a wired box with a dead
# internet gains nothing from losing its Wi-Fi too.
DEF_IF=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
if [ -n "$DEF_IF" ] && [ "$DEF_IF" != "$WIFI" ]; then
  stamp "default route is $DEF_IF, not $WIFI — leaving Wi-Fi alone"
  exit 0
fi

if [ $((fails % 3)) -eq 0 ]; then
  stamp "turning Wi-Fi ($WIFI) off and on"
  networksetup -setairportpower "$WIFI" off >> "$LOG" 2>&1
  sleep 5
  networksetup -setairportpower "$WIFI" on >> "$LOG" 2>&1
  sleep 25
  if online; then
    stamp "internet back after the Wi-Fi restart (ip $(ipconfig getifaddr "$WIFI" 2>/dev/null))"
    echo 0 > "$STATE"
  else
    stamp "still offline after the Wi-Fi restart — will try again in ~6 min"
  fi
fi
exit 0
