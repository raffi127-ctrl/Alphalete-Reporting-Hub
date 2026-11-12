#!/bin/bash
# Laptop Set Up - Owner & Admin (Mac) — a full walkthrough.
#
# Double-click this file on the NEW laptop. Pop-up windows walk the person
# through EVERY line of the "Laptop Set Up - Owner & Admin" checklist, one
# step at a time ("Step 3 of 15"), with the exact clicks. The script does the
# parts a computer can do by itself (installs, Dock, mouse, screen saver,
# printers) and opens the right page for the parts only a person can do
# (making accounts, signing in, phone steps).
#
# Every pop-up has "Done" and "Skip for now". Done steps are remembered, so
# running it again picks up where they left off — handy when a step has to
# wait (e.g. Megan registering the owner for Lucy's background checks).
#
#   Test without changing anything:   bash Laptop-Setup-Mac.command --dry-run
#   Start over from step 1:            bash Laptop-Setup-Mac.command --reset
#
# Needs nothing installed first. A brand-new Mac has no Python/Homebrew, so
# this is plain bash + built-in Mac tools only (bash 3.2 safe).

DRY_RUN=0
[ "$1" = "--dry-run" ] && DRY_RUN=1
PROGRESS="$HOME/.laptop-setup-progress"
[ "$1" = "--reset" ] && rm -f "$PROGRESS"

# ---- Work sites (checklist: "Gmail, Google Calendar, Google Drive &") ----
# name|url — each gets its own "log in here" step.
WORK_SITES=(
  "OwnerVille|https://ownerville.com/"
  "ApplicantStream|https://applicantstream.com/"
  "Apex|https://apex.herbjoyent.com/"
  "Sterling|https://www.sterlingcheck.com/login/"
  "BlueInk|https://app.blueink.com/"
)

# ---- Official download links (vendor's own servers only) ----
ARCH="$(uname -m)"   # arm64 = Apple chip, x86_64 = Intel
CHROME_URL="https://dl.google.com/chrome/mac/universal/stable/GGRO/googlechrome.dmg"
SLACK_URL="https://slack.com/api/desktop.latestRelease?arch=universal&variant=dmg&redirect=true"
if [ "$ARCH" = "arm64" ]; then
  ZOOM_URL="https://zoom.us/client/latest/Zoom.pkg?archType=arm64"
else
  ZOOM_URL="https://zoom.us/client/latest/Zoom.pkg"
fi
EXCEL_URL="https://go.microsoft.com/fwlink/?linkid=525135"   # Excel only, ~1 GB
MAGNET_APPSTORE="macappstore://apps.apple.com/app/id441258766"

# ---- Gmail forwarding ----
LUCY_BG_INBOX="lucysterlingreports@gmail.com"   # read by icd_onboarding/bg_status.py
STERLING="noreply@us.fadv.co"

DONE=(); YOURS=(); FAILED=()

# ================================================================= helpers
bold()  { printf "\n\033[1m%s\033[0m\n" "$1"; }
# GO=back is set when someone presses Back; everything after that in the
# current step stands down (no pop-ups, no actions, no report lines) and the
# loop at the bottom re-opens the previous step with FORCE=1, so its windows
# show again even if they were done.
GO=next; FORCE=0; STEP_I=0
ok()    { [ "$GO" = back ] && return 0; printf "  \033[32m✅ %s\033[0m\n" "$1"; DONE+=("$1"); }
fail()  { [ "$GO" = back ] && return 0; printf "  \033[31m❌ %s\033[0m\n" "$1"; FAILED+=("$1"); }
todo()  { [ "$GO" = back ] && return 0; printf "  ☐ %s\n" "$1"; YOURS+=("$1"); }
run()   { [ "$GO" = back ] && return 0; if [ $DRY_RUN = 1 ]; then echo "  (dry run) would run: $*"; else "$@"; fi; }

# Sections number themselves: TOTAL is however many `section` lines this file has.
TOTAL="$(grep -c '^section "' "$0")"
N=0; TITLE=""
section() { N=$((STEP_I+1)); TITLE="$1"; bold "Step $N of $TOTAL — $TITLE"; }

# Progress memory: a step marked Done is never asked again.
is_done()   { [ $DRY_RUN = 0 ] && grep -qxF "$1" "$PROGRESS" 2>/dev/null; }
mark_done() { [ $DRY_RUN = 0 ] && echo "$1" >> "$PROGRESS"; }

# --- pop-ups (args go in as argv, so quotes/apostrophes in text are safe) ---
_dialog() {   # title message buttons-csv default  -> prints the button clicked
  osascript - "$1" "$2" "$3" "$4" <<'APPLESCRIPT' 2>/dev/null
on run argv
  set AppleScript's text item delimiters to ","
  set btns to text items of (item 3 of argv)
  try
    set r to display dialog (item 2 of argv) with title (item 1 of argv) buttons btns default button (item 4 of argv) with icon note
    return button returned of r
  on error
    return ""
  end try
end run
APPLESCRIPT
}

say_info() {   # message   (OK; Back from step 2 on)
  [ "$GO" = back ] && return 0
  [ "${QUIET_INFO:-0}" = 1 ] && return 0
  if [ $DRY_RUN = 1 ]; then echo "  (pop-up) $1" | head -3; return; fi
  if [ "$N" -gt 1 ]; then
    [ "$(_dialog "Step $N of $TOTAL — $TITLE" "$1" "Back,OK" "OK")" = "Back" ] && GO=back
  else
    _dialog "Step $N of $TOTAL — $TITLE" "$1" "OK" "OK" >/dev/null
  fi
}

# A step only a person can do. key, then the instructions.
# Done -> remembered; Skip -> listed on the report as still to do.
# LAST_MSG / LAST_SHOWN let a check that fails on a step finished in an
# EARLIER run show that step's instructions first, never a bare "not done"
# (Megan's test 2026-11-11: ApplicantStream said "No ☆" without ever having
# said to click it, because the step was marked done before checks existed).
LAST_MSG=""; LAST_SHOWN=0
human() {
  # 4th arg: the "done" button's words (default "I did it"); launch-team
  # steps say "They confirmed it done" (Megan, 2026-11-11).
  local key="$1" msg="$2" label="${3:-$TITLE}" done="${4:-I did it}"
  [ "$GO" = back ] && return 1
  LAST_MSG="$msg"; LAST_SHOWN=0
  if [ "$FORCE" = 0 ] && is_done "$key"; then ok "$label (done earlier)"; return 0; fi
  LAST_SHOWN=1
  if [ $DRY_RUN = 1 ]; then echo "  (pop-up) $label"; return 0; fi
  local btns="Skip,$done"; [ "$N" -gt 1 ] && btns="Back,Skip,$done"
  local b; b="$(_dialog "Step $N of $TOTAL — $TITLE" "$msg" "$btns" "$done")"
  [ "$b" = "Back" ] && { GO=back; return 1; }
  if [ "$b" = "$done" ]; then is_done "$key" || mark_done "$key"; ok "$label"; return 0; fi
  todo "$label"; return 1
}

ask_yes() {   # question -> 0 = Yes
  [ $DRY_RUN = 1 ] && return 0
  [ "$(_dialog "Step $N of $TOTAL — $TITLE" "$1" "No,Yes" "Yes")" = "Yes" ]
}

ask_text() {   # question default -> prints answer
  if [ $DRY_RUN = 1 ]; then echo "${2:-example}"; return; fi
  osascript - "Step $N of $TOTAL — $TITLE" "$1" "$2" <<'APPLESCRIPT' 2>/dev/null
on run argv
  try
    set r to display dialog (item 2 of argv) with title (item 1 of argv) default answer (item 3 of argv) buttons {"OK"} default button "OK" with icon note
    return text returned of r
  on error
    return ""
  end try
end run
APPLESCRIPT
}

ask_email() {   # question default -> prints a lower-cased email, asks until it looks like one
  local v
  while :; do
    v="$(ask_text "$1" "$2" | tr -d ' ' | tr 'A-Z' 'a-z')"
    case "$v" in *@*.*) echo "$v"; return;; esac
    [ $DRY_RUN = 1 ] && { echo "example@gmail.com"; return; }
    _dialog "Oops" "That's not an email. Try again." "OK" "OK" >/dev/null
  done
}

# Remember answers between runs (so a re-run doesn't ask again).
remember() { [ $DRY_RUN = 0 ] && { grep -v "^$1=" "$PROGRESS" 2>/dev/null > "$PROGRESS.tmp"; echo "$1=$2" >> "$PROGRESS.tmp"; mv "$PROGRESS.tmp" "$PROGRESS"; }; }
recall()   { [ $DRY_RUN = 0 ] && sed -n "s/^$1=//p" "$PROGRESS" 2>/dev/null | tail -1; }

# Every page opens in Chrome's OWN "Reception" profile, never whatever
# profile is already open. Megan's test 2026-11-11: on a Mac whose Chrome was
# already signed in, "open Gmail/Calendar/Drive" landed in HER Drive. A
# separate profile starts empty, so the person always sees a sign-in screen
# and reception's logins/passwords never mix with the owner's own Chrome.
CHROME_PROFILE="Reception"
open_chrome() {   # url...   (falls back to the default browser before Chrome exists)
  if [ -d "/Applications/Google Chrome.app" ]; then
    run open -na "Google Chrome" --args --profile-directory="$CHROME_PROFILE" "$@"
  else
    run open "$@"
  fi
}

# --- check their work -------------------------------------------------------
# After "I did it", Lucy looks for proof on the laptop itself and won't move on
# until it's there or they press Skip (Megan, 2026-11-11: "we should check as
# much as we can ... we want this idiot proof"). Every check reads a file or
# setting the app itself keeps -- no Python (a new Mac has none), no network.
#   Apple account  -> MobileMeAccounts (signed in, and as reception)
#   Chrome         -> the Reception profile's Preferences (signed in + sync on)
#   ☆ bookmarks    -> the profile's Bookmarks file
#   saved passwords-> the profile's "Login Data" databases (site names only;
#                     Lucy never reads a password)
#   Slack          -> Slack's root-state.json lists a workspace
#   Zoom           -> Zoom keeps a per-account folder once someone signs in
#   Excel          -> Office records the email it's activated with
#   Magnet         -> the app is in /Applications
# Not checkable from the laptop: Gmail filters/forwarding, Drive sharing,
# anything on the phone, Slack admin. Those stay "I did it".
CHROME_DIR="$HOME/Library/Application Support/Google/Chrome/$CHROME_PROFILE"
unmark() { [ $DRY_RUN = 0 ] && { grep -vxF "$1" "$PROGRESS" 2>/dev/null > "$PROGRESS.tmp"; mv "$PROGRESS.tmp" "$PROGRESS"; }; }

verify() {   # step-key  "what was checked"  check-function  args...
  local key="$1" what="$2" fn="$3"; shift 3
  [ "$GO" = back ] && return 0
  [ $DRY_RUN = 1 ] && { echo "  (dry run) Lucy would check: $what"; return 0; }
  grep -qxF "$key" "$PROGRESS" 2>/dev/null || return 0   # they skipped: nothing to check
  local problem b
  while :; do
    sleep 3                       # apps save their files a moment after a click
    problem="$("$fn" "$@")"
    if [ -z "$problem" ]; then ok "Lucy checked ✓ $what"; return 0; fi
    if [ "$LAST_SHOWN" = 0 ] && [ -n "$LAST_MSG" ]; then
      # finished in an earlier run but not really done: give the instructions again
      LAST_SHOWN=1
      b="$(_dialog "Step $N of $TOTAL — $TITLE" "$LAST_MSG" "Skip,I did it" "I did it")"
      [ "$b" = "I did it" ] && continue
      unmark "$key"; todo "$what (Lucy checked: not done)"; return 1
    fi
    b="$(_dialog "Step $N of $TOTAL — $TITLE" "Lucy checked. Not done yet:

$problem" "Skip,Check again" "Check again")"
    if [ "$b" != "Check again" ]; then
      unmark "$key"; todo "$what (Lucy checked: not done)"; return 1
    fi
  done
}

# SAVE EACH PASSWORD RIGHT AFTER SIGNING IN (Megan, 2026-11-11: "this should
# also be done pretty early since they would have been saving them as we
# went"). Apps that aren't websites go into Google Passwords by hand, one at a
# time, then Lucy checks it landed.
save_password() {   # step-key  "App name"  website
  local key="$1" name="$2" site="$3"
  open_chrome "https://passwords.google.com/?authuser=$RECEPTION_EMAIL"
  human "$key" "Save your ${name} password.
Google Passwords is open in Chrome.

1. Click “Add”.
2. Website: ${site}
3. Type your ${name} email and password.
4. Click “Save”." "${name} password saved in Google Passwords"
  verify "$key" "${name} password saved" chk_passwords "${name}|${site}"
}

# Each check prints nothing when it's done, or what's wrong + how to fix it.
chk_stars() {   # "Name|text-in-the-address" ...
  local urls e miss=""
  urls="$(grep -o '"url": *"[^"]*"' "$CHROME_DIR/Bookmarks" 2>/dev/null)"
  for e in "$@"; do echo "$urls" | grep -qi "${e#*|}" || miss="$miss${e%%|*}
"; done
  [ -n "$miss" ] && printf "No ☆ on:\n%s\nGo to that tab.\nClick the ☆ at the right end of the web address bar.\nThen click “Done”." "$miss"
}
_saved_sites() {   # the site addresses with a saved login (both of Chrome's lists)
  local t db; t="$(mktemp -d)"
  for db in "Login Data" "Login Data For Account"; do
    [ -f "$CHROME_DIR/$db" ] || continue
    cp "$CHROME_DIR/$db" "$t/db" 2>/dev/null && sqlite3 -readonly "$t/db" "select origin_url from logins;" 2>/dev/null
  done
  rm -rf "$t"
}
chk_passwords() {   # "Name|text-in-the-address" ...
  local sites e miss=""
  sites="$(_saved_sites)"
  for e in "$@"; do echo "$sites" | grep -qi "${e#*|}" || miss="$miss${e%%|*}
"; done
  [ -n "$miss" ] && printf "No saved password for:\n%s\nLog out. Log in again.\nWhen Chrome asks to save the password, click “Save”." "$miss"
}
chk_site() {   # "Name|text-in-the-address"
  local p; p="$(chk_stars "$1")"; [ -n "$p" ] && { echo "$p"; return; }
  chk_passwords "$1"
}
chk_apple() {
  local acct; acct="$(defaults read MobileMeAccounts Accounts 2>/dev/null)"
  if ! echo "$acct" | grep -q "LoggedIn = 1"; then
    printf "No Apple account is signed in.\n\nIn System Settings, click “Sign in” (top left)."
  elif ! echo "$acct" | grep -qi "$RECEPTION_EMAIL"; then
    printf "This Mac is signed in to a different Apple account.\n\nAsk the launch team."
  fi
}
chk_apple_any() {
  defaults read MobileMeAccounts Accounts 2>/dev/null | grep -q "LoggedIn = 1" && return
  printf "No Apple account is signed in.\n\nIn System Settings, click “Sign in” (top left)."
}
chk_chrome() {
  local f="$CHROME_DIR/Preferences"
  if ! grep -o '"account_info":\[[^]]*\]' "$f" 2>/dev/null | grep -qi "\"email\":\"$RECEPTION_EMAIL\""; then
    printf "Chrome isn't signed in as:\n%s\n\n1. Click your picture at the top right of Chrome.\n2. Click “Turn on sync”. Then “Yes, I'm in”." "$RECEPTION_EMAIL"
  elif ! grep -q '"consented_to_sync":true' "$f" 2>/dev/null; then
    printf "Sync is off.\n\n1. Click your picture at the top right of Chrome.\n2. Click “Turn on sync”. Then “Yes, I'm in”."
  fi
}
chk_slack() {
  local f
  for f in "$HOME/Library/Application Support/Slack/storage/root-state.json" \
           "$HOME/Library/Containers/com.tinyspeck.slackmacgap/Data/Library/Application Support/Slack/storage/root-state.json"; do
    grep -Eq '"workspaces":\{"[A-Z0-9]+"' "$f" 2>/dev/null && return
  done
  printf "Slack isn't signed in.\n\nIn Slack, sign in with your own email."
}
chk_zoom() {
  ls -d "$HOME/Library/Application Support/zoom.us/data/"*@xmpp.zoom.us >/dev/null 2>&1 && return
  printf "Zoom isn't signed in.\n\nIn Zoom, click “Sign in”."
}
chk_excel() {
  defaults read com.microsoft.office OfficeActivationEmailAddress 2>/dev/null | grep -q @ && return
  printf "Excel isn't signed in.\n\nIn Excel, click “Sign in”."
}
chk_magnet() {
  [ -d "/Applications/Magnet.app" ] && return
  printf "Magnet isn't on the laptop yet.\n\nIn the App Store, click “Get”.\nWait until it's done."
}

# ------------------------------------------------------------- installers
# DOWNLOADS START THE MOMENT THE WALKTHROUGH OPENS (Megan, 2026-11-11: "the
# goal is to shorten this call"). Excel alone is ~1 GB; fetched while the
# person makes the Gmail + Apple account, it's usually done by step 3. Chrome
# and Slack need no password, so they install by themselves in the
# background too. Zoom + Excel need the laptop password, so step 3 installs
# both behind ONE password box.
CACHE="$HOME/Library/Caches/LaptopSetup"
BG_DONE="$CACHE/downloads.done"

_fetch() {   # name url ext -> $CACHE/name.ext  (resumes a half-finished file)
  local out="$CACHE/$1.$3"
  [ -f "$out" ] && return 0
  curl -fsSL -C - -o "$out.part" "$2" && mv "$out.part" "$out"
}
_dmg_to_apps() {   # name  (copies name.app out of the downloaded dmg)
  local mnt
  mnt="$(hdiutil attach -nobrowse -noverify "$CACHE/$1.dmg" | tail -1 | awk -F'\t' '{print $NF}')"
  [ -d "$mnt/$1.app" ] && cp -R "$mnt/$1.app" /Applications/
  hdiutil detach "$mnt" -quiet 2>/dev/null
}

start_downloads() {
  [ $DRY_RUN = 1 ] && { echo "  (dry run) would start downloading Chrome, Slack, Zoom, Excel in the background"; return; }
  mkdir -p "$CACHE"; rm -f "$BG_DONE"
  (
    [ -d "/Applications/Google Chrome.app" ] || { _fetch "Google Chrome" "$CHROME_URL" dmg && _dmg_to_apps "Google Chrome" && touch "$CACHE/chrome.ready"; } &
    [ -d "/Applications/Slack.app" ]         || { _fetch "Slack" "$SLACK_URL" dmg && _dmg_to_apps "Slack"; } &
    [ -d "/Applications/zoom.us.app" ]       || _fetch "zoom.us" "$ZOOM_URL" pkg &
    [ -d "/Applications/Microsoft Excel.app" ] || _fetch "Microsoft Excel" "$EXCEL_URL" pkg &
    wait
    touch "$BG_DONE"
  ) >>"$CACHE/download.log" 2>&1 &
  BG_PID=$!
}

# Step 1 makes the Gmail INSIDE Chrome, so step 6 finds it already signed in
# (Megan, 2026-11-11). Chrome is small and downloads first; wait for it, but
# never more than 4 minutes -- after that, Google's page opens in Safari.
wait_for_chrome() {
  [ $DRY_RUN = 1 ] && return
  [ -d "/Applications/Google Chrome.app" ] && [ ! -f "$CACHE/Google Chrome.dmg" ] && return
  local i=0
  printf "  Getting Chrome ready"
  while [ ! -f "$CACHE/chrome.ready" ] && [ $i -lt 48 ] && kill -0 "$BG_PID" 2>/dev/null; do
    printf "."; sleep 5; i=$((i+1))
  done
  echo
}

wait_for_file() {   # file-in-cache  message   (max 5 min; nothing to wait for if the app is there)
  [ $DRY_RUN = 1 ] && return
  local app="/Applications/${1%.*}.app" i=0
  [ -d "$app" ] && return
  printf "  %s" "$2"
  while [ ! -f "$CACHE/$1" ] && [ $i -lt 60 ] && kill -0 "$BG_PID" 2>/dev/null; do
    printf "."; sleep 5; i=$((i+1))
  done
  echo
}

wait_for_downloads() {
  [ $DRY_RUN = 1 ] && return
  local shown=0
  while [ ! -f "$BG_DONE" ] && kill -0 "$BG_PID" 2>/dev/null; do
    [ $shown = 0 ] && { printf "  Still downloading"; shown=1; }
    printf "."; sleep 5
  done
  [ $shown = 1 ] && echo " done."
}

install_pkgs() {   # the Zoom + Excel installers (or just the ones named), ONE password box
  [ "$GO" = back ] && return 0
  local cmd="" name list=("$@")
  [ ${#list[@]} -eq 0 ] && list=("zoom.us" "Microsoft Excel")
  for name in "${list[@]}"; do
    if [ -d "/Applications/$name.app" ]; then continue; fi
    if [ $DRY_RUN = 1 ]; then echo "  (dry run) would install $name"; continue; fi
    if [ -f "$CACHE/$name.pkg" ]; then
      cmd="$cmd/usr/sbin/installer -pkg '$CACHE/$name.pkg' -target / ; "
    else
      fail "$name download (check the Wi-Fi, then open the link again)"
    fi
  done
  if [ -n "$cmd" ]; then
    echo "  Installing ${list[*]} (the Mac asks for the laptop password)..."
    osascript -e "do shell script \"$cmd\" with administrator privileges" >/dev/null 2>&1
  fi
}

report_app() {   # name -> ok/fail by what's actually in /Applications
  if [ $DRY_RUN = 1 ] || [ -d "/Applications/$1.app" ]; then ok "$1 installed"; else fail "$1 install"; fi
}

DOCK_CHANGED=0
dock_add() {   # "/Applications/X.app"
  local app="$1" name; name="$(basename "$app" .app)"
  if [ ! -d "$app" ]; then fail "$name on Dock (app not installed)"; return 1; fi
  if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "${app// /%20}/"; then ok "$name already on Dock"; return 0; fi
  run defaults write com.apple.dock persistent-apps -array-add \
    "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$app</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>"
  ok "$name added to Dock"; DOCK_CHANGED=1
}

# ---------------------------------------------------------- Gmail filters
filter_entry() {   # from subject forwardTo   (subject "" = any subject)
  echo " <entry>"
  echo "  <category term='filter'></category>"
  echo "  <title>Mail Filter</title>"
  echo "  <content></content>"
  echo "  <apps:property name='from' value='$1'/>"
  [ -n "$2" ] && echo "  <apps:property name='subject' value='$2'/>"
  echo "  <apps:property name='forwardTo' value='$3'/>"
  echo " </entry>"
}
write_filters() {  # file  entries...(as "from|subject|to")
  local f="$1"; shift
  {
    echo "<?xml version='1.0' encoding='UTF-8'?>"
    echo "<feed xmlns='http://www.w3.org/2005/Atom' xmlns:apps='http://schemas.google.com/apps/2006'>"
    echo " <title>Mail Filters</title>"
    local e a b c; for e in "$@"; do IFS='|' read -r a b c <<< "$e"; filter_entry "$a" "$b" "$c"; done
    echo "</feed>"
  } > "$f"
  if [ $DRY_RUN = 1 ]; then echo "  (dry run) $(basename "$f") would be:"; sed 's/^/    /' "$f"; fi
}

# ===================================================================== RUN
bold "════════════════════════════════════════════"
bold "  Laptop Set Up — Owner & Admin"
[ $DRY_RUN = 1 ] && bold "  DRY RUN — nothing will change, no pop-ups"
bold "════════════════════════════════════════════"

if [ $DRY_RUN = 0 ]; then
  _dialog "Laptop Set Up" "Hi! Let's set up this laptop.

A window will tell you what to do.
Do it. Then click “I did it”.

Before you start:
• Be sure and join our Zoom call on your new laptop that we're setting up
• Have your phone ready
• Be on your new office Wi-Fi

Don't close the black window." "Let's go" "Let's go" >/dev/null
fi
# KEEP GOING OR START OVER (Megan's test 2026-11-11: an old run's remembered
# email made step 2 check sync for an address that was never created). Asked
# only when an earlier run left progress behind.
if [ $DRY_RUN = 0 ] && [ -s "$PROGRESS" ]; then
  b="$(_dialog "Laptop Set Up" "You started this before.

Keep going where you left off, or start over from step 1?" "Start over,Keep going" "Keep going")"
  [ "$b" = "Start over" ] && rm -f "$PROGRESS"
fi
start_downloads

# THEIR NAME, NOT "WHOSE COMPUTER" (Megan, 2026-11-11: "this should just be
# where they type their name. It's a new laptop for them."). It's always the
# person's own new laptop, so the Apple step uses THEIR OWN Apple account.
# The name also tells them their Drive folder: Maud names it after them.
COMPUTER=owner
PERSON_NAME="$(recall PERSON_NAME)"
while [ -z "$PERSON_NAME" ]; do
  if [ $DRY_RUN = 1 ]; then PERSON_NAME="Example Person"; break; fi
  PERSON_NAME="$(osascript - "Laptop Set Up" "Type your first and last name." <<'APPLESCRIPT' 2>/dev/null
on run argv
  try
    set r to display dialog (item 2 of argv) with title (item 1 of argv) default answer "" buttons {"OK"} default button "OK" with icon note
    return text returned of r
  on error
    return ""
  end try
end run
APPLESCRIPT
)"
  PERSON_NAME="$(echo "$PERSON_NAME" | sed 's/^ *//; s/ *$//')"
done
remember PERSON_NAME "$PERSON_NAME"

# ------------------------------------------------------------------------
step_0() {
section "Get on the Zoom call"
# ZOOM COMES FIRST (Megan, 2026-11-11: "this should be with the zoom account
# launch prompt and be their personal email"). The launch team runs the rest
# of the setup on that call, so Zoom is installed before anything else -- it's
# small and downloads first -- and they sign in with their PERSONAL email.
wait_for_file "zoom.us.pkg" "Getting Zoom ready"
install_pkgs "zoom.us"
run open -a zoom.us 2>/dev/null
human zoom "Zoom is open.
(Look behind this box.)

Make your Zoom account:
1. Click “Sign up”.
2. Click “Google”. Pick your personal Gmail.
(Already have a Zoom account? Click “Sign in” instead.)
3. Join our Zoom call." "Zoom account made + on the call"
verify zoom "Zoom signed in" chk_zoom
}

step_1() {
section "Make the reception email"
# <companyname>reception@gmail.com — the first step on every laptop (Megan, 2026-11-11).
RECEPTION_EMAIL="$(recall RECEPTION_EMAIL)"
if [ "$FORCE" = 0 ] && [ -n "$RECEPTION_EMAIL" ] && is_done reception_email; then
  ok "Reception email: $RECEPTION_EMAIL (done earlier)"
else
  # They type the FULL company name (Megan, 2026-11-11), but the email uses
  # just the brand: "Alphalete Marketing" -> alphaletereception@gmail.com
  # (ours). Generic business words are dropped; if that leaves nothing, the
  # whole name is used.
  COMPANY=""
  while [ -z "$COMPANY" ]; do
    COMPANY_NAME="$(ask_text "Type your full company name.

Example: Alphalete Marketing" "")"
    [ $DRY_RUN = 1 ] && COMPANY_NAME="Example Marketing"
    SHORT_NAME="$(echo "$COMPANY_NAME" | tr -s ' ' '\n' \
      | grep -viE '^(marketing|llc|l\.l\.c\.?|inc\.?|co\.?|corp\.?|company|group|enterprises?|solutions|the|and|&)$' \
      | tr '\n' ' ' | sed 's/ *$//')"
    [ -z "$SHORT_NAME" ] && SHORT_NAME="$COMPANY_NAME"
    COMPANY="$(echo "$SHORT_NAME" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9')"
  done
  RECEPTION_EMAIL="${COMPANY}reception@gmail.com"
  wait_for_chrome
  open_chrome "https://accounts.google.com/signup"
  if human reception_email "Google is open.

Make this Gmail:
${RECEPTION_EMAIL}

Name: ${SHORT_NAME} Reception" "Reception email created"; then
    # Google sometimes says the name is taken and makes them pick another.
    # Every later step uses this address, so ask which one they ended up with.
    if [ $DRY_RUN = 0 ] && [ "$(_dialog "Step $N of $TOTAL — $TITLE" "Is this your new email?

${RECEPTION_EMAIL}

(Google sometimes makes you pick a different one.)" "No, I got a different one,Yes, that's it" "Yes, that's it")" != "Yes, that's it" ]; then
      RECEPTION_EMAIL="$(ask_email "Type your new email:" "")"
    fi
  fi
  remember RECEPTION_EMAIL "$RECEPTION_EMAIL"
fi
# Sync goes on NOW, not at "Sign in to Google": every password from here on
# is saved as they go, and Lucy's password check reads Chrome's synced list.
human chrome_sync "Turn on Chrome sync.
(It saves your passwords to Google.)

1. Click your picture at the top right of Chrome.
2. Click “Turn on sync”. Then “Yes, I'm in”." "Chrome sync on"
verify chrome_sync "Chrome signed in as reception, sync on" chk_chrome
# No Zoom password to save: they make Zoom with "Sign up -> Google", so it
# logs in through their personal Gmail and has no password of its own.
# (Every other login is saved -- Megan 2026-11-11: "It can all be saved".)

# ------------------------------------------------------------------------
}
step_2() {
section "Apple account (iCloud)"
run open "x-apple.systempreferences:com.apple.systempreferences.AppleIDSettings"
if [ "$COMPUTER" = owner ]; then
  human icloud "System Settings is open.
(The gray ⚙️ window. Look behind this box.)

1. Click “Sign in”.
2. Sign in with YOUR OWN Apple account." "Owner's own iCloud signed in"
  verify icloud "Apple account signed in" chk_apple_any
  save_password pw_apple "Apple account" "apple.com"
else
  human icloud "System Settings is open.
(The gray ⚙️ window. Look behind this box.)

1. Click “Sign in”.
2. Click “Create Apple Account”.
3. Use this email:
${RECEPTION_EMAIL}

Already signed in to a different Apple account? Ask the launch team." "iCloud for reception email created"
  verify icloud "Apple account signed in as reception" chk_apple
  save_password pw_apple "Apple account" "apple.com"
fi

# ------------------------------------------------------------------------
}
step_3() {
section "Get the apps"
# Downloads started at the welcome screen; usually finished by now.
say_info "Lucy is putting the apps on this laptop:
Chrome, Slack and Excel.

When it asks for the laptop password, type it.

Click OK."
wait_for_downloads
install_pkgs
for app in "Google Chrome" "Slack" "zoom.us" "Microsoft Excel"; do report_app "$app"; done
[ $DRY_RUN = 0 ] && rm -rf "$CACHE"

# ------------------------------------------------------------------------
}
step_4() {
section "Get Magnet"
if [ -d "/Applications/Magnet.app" ]; then
  ok "Magnet already installed"
else
  run open "$MAGNET_APPSTORE"
  human magnet "The App Store is open.

1. Click “Get”.
2. Wait until it's done." "Magnet installed"
  verify magnet "Magnet installed" chk_magnet
fi
if [ $DRY_RUN = 1 ]; then
  echo "  (dry run) would set Magnet to open at startup"
elif [ -d "/Applications/Magnet.app" ]; then
  if osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null | grep -q Magnet; then
    ok "Magnet already opens at startup"
  elif osascript -e 'tell application "System Events" to make login item at end with properties {path:"/Applications/Magnet.app", hidden:false}' >/dev/null 2>&1; then
    ok "Magnet opens every time the laptop turns on"
  else
    fail "Magnet at startup (System Settings → General → Login Items → + → Magnet)"
  fi
else
  todo "Magnet: install it, then run this again to make it open at startup"
fi

# ------------------------------------------------------------------------
}
step_5() {
section "Mouse and screen"
for app in "/Applications/Google Chrome.app" "/Applications/Slack.app" \
           "/Applications/zoom.us.app" "/Applications/Microsoft Excel.app"; do
  dock_add "$app"
done
[ "$DOCK_CHANGED" = 1 ] && run killall Dock
run defaults write -g com.apple.mouse.scaling -float 3    && ok "Mouse speed set to fastest"
run defaults write -g com.apple.trackpad.scaling -float 3 && ok "Trackpad speed set to fastest"
run defaults write com.apple.AppleMultitouchMouse MouseButtonMode -string TwoButton
run defaults write com.apple.driver.AppleBluetoothMultitouch.mouse MouseButtonMode -string TwoButton \
  && ok "Right side of mouse = right-click"
run defaults -currentHost write com.apple.screensaver idleTime -int 0 && ok "Screen saver set to Never"
say_info "The laptop did these by itself:

✅ Apps on the bottom bar
✅ Fast mouse
✅ Right-click on the mouse
✅ Screen saver off"

# ------------------------------------------------------------------------
}
step_6() {
section "Bookmark Gmail, Calendar, Drive"
open_chrome "https://mail.google.com/" "https://calendar.google.com/" "https://drive.google.com/"
human chrome_google "Gmail, Calendar and Drive are open in tabs at the top of Chrome.

Click each tab.
Click the ☆ at the right end of the web address bar.
Then click “Done”." "Chrome: Gmail, Calendar, Drive bookmarked"
verify chrome_google "Chrome signed in as reception, sync on" chk_chrome
verify chrome_google "☆ on Gmail, Calendar, Drive" chk_stars "Gmail|mail.google.com" "Calendar|calendar.google.com" "Drive|drive.google.com"

# ------------------------------------------------------------------------
}
step_7() {
section "Sign in to work websites"
for entry in "${WORK_SITES[@]}"; do
  IFS='|' read -r sname surl <<< "$entry"
  open_chrome "$surl"
  extra=""
  # Maud makes their BlueInk login and the launch team gives it to them on the
  # call (2026-11-11); then it's a normal log in + save + ☆ like the others.
  [ "$sname" = "BlueInk" ] && extra="
The launch team will give you your BlueInk login."
  human "site_$sname" "${sname} is open.

1. Log in.${extra}
2. Chrome asks to save the password. Click “Save”.
3. Save the page: click the ☆ at the right end of the web address bar. Then click “Done”." "Chrome: logged in to $sname + bookmarked"
  # what to look for in the saved address (Apex lives on herbjoyent.com)
  needle="$(echo "$sname" | tr 'A-Z' 'a-z')"; [ "$sname" = "Apex" ] && needle="herbjoyent"
  verify "site_$sname" "$sname: ☆ + password saved" chk_site "$sname|$needle"
done

# ------------------------------------------------------------------------
}
step_8() {
section "Send login codes to reception"
# Sara+ and Sterling login codes reach reception (Megan, 2026-11-11: "it
# should be sara and sterling codes"), plus OwnerVille's verification code
# because it's on the checklist ("keep it if it's on the list"). Sara+'s sender
# is the one icd_alerts/code_forward.py already filters on (from: only).
# Google won't let a script add a forwarding address to a regular Gmail (that
# API is Workspace-admin only) and a filter can only forward to a CONFIRMED
# address — so the person adds + confirms it, then imports a filter file this
# script writes, with Gmail's own "Import filters" button. No sign-in tokens.
OWNER_EMAIL="$(recall OWNER_EMAIL)"
if [ -z "$OWNER_EMAIL" ]; then
  OWNER_EMAIL="$(ask_email "Next: your Sara+, Sterling and OwnerVille login codes will go to reception.

What email address is your Sara+ account set up with?" "")"
  remember OWNER_EMAIL "$OWNER_EMAIL"
fi
OWNER_GMAIL="https://mail.google.com/mail/?authuser=$OWNER_EMAIL"
if [ $DRY_RUN = 1 ]; then OUT="$(mktemp -d)"; else OUT="$HOME/Desktop"; fi
F_RECEPTION="$OUT/Gmail-Filters-1-Reception.xml"
F_LUCY="$OUT/Gmail-Filters-2-Lucy-Background-Checks.xml"
write_filters "$F_RECEPTION" \
  "security.info@saraplus.com||$RECEPTION_EMAIL" \
  "$STERLING|Authentication Request|$RECEPTION_EMAIL" \
  "noreply@ownerville.com|Your Account Verification Code|$RECEPTION_EMAIL"
write_filters "$F_LUCY" "$STERLING||$LUCY_BG_INBOX"

if is_done filters_reception; then
  ok "Owner's Gmail forwards login codes to reception (done earlier)"
else
  open_chrome "$OWNER_GMAIL#settings/fwdandpop"
  human fwd_reception_added "Gmail is open for:
${OWNER_EMAIL}
(the email your Sara+ account uses)
Sign in to it if it asks.

1. Click “Add a forwarding address”.
2. Type:
${RECEPTION_EMAIL}
3. Click Next. Then Proceed. Then OK.

Don't change anything else." "Owner's Gmail: reception added as a forwarding address"
  human fwd_reception_confirmed "Wait for the launch team to approve your forwarding." "Launch team approved the reception forwarding" "They confirmed it done"
  if is_done fwd_reception_confirmed || [ $DRY_RUN = 1 ]; then
    open_chrome "$OWNER_GMAIL#settings/filters"
    human filters_reception "Gmail is open.

1. Scroll to the bottom. Click “Import filters”.
2. Click “Choose File”. Pick this from the Desktop:
Gmail-Filters-1-Reception
3. Click “Open file”. Then “Create filters”." "Owner's Gmail forwards Sara+, Sterling and OwnerVille login codes to reception"
  fi
fi

# ------------------------------------------------------------------------
}
step_9() {
section "Send background checks to Lucy"
# Everything from Sterling also goes to Lucy's inbox, so each new start's BG
# Status fills itself in on the ICD board. Both forwards are approved by the
# LAUNCH TEAM on the Zoom call (Megan, 2026-11-11) — the person just waits.
# For Lucy's, that means registering the owner on the "Sterling Results Mail"
# tab (REGISTER_CMD, printed in Terminal + the report) so Lucy 1 confirms it;
# a new laptop isn't enrolled and can't put itself there.
REGISTER_CMD="lucy rerun icd_code_mail_register -- --service sterling_results --register <office-key> $OWNER_EMAIL"
if is_done filters_lucy; then
  ok "Owner's Gmail forwards background checks to Lucy (done earlier)"
else
  echo "  For the launch team: $REGISTER_CMD"
  open_chrome "$OWNER_GMAIL#settings/fwdandpop"
  human fwd_lucy_added "Gmail is open for:
${OWNER_EMAIL}
(the email your Sara+ account uses)
Sign in to it if it asks.

1. Click “Add a forwarding address”.
2. Type:
${LUCY_BG_INBOX}
3. Click Next. Then Proceed. Then OK.

Don't change anything else." "Owner's Gmail: Lucy added as a forwarding address"
  human fwd_lucy_approved "Wait for the launch team to approve your forwarding." "Launch team approved the Lucy forwarding" "They confirmed it done"
  if is_done fwd_lucy_approved || [ $DRY_RUN = 1 ]; then
    open_chrome "$OWNER_GMAIL#settings/filters"
    human filters_lucy "Gmail is open.

1. Scroll to the bottom. Click “Import filters”.
2. Click “Choose File”. Pick this from the Desktop:
Gmail-Filters-2-Lucy-Background-Checks
3. Click “Open file”. Then “Create filters”." "Owner's Gmail forwards Sterling background checks to Lucy"
  fi
fi
[ $DRY_RUN = 1 ] && rm -rf "$OUT"

# ------------------------------------------------------------------------
}
step_10() {
section "Share Google Drive"
# Maud makes a Drive folder named after the owner (first + last name) and
# shares it with reception as Editor (2026-11-11). Same folder for every office.
human drive_shared "Wait for the launch team to share your Google Drive folder with:
${RECEPTION_EMAIL}

(It's named: ${PERSON_NAME})" "Drive folder shared with reception (launch team)" "They confirmed it done"

# ------------------------------------------------------------------------
}
step_11() {
section "Contacts"
# "Google Contacts (Laptop & Phone)" = reception's Google contacts show up in
# the Mac's Contacts app, the same way the phone step does on the phone.
# Opening the Google Contacts website alone did nothing on a new account.
run open "x-apple.systempreferences:com.apple.Internet-Accounts-Settings.extension"
human contacts_laptop "System Settings is open on Internet Accounts.
(The gray ⚙️ window. Look behind this box.)

1. Click “Add Account”. Click “Google”.
2. Sign in with:
${RECEPTION_EMAIL}
3. Turn on “Contacts”. Click “Done”." "Google Contacts on the laptop"
human contacts_phone "Grab the phone.

1. Open Settings.
2. Tap Apps. Then Contacts. Then Contacts Accounts.
3. Tap Add Account. Tap Google.
4. Sign in with:
${RECEPTION_EMAIL}
5. Turn on Contacts." "Contacts on the phone"

# ------------------------------------------------------------------------
}
step_12() {
section "Calendar on the phone"
human phone_calendar "Grab the phone.

1. Open the App Store.
2. Find “Google Calendar”. Tap Get.
3. Sign in with:
${RECEPTION_EMAIL}" "Google Calendar app on the phone"

# ------------------------------------------------------------------------
}
step_13() {
section "Slack"
run open -a Slack 2>/dev/null
# Slack is the PERSON's own login, not reception's (Megan 2026-11-11: "idk why
# an ICD would sign in using their company reception email"; the checklist
# says "Login/Create account - made admin AO").
human slack_signin "Slack is open.
(Look behind this box.)

Sign in with YOUR OWN email.
No Slack account yet? Click “Create an account”." "Slack: signed in"
verify slack_signin "Slack signed in" chk_slack
save_password pw_slack "Slack" "slack.com"
# Slack's own alert choice lives in their Slack account (online), so the
# laptop can't set it -- and Slack already alerts on DMs + mentions. What
# "Notification On" needs is the Mac's permission, which only a person can
# grant; Lucy opens the exact switch (tested 2026-11-11).
run open "x-apple.systempreferences:com.apple.Notifications-Settings.extension?id=com.tinyspeck.slackmacgap"
human slack_alerts_laptop "Slack alerts are open in System Settings.
(The gray ⚙️ window. Look behind this box.)

Turn on “Allow notifications”." "Slack alerts on the laptop"
human slack_phone "Grab your phone.

1. Open Slack. (Don't have it? Get it from the App Store and sign in with your own email.)
2. Open the phone's Settings. Tap Notifications. Tap Slack.
3. Turn on “Allow Notifications”." "Slack alerts on the phone"
human slack_admin "Ask the launch team to make you a Slack admin.

They will do it on the Zoom call." "Slack: made admin (AO)" "They confirmed it done"

# ------------------------------------------------------------------------
}
step_15() {
section "Excel"
run open -a "Microsoft Excel" 2>/dev/null
# Every office's Excel signs in as Alphalete's reception (the checklist's
# "Login alphaletereception"). There's no password: Microsoft emails a code to
# that inbox, which the launch team reads out on the call (Maud, 2026-11-11).
human excel "Excel is open.

1. Click “Sign in”.
2. Type: alphaletereception@gmail.com
3. Microsoft sends a code. The launch team will tell you the code.
4. Type the code." "Excel: signed in"
verify excel "Excel signed in" chk_excel

# ------------------------------------------------------------------------
}
step_17() {
section "Printers"
if [ "$FORCE" = 0 ] && is_done printers; then ok "Printers (done earlier)"; return 0; fi
# ONLY THIS NETWORK'S PRINTERS (Megan, 2026-11-11: "this should only show those
# on the current network as they will be at their office and then have the
# option of adding more"). Office printers announce themselves on the Wi-Fi
# (AirPrint), so no addresses are needed; each new one is added with the Mac's
# built-in driver. One already added is matched by its ID, so re-running never
# makes the "Printer_2, Printer_3, Printer_4" pile-up seen on Megan's Mac.
# Printers added somewhere else (another office) are never listed here.
PRINT_SETTINGS="x-apple.systempreferences:com.apple.Print-Scanner-Settings.extension"
FOUND="$(ippfind -T 5 _ipp._tcp --exec echo '{service_name}|{}|{txt_UUID}' \; 2>/dev/null | sort -u -t'|' -k1,1)"
HAVE="$(lpstat -v 2>/dev/null)"
QUEUES_BEFORE="$(lpstat -v 2>/dev/null | sed -n 's/^device for \([^:]*\):.*/\1/p')"
NEW=(); ON_NET=""
while IFS= read -r line; do
  [ -z "$line" ] && continue
  IFS='|' read -r pname puri puuid <<< "$line"
  if [ -n "$puuid" ] && echo "$HAVE" | grep -qi "$puuid"; then
    ON_NET="${ON_NET}✅ ${pname}
"
  else
    NEW+=("$line")
  fi
done <<< "$FOUND"

# 1) new printers on this Wi-Fi: add them (one Yes)
if [ ${#NEW[@]} -gt 0 ]; then
  NEW_LIST="$(for l in "${NEW[@]}"; do echo "🖨  ${l%%|*}"; done)"
  if ask_yes "Printers on this Wi-Fi:
${ON_NET}${NEW_LIST}

Add the 🖨 ones?"; then
    for l in "${NEW[@]}"; do
      IFS='|' read -r pname puri puuid <<< "$l"
      queue="$(echo "$pname" | tr -c 'A-Za-z0-9\n' '_' | sed 's/__*/_/g; s/_$//')"
      if run lpadmin -p "$queue" -E -v "$puri" -m everywhere -D "$pname"; then
        ok "Printer added: $pname"; ON_NET="${ON_NET}✅ ${pname}
"
      else
        fail "Printer $pname (add it in System Settings → Printers & Scanners)"
      fi
    done
  else
    todo "Printers on this Wi-Fi not added"
  fi
fi

# 2) what's connected on this Wi-Fi, plus "add another" for anything not found
if [ $DRY_RUN = 1 ]; then echo "  (pop-up) printers on this Wi-Fi + Add another printer"; return 0; fi
[ "$GO" = back ] && return 0
while :; do
  if [ -n "$ON_NET" ]; then
    MSG="Connected printers on this Wi-Fi:
${ON_NET}
Need another printer? Click “Add another printer”."
  else
    MSG="No printers found on this Wi-Fi.

1. Make sure you're on the office Wi-Fi.
2. Turn on the printer.
3. Click “Add another printer”."
  fi
  b="$(_dialog "Step $N of $TOTAL — $TITLE" "$MSG" "Back,Add another printer,Done" "Done")"
  case "$b" in
    Back) GO=back; return 0;;
    "Add another printer")
      open "$PRINT_SETTINGS"
      _dialog "Step $N of $TOTAL — $TITLE" "System Settings is open on Printers.
(The gray ⚙️ window. Look behind this box.)

1. Click “Add Printer, Scanner or Fax…”.
2. Click the printer. Click “Add”." "I did it" "I did it" >/dev/null
      # list whatever they just added, by its own name
      for q in $(lpstat -v 2>/dev/null | sed -n 's/^device for \([^:]*\):.*/\1/p'); do
        echo "$QUEUES_BEFORE" | grep -qxF "$q" && continue
        QUEUES_BEFORE="$QUEUES_BEFORE
$q"
        pname="$(lpstat -l -p "$q" 2>/dev/null | sed -n 's/^[[:space:]]*Description: //p' | head -1)"
        ok "Printer added: ${pname:-$q}"; ON_NET="${ON_NET}✅ ${pname:-$q}
"
      done
      ;;
    *)
      if [ -n "$ON_NET" ]; then is_done printers || mark_done printers; ok "Printers connected: $(echo "$ON_NET" | grep -c ✅)"; else todo "Printers: none connected"; fi
      return 0;;
  esac
done
}

# ---------------------------------------------------------- run the steps
# One function per step, so Back can re-open the previous one.
STEPS=($(declare -F | awk '{print $3}' | grep -E '^step_[0-9]+$' | sort -t_ -k2 -n))
run_all() {
  local i=0
  while [ $i -lt ${#STEPS[@]} ]; do
    STEP_I=$i; GO=next
    "${STEPS[$i]}"
    if [ "$GO" = back ] && [ $i -gt 0 ]; then i=$((i-1)); FORCE=1; else i=$((i+1)); FORCE=0; fi
  done
  GO=next
}

# LEFTOVERS POP UP, NOT JUST THE REPORT (Megan, 2026-11-11: "this should pop up
# the remaining boxes not just show in the terminal what's not done"). After a
# pass, anything skipped or failed is offered again as its own window; a second
# pass shows ONLY those (finished steps skip by themselves, info boxes stay quiet).
QUIET_INFO=0
while :; do
  run_all
  LEFT=$(( ${#YOURS[@]} + ${#FAILED[@]} ))
  [ $DRY_RUN = 1 ] || [ $LEFT -eq 0 ] && break
  LIST="$( { printf '%s\n' "${YOURS[@]}"; printf '%s\n' "${FAILED[@]}"; } | grep -v '^$' \
          | sed 's/ (Lucy checked: not done)//' | awk '!seen[$0]++' | head -8 | sed 's/^/• /')"
  b="$(_dialog "Laptop Set Up" "$LEFT step(s) aren't done yet:

$LIST

Finish them now?" "Later,Finish them now" "Finish them now")"
  [ "$b" = "Finish them now" ] || break
  DONE=(); YOURS=(); FAILED=(); QUIET_INFO=1
done

# ----------------------------------------------------------------- report
REPORT="$HOME/Desktop/Laptop-Setup-Report.txt"
[ $DRY_RUN = 1 ] && REPORT="$(mktemp)"
{
  echo "Laptop Set Up — $(scutil --get ComputerName 2>/dev/null) — $(date '+%Y-%m-%d %H:%M')"
  echo "For: $PERSON_NAME    Reception email: $RECEPTION_EMAIL    Sara+ email: $OWNER_EMAIL"
  echo "Launch team — Lucy background-check forward: $REGISTER_CMD"
  echo; echo "DONE:";                           for s in "${DONE[@]}";   do echo "  ✅ $s"; done | awk '!seen[$0]++'
  echo; echo "COULD NOT DO (fix by hand):";     for s in "${FAILED[@]}"; do echo "  ❌ $s"; done
  echo; echo "STILL TO DO (run this file again):"; for s in "${YOURS[@]}";  do echo "  ☐ $s"; done
} > "$REPORT"

bold "════════════════════════════════════════════"
cat "$REPORT"
if [ $DRY_RUN = 1 ]; then
  rm -f "$REPORT"
  bold "  Dry run finished — nothing changed."
  exit 0
fi

LEFT=$(( ${#YOURS[@]} + ${#FAILED[@]} ))
if [ $LEFT -eq 0 ]; then
  END_MSG="🎉 All done!

Last thing: restart the laptop."
else
  END_MSG="Almost done!

$LEFT step(s) left.
Open this file again to finish them."
fi
_dialog "Laptop Set Up" "$END_MSG" "OK" "OK" >/dev/null
open "$REPORT"
