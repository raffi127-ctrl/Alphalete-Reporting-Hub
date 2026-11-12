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
ok()    { printf "  \033[32m✅ %s\033[0m\n" "$1"; DONE+=("$1"); }
fail()  { printf "  \033[31m❌ %s\033[0m\n" "$1"; FAILED+=("$1"); }
todo()  { printf "  ☐ %s\n" "$1"; YOURS+=("$1"); }
run()   { if [ $DRY_RUN = 1 ]; then echo "  (dry run) would run: $*"; else "$@"; fi; }

# Sections number themselves: TOTAL is however many `section` lines this file has.
TOTAL="$(grep -c '^section "' "$0")"
N=0; TITLE=""
section() { N=$((N+1)); TITLE="$1"; bold "Step $N of $TOTAL — $TITLE"; }

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

say_info() {   # message   (one OK button)
  if [ $DRY_RUN = 1 ]; then echo "  (pop-up) $1" | head -3; return; fi
  _dialog "Step $N of $TOTAL — $TITLE" "$1" "OK" "OK" >/dev/null
}

# A step only a person can do. key, then the instructions.
# Done -> remembered; Skip -> listed on the report as still to do.
human() {
  local key="$1" msg="$2" label="${3:-$TITLE}"
  if is_done "$key"; then ok "$label (done earlier)"; return 0; fi
  if [ $DRY_RUN = 1 ]; then echo "  (pop-up) $label"; return 0; fi
  local b; b="$(_dialog "Step $N of $TOTAL — $TITLE" "$msg" "Skip,I did it" "I did it")"
  if [ "$b" = "I did it" ]; then mark_done "$key"; ok "$label"; return 0; fi
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

wait_for_downloads() {
  [ $DRY_RUN = 1 ] && return
  local shown=0
  while [ ! -f "$BG_DONE" ] && kill -0 "$BG_PID" 2>/dev/null; do
    [ $shown = 0 ] && { printf "  Still downloading"; shown=1; }
    printf "."; sleep 5
  done
  [ $shown = 1 ] && echo " done."
}

install_pkgs() {   # the Zoom + Excel installers, ONE password box for both
  local cmd="" name
  for name in "zoom.us" "Microsoft Excel"; do
    if [ -d "/Applications/$name.app" ]; then continue; fi
    if [ $DRY_RUN = 1 ]; then echo "  (dry run) would install $name"; continue; fi
    if [ -f "$CACHE/$name.pkg" ]; then
      cmd="$cmd/usr/sbin/installer -pkg '$CACHE/$name.pkg' -target / ; "
    else
      fail "$name download (check the Wi-Fi, then open the link again)"
    fi
  done
  if [ -n "$cmd" ]; then
    echo "  Installing Zoom + Excel (the Mac asks for the laptop password once)..."
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
start_downloads

# ------------------------------------------------------------------------
section "Make the reception email"
# <companyname>reception@gmail.com — the first step on every laptop (Megan, 2026-11-11).
RECEPTION_EMAIL="$(recall RECEPTION_EMAIL)"
if [ -n "$RECEPTION_EMAIL" ] && is_done reception_email; then
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

# ------------------------------------------------------------------------
section "Make an Apple account"
run open "x-apple.systempreferences:com.apple.systempreferences.AppleIDSettings"
human icloud "System Settings is open.
(The gray ⚙️ window. Look behind this box.)

1. Click “Sign in”.
2. Click “Create Apple Account”.
3. Use this email:
${RECEPTION_EMAIL}

Already signed in to a different Apple account? Ask the launch team." "iCloud for reception email created"

# ------------------------------------------------------------------------
section "Get the apps"
# Downloads started at the welcome screen; usually finished by now.
say_info "Lucy is putting 4 apps on this laptop:
Chrome, Slack, Zoom and Excel.

When it asks for the laptop password, type it.

Click OK."
wait_for_downloads
install_pkgs
for app in "Google Chrome" "Slack" "zoom.us" "Microsoft Excel"; do report_app "$app"; done
[ $DRY_RUN = 0 ] && rm -rf "$CACHE"

# ------------------------------------------------------------------------
section "Get Magnet"
if [ -d "/Applications/Magnet.app" ]; then
  ok "Magnet already installed"
else
  run open "$MAGNET_APPSTORE"
  human magnet "The App Store is open.

1. Click “Get”.
2. Wait until it's done." "Magnet installed"
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
section "Sign in to Google"
open_chrome "https://mail.google.com/" "https://calendar.google.com/" "https://drive.google.com/"
human chrome_google "Chrome is open.

1. Click your picture at the top right of Chrome.
2. Click “Turn on sync”. Then “Yes, I'm in”.
(Asked to sign in? Use ${RECEPTION_EMAIL}.)
3. Save each page (Gmail, Calendar, Drive):
click the ☆ at the right end of the web address bar. Then click “Done”." "Chrome: Gmail, Calendar, Drive signed in + bookmarked"

# ------------------------------------------------------------------------
section "Sign in to work websites"
for entry in "${WORK_SITES[@]}"; do
  IFS='|' read -r sname surl <<< "$entry"
  open_chrome "$surl"
  extra=""
  [ "$sname" = "BlueInk" ] && extra="
Ask the owner for the password."
  human "site_$sname" "${sname} is open.

1. Log in.${extra}
2. Chrome asks to save the password. Click “Save”.
3. Save the page: click the ☆ at the right end of the web address bar. Then click “Done”." "Chrome: logged in to $sname + bookmarked"
done

# ------------------------------------------------------------------------
section "Send codes to reception"
# The checklist's filters: Sterling + OwnerVille login codes reach reception.
# Google won't let a script add a forwarding address to a regular Gmail (that
# API is Workspace-admin only) and a filter can only forward to a CONFIRMED
# address — so the person adds + confirms it, then imports a filter file this
# script writes, with Gmail's own "Import filters" button. No sign-in tokens.
OWNER_EMAIL="$(recall OWNER_EMAIL)"
if [ -z "$OWNER_EMAIL" ]; then
  OWNER_EMAIL="$(ask_email "Type the OWNER's email:" "")"
  remember OWNER_EMAIL "$OWNER_EMAIL"
fi
OWNER_GMAIL="https://mail.google.com/mail/?authuser=$OWNER_EMAIL"
if [ $DRY_RUN = 1 ]; then OUT="$(mktemp -d)"; else OUT="$HOME/Desktop"; fi
F_RECEPTION="$OUT/Gmail-Filters-1-Reception.xml"
F_LUCY="$OUT/Gmail-Filters-2-Lucy-Background-Checks.xml"
write_filters "$F_RECEPTION" \
  "$STERLING|Authentication Request|$RECEPTION_EMAIL" \
  "noreply@ownerville.com|Your Account Verification Code|$RECEPTION_EMAIL"
write_filters "$F_LUCY" "$STERLING||$LUCY_BG_INBOX"

if is_done filters_reception; then
  ok "Owner's Gmail forwards login codes to reception (done earlier)"
else
  open_chrome "$OWNER_GMAIL#settings/fwdandpop"
  human fwd_reception_added "The owner's Gmail is open.
(Sign in as the owner if it asks.)

1. Click “Add a forwarding address”.
2. Type:
${RECEPTION_EMAIL}
3. Click Next. Then Proceed. Then OK.

Don't change anything else." "Owner's Gmail: reception added as a forwarding address"
  human fwd_reception_confirmed "Wait for the launch team to approve your forwarding." "Launch team approved the reception forwarding"
  if is_done fwd_reception_confirmed || [ $DRY_RUN = 1 ]; then
    open_chrome "$OWNER_GMAIL#settings/filters"
    human filters_reception "Gmail is open.

1. Scroll to the bottom. Click “Import filters”.
2. Click “Choose File”. Pick this from the Desktop:
Gmail-Filters-1-Reception
3. Click “Open file”. Then “Create filters”." "Owner's Gmail forwards Sterling + OwnerVille login codes to reception"
  fi
fi

# ------------------------------------------------------------------------
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
  human fwd_lucy_added "The owner's Gmail is open.
(Sign in as the owner if it asks.)

1. Click “Add a forwarding address”.
2. Type:
${LUCY_BG_INBOX}
3. Click Next. Then Proceed. Then OK.

Don't change anything else." "Owner's Gmail: Lucy added as a forwarding address"
  human fwd_lucy_approved "Wait for the launch team to approve your forwarding." "Launch team approved the Lucy forwarding"
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
section "Share Google Drive"
open_chrome "https://drive.google.com/drive/u/0/my-drive?authuser=$OWNER_EMAIL"
human drive_shared "The owner's Google Drive is open.

For each folder reception needs:
1. Right-click it. Click “Share”.
2. Type:
${RECEPTION_EMAIL}
3. Click “Send”." "Google Drive docs shared with reception"

# ------------------------------------------------------------------------
section "Contacts"
open_chrome "https://contacts.google.com/?authuser=$RECEPTION_EMAIL"
human contacts_laptop "Google Contacts is open.

Check the contacts are there." "Contacts on the laptop"
human contacts_phone "Grab the phone.

1. Open Settings.
2. Tap Apps. Then Contacts. Then Contacts Accounts.
3. Tap Add Account. Tap Google.
4. Sign in with:
${RECEPTION_EMAIL}
5. Turn on Contacts." "Contacts on the phone"

# ------------------------------------------------------------------------
section "Calendar on the phone"
human phone_calendar "Grab the phone.

1. Open the App Store.
2. Find “Google Calendar”. Tap Get.
3. Sign in with:
${RECEPTION_EMAIL}" "Google Calendar app on the phone"

# ------------------------------------------------------------------------
section "Slack"
run open -a Slack 2>/dev/null
human slack_signin "Slack is open.

Sign in with:
${RECEPTION_EMAIL}" "Slack: signed in"
human slack_alerts_laptop "Turn on Slack alerts.

1. In Slack, click your picture (top right).
2. Click Preferences. Then Notifications.
3. Pick “All new messages”.

If the laptop asks, click Allow." "Slack alerts on the laptop"
human slack_phone "Grab the phone.

1. Get Slack from the App Store.
2. Sign in with:
${RECEPTION_EMAIL}
3. Tap Allow for alerts." "Slack on the phone"
human slack_admin "Ask the launch team to make you a Slack admin.

They will do it on the Zoom call." "Slack: made admin (AO)"

# ------------------------------------------------------------------------
section "Zoom"
run open -a zoom.us 2>/dev/null
human zoom "Zoom is open.

Sign in with:
${RECEPTION_EMAIL}

No account? Click “Sign up”." "Zoom: signed in"

# ------------------------------------------------------------------------
section "Excel"
run open -a "Microsoft Excel" 2>/dev/null
human excel "Excel is open.

1. Click “Sign in”.
2. Use the reception login.
(Alphalete: alphaletereception)" "Excel: signed in"

# ------------------------------------------------------------------------
section "Save the other passwords"
# The website logins are saved by Chrome as they log in (step 7). These ones
# aren't websites, so they go into Google Passwords by hand. Signed in to
# Chrome as reception, so they all live in the reception Google account.
open_chrome "https://passwords.google.com/?authuser=$RECEPTION_EMAIL"
human save_passwords "Google Passwords is open.

Save each of these:
• Apple account → website: apple.com
• Slack → website: slack.com
• Zoom → website: zoom.us
• Excel → website: microsoft.com

For each one:
1. Click “Add”.
2. Type the website, username and password.
3. Click “Save”." "Apple, Slack, Zoom and Excel passwords saved in Google Passwords"

# ------------------------------------------------------------------------
section "Printers"
# Office printers announce themselves on the Wi-Fi (AirPrint), so no
# addresses are needed. Each is added with the Mac's built-in driver. One
# already added is skipped by its ID, so re-running never makes the
# "Printer_2, Printer_3, Printer_4" pile-up seen on Megan's Mac.
FOUND="$(ippfind -T 5 _ipp._tcp --exec echo '{service_name}|{}|{txt_UUID}' \; 2>/dev/null | sort -u -t'|' -k1,1)"
HAVE="$(lpstat -v 2>/dev/null)"
HAVE_NAMES="$(lpstat -l -p 2>/dev/null | sed -n 's/^[[:space:]]*Description: //p')"
if [ -n "$HAVE_NAMES" ]; then
  echo "  This laptop is already connected to:"; echo "$HAVE_NAMES" | sed 's/^/    ✅ /'
else
  echo "  This laptop isn't connected to any printer yet."
fi
NEW=()
while IFS= read -r line; do
  [ -z "$line" ] && continue
  IFS='|' read -r pname puri puuid <<< "$line"
  if [ -n "$puuid" ] && echo "$HAVE" | grep -qi "$puuid"; then continue; fi
  NEW+=("$line")
done <<< "$FOUND"
CONNECTED_MSG=""
[ -n "$HAVE_NAMES" ] && CONNECTED_MSG="Already connected:
$(echo "$HAVE_NAMES" | sed 's/^/✅ /')

"
if [ ${#NEW[@]} -gt 0 ]; then
  NEW_LIST="$(for l in "${NEW[@]}"; do echo "🖨  ${l%%|*}"; done)"
  if ask_yes "${CONNECTED_MSG}New printers:
${NEW_LIST}

Add them?"; then
    for l in "${NEW[@]}"; do
      IFS='|' read -r pname puri puuid <<< "$l"
      queue="$(echo "$pname" | tr -c 'A-Za-z0-9\n' '_' | sed 's/__*/_/g; s/_$//')"
      if run lpadmin -p "$queue" -E -v "$puri" -m everywhere -D "$pname"; then ok "Printer added: $pname"
      else fail "Printer $pname (add it in System Settings → Printers & Scanners → +)"; fi
    done
  else
    todo "Printers: add them in System Settings → Printers & Scanners → +"
  fi
elif [ -n "$HAVE_NAMES" ]; then
  ok "Already connected to $(echo "$HAVE_NAMES" | wc -l | tr -d ' ') printer(s)"
  say_info "${CONNECTED_MSG}All set!"
else
  fail "No printers found on this Wi-Fi"
  say_info "No printers found.

1. Join the office Wi-Fi.
2. Turn on the printer.
3. Open this file again."
fi

# ----------------------------------------------------------------- report
REPORT="$HOME/Desktop/Laptop-Setup-Report.txt"
[ $DRY_RUN = 1 ] && REPORT="$(mktemp)"
{
  echo "Laptop Set Up — $(scutil --get ComputerName 2>/dev/null) — $(date '+%Y-%m-%d %H:%M')"
  echo "Reception email: $RECEPTION_EMAIL    Owner: $OWNER_EMAIL"
  echo "Launch team — Lucy background-check forward: $REGISTER_CMD"
  echo; echo "DONE:";                           for s in "${DONE[@]}";   do echo "  ✅ $s"; done
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
