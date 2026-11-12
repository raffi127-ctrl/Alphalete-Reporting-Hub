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

# WHO this laptop is for (Maud, 2026-11-12: "3 different set ups pretty
# much: Owner, Admin, Reception"). Each has its own link (the page passes
# owner|admin|reception); they're the same walkthrough with a few differences,
# each marked "ROLE:" where it happens. Known so far: reception uses the
# reception iCloud, the owner their own. Admin = owner's steps until Maud's
# list of differences says otherwise.
DRY_RUN=0; RESET=0; ROLE=owner
for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1;; --reset) RESET=1;;
    owner|admin|reception) ROLE="$a";;
  esac
done
case "$ROLE" in admin) ROLE_NAME="Admin";; reception) ROLE_NAME="Reception";; *) ROLE_NAME="Owner";; esac
PROGRESS="$HOME/.laptop-setup-progress-$ROLE"
[ $RESET = 1 ] && rm -f "$PROGRESS"

# ---- Work sites (checklist: "Gmail, Google Calendar, Google Drive &") ----
# name|url — each gets its own "log in here" step.
WORK_SITES=(
  "OwnerVille|https://ownerville.com/"
  "ApplicantStream|https://applicantstream.com/"
  "Apex|https://apex.herbjoyent.com/"
  "Sterling|https://auth.sterlingcheck.app/oauth2/login"
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
  # 5th arg "required": no Skip button (the step everything else depends on).
  local key="$1" msg="$2" label="${3:-$TITLE}" done="${4:-I did it}" req="${5:-}"
  [ "$GO" = back ] && return 1
  LAST_MSG="$msg"; LAST_SHOWN=0
  if [ "$FORCE" = 0 ] && is_done "$key"; then ok "$label (done earlier)"; return 0; fi
  LAST_SHOWN=1
  if [ $DRY_RUN = 1 ]; then echo "  (pop-up) $label"; return 0; fi
  local skip="Skip,"; [ "$req" = required ] && skip=""
  local btns="${skip}$done"; [ "$N" -gt 1 ] && btns="Back,${skip}$done"
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
  type use_reception_profile >/dev/null 2>&1 && use_reception_profile >/dev/null
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
# FIND THE PROFILE THAT IS ACTUALLY RECEPTION (Olivia's run, 2026-11-12: Chrome
# was signed in as reception -- in Chrome's own default profile, not ours --
# so every check looked in an empty "Reception" folder and said "not done").
# Whichever profile is signed in as the reception email wins; checks, pins,
# the All in One and newly opened pages all follow it.
use_reception_profile() {
  [ -n "$RECEPTION_EMAIL" ] || return 0
  local base="$HOME/Library/Application Support/Google/Chrome" d
  for d in "$base"/*/; do
    d="${d%/}"
    [ -f "$d/Preferences" ] || continue
    if grep -o '"account_info":\[[^]]*\]' "$d/Preferences" 2>/dev/null | grep -qi "\"email\":\"$RECEPTION_EMAIL\""; then
      if [ "$CHROME_DIR" != "$d" ]; then
        CHROME_DIR="$d"; CHROME_PROFILE="${d##*/}"
        echo "  (Chrome profile signed in as reception: $CHROME_PROFILE)"
      fi
      return 0
    fi
  done
}
unmark() { [ $DRY_RUN = 0 ] && { grep -vxF "$1" "$PROGRESS" 2>/dev/null > "$PROGRESS.tmp"; mv "$PROGRESS.tmp" "$PROGRESS"; }; }

verify() {   # step-key  "what was checked"  check-function  args...
  local key="$1" what="$2" fn="$3"; shift 3
  use_reception_profile
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
save_password() {   # step-key  "App name"  website  [username]  [All-in-One labels]
  local key="$1" name="$2" site="$3" user="${4:-}" labels="${5:-$2}"
  open_chrome "https://passwords.google.com/?authuser=$RECEPTION_EMAIL"
  human "$key" "Save your ${name} password.
Google Passwords is open in Chrome.

1. Click “Add”.
2. Website: ${site}
3. Type your ${name} email and password.
4. Click “Save”." "${name} password saved in Google Passwords"
  verify "$key" "${name} password saved" chk_passwords "${name}|${site}"
  allin_login "allin_$key" "$labels" "$user"
}

# --- PINS: Lucy pins the tab herself, then checks it stuck -----------------
# (Maud 2026-11-12: pin, not bookmark; Megan: "can you just pin it for them?")
# Lucy clicks Chrome's own Tab > Pin Tab on the Reception window. macOS asks
# once to let Terminal click for her (Accessibility); skipped -> they pin by
# hand. The CHECK reads Chrome's own session file for the Reception profile:
# each open tab's address + its pinned flag (Chrome's SNSS format: command 6 =
# a tab's address, 12 = its pinned state, 16 = tab closed). Only the NEWEST
# Session_ file counts -- Chrome keeps old ones beside it (an old file showed a
# pin that was long gone, 2026-11-12). Read with the Mac's built-in perl; if
# perl or the file is missing, the check stands down instead of failing them.
AX_ASKED=0
_pin_reader() {
  local r; r="$(mktemp)"
  cat > "$r" <<'PERL'
use strict; use warnings;
my (%url,%pin,%closed);
my $f = shift; open(my $fh,'<:raw',$f) or exit; local $/; my $d=<$fh>; close $fh;
exit unless substr($d,0,4) eq 'SNSS';
my ($p,$n)=(8,length $d);
while ($p+2 <= $n) {
  my $size=unpack('v',substr($d,$p,2)); $p+=2;
  last if $size==0 || $p+$size>$n;
  my $id=ord(substr($d,$p,1)); my $pl=substr($d,$p+1,$size-1); $p+=$size;
  if ($id==12 && length($pl)>=5) { my ($t,$b)=unpack('l C',$pl); $pin{$t}=$b?1:0; }
  elsif ($id==6 && length($pl)>=16) { my (undef,$t,undef,$ul)=unpack('L l l l',$pl);
    $url{$t}=substr($pl,16,$ul) if $ul>=0 && 16+$ul<=length $pl; }
  elsif ($id==16 && length($pl)>=4) { $closed{unpack('l',$pl)}=1; }
}
for my $t (keys %url) { next if $closed{$t}; print(($pin{$t}//0),"\t",$url{$t},"\n"); }
PERL
  echo "$r"
}
chk_pins() {   # "Name|text-in-the-address" ...
  command -v perl >/dev/null 2>&1 || return 0
  local sess r tabs e miss=""
  sess="$(ls -t "$CHROME_DIR/Sessions/" 2>/dev/null | grep '^Session_' | head -1)"
  [ -n "$sess" ] || return 0
  r="$(_pin_reader)"; tabs="$(perl "$r" "$CHROME_DIR/Sessions/$sess" 2>/dev/null)"; rm -f "$r"
  for e in "$@"; do echo "$tabs" | grep -qiE "^1	.*${e#*|}" || miss="$miss${e%%|*}
"; done
  [ -n "$miss" ] && printf "Not pinned yet:\n%s\nRight-click its tab at the top of Chrome.\nClick “Pin”." "$miss"
}
_reception_urls() {   # every open tab address in the Reception profile (newest session file)
  command -v perl >/dev/null 2>&1 || return 0
  local sess r
  sess="$(ls -t "$CHROME_DIR/Sessions/" 2>/dev/null | grep '^Session_' | head -1)"
  [ -n "$sess" ] || return 0
  r="$(_pin_reader)"; perl "$r" "$CHROME_DIR/Sessions/$sess" 2>/dev/null | cut -f2; rm -f "$r"
}
_auto_pin() {   # text-in-the-address -> pinned | already | notfound | denied
  # Picks the Chrome window that IS the Reception profile: the one whose tabs
  # best match Reception's own session list. AppleScript can't name a window's
  # profile, and "the front window" was wrong in Megan's test (2026-11-12) --
  # it pinned a tab in her own Chrome.
  osascript - "$1" "$(_reception_urls)" <<'APPLESCRIPT' 2>/dev/null
on run argv
  set needle to item 1 of argv
  set blob to item 2 of argv
  set bestW to 0
  set bestScore to -1
  set bestTab to 0
  tell application "Google Chrome"
    repeat with wi from 1 to count of windows
      set w to window wi
      set score to 0
      set hit to 0
      set i to 0
      repeat with t in tabs of w
        set i to i + 1
        set u to URL of t
        if blob is not "" and blob contains u then set score to score + 1
        if hit = 0 and u contains needle then set hit to i
      end repeat
      if hit > 0 and score > bestScore then
        set bestScore to score
        set bestW to wi
        set bestTab to hit
      end if
    end repeat
    if bestW = 0 then return "notfound"
    set w to window bestW
    set active tab index of w to bestTab
    set index of w to 1
    activate
  end tell
  delay 0.7
  try
    tell application "System Events" to tell process "Google Chrome"
      if exists menu item "Unpin Tab" of menu "Tab" of menu bar 1 then return "already"
      click menu item "Pin Tab" of menu "Tab" of menu bar 1
    end tell
    return "pinned"
  on error
    return "denied"
  end try
end run
APPLESCRIPT
}
pin_tabs() {   # step-key  "Name|text-in-the-address" ...
  local key="$1"; shift
  use_reception_profile
  [ "$GO" = back ] && return 0
  [ $DRY_RUN = 1 ] && { echo "  (dry run) Lucy would pin: ${*%%|*}"; return 0; }
  if [ "$FORCE" = 0 ] && is_done "$key"; then ok "Pinned: ${*%%|*} (done earlier)"; return 0; fi
  local e r left="" denied=0 try
  for try in 1 2; do
    left=""; denied=0
    for e in "$@"; do
      r="$(_auto_pin "${e#*|}")"
      case "$r" in pinned|already) ;; denied) denied=1; left="$left${e%%|*}
";; *) left="$left${e%%|*}
";; esac
    done
    [ $denied = 1 ] && [ $AX_ASKED = 0 ] || break
    AX_ASKED=1
    open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    [ "$(_dialog "Step $N of $TOTAL — $TITLE" "Let Lucy pin your tabs for you.

System Settings is open on Accessibility.
(The gray ⚙️ window. Look behind this box.)

Turn on “Terminal”.
(Type your laptop password if it asks.)" "Skip,I turned it on" "I turned it on")" = "I turned it on" ] || break
  done
  if [ -z "$left" ]; then
    mark_done "$key"; ok "Lucy pinned: $(printf '%s, ' "${@%%|*}" | sed 's/, $//')"
  else
    human "$key" "Pin these tabs:
${left}
Right-click its tab at the top of Chrome.
Click “Pin”." "Pinned: $(printf '%s, ' "${@%%|*}" | sed 's/, $//')"
  fi
  verify "$key" "pinned: $(printf '%s, ' "${@%%|*}" | sed 's/, $//')" chk_pins "$@"
}

# --- THE ALL IN ONE "Passwords" TAB ------------------------------------------
# (Maud + Megan, 2026-11-12) Every login goes in the office's "All in One -
# First Last" sheet, tab "Passwords". That tab is BLOCKS, not a table (read off
# the real "All in One - Oren"): a label (A or E), then "UN" and "PW" in the
# column right of it, and the value one column further (C or G). Blocks are
# found by LABEL, never by row number; a missing one (ApplicantStream, BlueInk,
# Slack, Zoom...) is added in the next free spot.
# Lucy types the USERNAME and turns the PW box green; the person types the
# password; Lucy clears the green. She never reads or types a password: only
# columns A/B/E/F (labels + UN/PW keys) are ever read, and the value cells are
# only ever WRITTEN (usernames, or "code sent to email" where there's no pw).
# Access = the RECEPTION account's Google Sheets permission (the sheet is
# shared with reception); the sheet is found from the tab they opened, so no
# Drive-wide access is asked for.
STOKEN=""; SREFRESH=""; SHEET_ID=""; PW_TAB="Passwords"
sheets_auth() {
  [ $DRY_RUN = 1 ] && { echo "  (dry run) Lucy would ask Google for Sheets access (reception)"; return 1; }
  [ -n "$STOKEN" ] && return 0
  _consent_retry "$RECEPTION_EMAIL" "https://www.googleapis.com/auth/spreadsheets" "spreadsheets" \
    "Lucy will fill in your All in One for you." "Google Sheets" || return 1
  STOKEN="$C_TOKEN"; SREFRESH="$C_REFRESH"; S_CID="$C_CID"; S_SEC="$C_SEC"; return 0
}
sheets_done() {
  [ -n "$STOKEN" ] && curl -fsS -d "token=${SREFRESH:-$STOKEN}" https://oauth2.googleapis.com/revoke >/dev/null 2>&1
  STOKEN=""; SREFRESH=""
}
_s_api() {   # METHOD  url-tail  json-body|""  out-file   -> HTTP code (refreshes once on 401)
  local m="$1" u="https://sheets.googleapis.com/v4/spreadsheets/$2" b="$3" o="$4" code try
  for try in 1 2; do
    if [ -n "$b" ]; then
      code="$(curl -sS -w '%{http_code}' -o "$o" -X "$m" -H "Authorization: Bearer $STOKEN" -H "Content-Type: application/json" -d "$b" "$u" 2>/dev/null)"
    else
      code="$(curl -sS -w '%{http_code}' -o "$o" -X "$m" -H "Authorization: Bearer $STOKEN" "$u" 2>/dev/null)"
    fi
    [ "$code" = 401 ] && [ -n "$SREFRESH" ] && [ $try = 1 ] || break
    STOKEN="$(curl -fsS https://oauth2.googleapis.com/token --data-urlencode "client_id=$S_CID" \
      --data-urlencode "client_secret=$S_SEC" --data-urlencode "refresh_token=$SREFRESH" \
      --data-urlencode "grant_type=refresh_token" 2>/dev/null | plutil -extract access_token raw -o - - 2>/dev/null)"
  done
  echo "$code"
}
find_allin_sheet() {   # sets SHEET_ID from the All in One tab open in the Reception Chrome
  local id t
  use_reception_profile
  t="$(mktemp -d)"
  for id in $(_reception_urls | sed -n 's#.*docs\.google\.com/spreadsheets/d/\([A-Za-z0-9_-]*\).*#\1#p' | awk '!s[$0]++'); do
    [ "$(_s_api GET "$id?fields=properties.title" "" "$t/p.json")" = 200 ] || continue
    if _json "$t/p.json" properties.title | grep -qi "all in one"; then SHEET_ID="$id"; break; fi
  done
  rm -rf "$t"; [ -n "$SHEET_ID" ]
}
_col() { printf "\\$(printf '%03o' $((65+$1)))"; }   # 0 -> A
# THE PASSWORDS TAB CAN MOVE AROUND (Megan, 2026-11-12: "we shouldn't hardcode
# it to a certain cell"). Lucy reads the whole tab once and finds every block
# wherever it sits: a cell saying UN (or "UN:") with a label above it; its
# value is the cell to the right; PW is the row below. Only labels, UN/PW
# positions and whether a UN is empty are kept -- password cells are read as
# part of the tab but never kept, shown or written down.
_pw_map() {   # -> "BLOCK<TAB>label<TAB>keycol<TAB>freeUNrow(0=none)" lines + one "SPOT<TAB>keycol<TAB>row"
  local t pl; t="$(mktemp -d)"
  _s_api GET "$SHEET_ID/values/${PW_TAB}%21A1:Z500" "" "$t/all.json" >/dev/null
  cat > "$t/map.pl" <<'PERL'
use strict; use warnings; use JSON::PP;
my $f = shift; open(my $fh,'<',$f) or exit; local $/; my $d = eval { decode_json(<$fh>) } || {}; close $fh;
my @v = @{ $d->{values} || [] };
sub cell { my ($r,$c)=@_; return '' if $r<0 || $c<0 || $r>$#v; my $x=$v[$r][$c]; return defined $x ? $x : ''; }
sub key  { my $s = uc cell(@_); $s =~ s/[\s:]//g; return $s; }
my (%lastrow, $maxkc);
for my $r (0..$#v) { for my $c (0..$#{$v[$r]}) {
  next unless key($r,$c) eq 'UN';
  next if $r>0 && (key($r-1,$c) eq 'UN' || key($r-1,$c) eq 'PW');   # not the first pair
  my $label = '';
  for my $up (1,2) { for my $cc ($c-1,$c,$c+1) { my $x = cell($r-$up,$cc); if ($x ne '') { $label=$x; last } } last if $label ne ''; }
  my ($k,$free,@have) = ($r,0);
  while (key($k,$c) eq 'UN' || key($k,$c) eq 'PW') {
    $free = $k+1 if !$free && key($k,$c) eq 'UN' && cell($k,$c+1) eq '';
    push @have, ($k+1).'='.lc(cell($k,$c+1)) if key($k,$c) eq 'UN' && cell($k,$c+1) ne '';
    $k++;
  }
  $label =~ s/\t/ /g; s/[\t|]/ /g for @have;
  print "BLOCK\t$label\t$c\t$free\t", join('|',@have), "\n";
  $lastrow{$c} = $k if !defined $lastrow{$c} || $k > $lastrow{$c};
  $maxkc = $c if !defined $maxkc || $c > $maxkc;
}}
$maxkc = 5 unless defined $maxkc;
my $end = $lastrow{$maxkc} // 0;
for my $r ($end..$#v) { for my $cc ($maxkc-1..$maxkc+1) { $end = $r+1 if cell($r,$cc) ne '' } }
print "SPOT\t$maxkc\t", $end+2, "\n";   # label row of a new block, 1-based, one blank row after the last
PERL
  perl "$t/map.pl" "$t/all.json"
  rm -rf "$t"
}
_sheet_gid() {
  local t g; t="$(mktemp -d)"
  _s_api GET "$SHEET_ID?fields=sheets.properties" "" "$t/s.json" >/dev/null
  local i=0
  while _json "$t/s.json" sheets.$i.properties.title >/dev/null; do
    [ "$(_json "$t/s.json" sheets.$i.properties.title)" = "$PW_TAB" ] && { g="$(_json "$t/s.json" sheets.$i.properties.sheetId)"; break; }
    i=$((i+1))
  done
  rm -rf "$t"; echo "$g"
}
_paint() {   # row(1-based) col(0-based) green|clear
  local gid rgb; gid="$(_sheet_gid)"; [ -n "$gid" ] || return 1
  [ "$3" = green ] && rgb='"red":0.72,"green":0.94,"blue":0.72' || rgb='"red":1,"green":1,"blue":1'
  _s_api POST "$SHEET_ID:batchUpdate" "{\"requests\":[{\"repeatCell\":{\"range\":{\"sheetId\":$gid,\"startRowIndex\":$(($1-1)),\"endRowIndex\":$1,\"startColumnIndex\":$2,\"endColumnIndex\":$(($2+1))},\"cell\":{\"userEnteredFormat\":{\"backgroundColor\":{$rgb}}},\"fields\":\"userEnteredFormat.backgroundColor\"}}]}" /dev/null >/dev/null
}
_put() {   # A1  value
  local v="${2//\"/\\\"}"
  _s_api PUT "$SHEET_ID/values/${PW_TAB}%21$1?valueInputOption=RAW" "{\"values\":[[\"$v\"]]}" /dev/null >/dev/null
}
_saved_username() {   # text-in-the-address -> the username Chrome saved for that site
  local t db u; t="$(mktemp -d)"
  for db in "Login Data For Account" "Login Data"; do
    [ -f "$CHROME_DIR/$db" ] || continue
    cp "$CHROME_DIR/$db" "$t/db" 2>/dev/null || continue
    u="$(sqlite3 -readonly "$t/db" "select username_value from logins where origin_url like '%$1%' and username_value<>'' order by date_last_used desc limit 1;" 2>/dev/null)"
    [ -n "$u" ] && break
  done
  rm -rf "$t"; echo "$u"
}
allin_login() {   # step-key  "Label|other label|..."  username  [pw-note]
  local key="$1" labels="$2" user="$3" note="$4" name="${2%%|*}"
  use_reception_profile
  [ "$GO" = back ] && return 0
  if [ $DRY_RUN = 1 ]; then
    if [ -n "$note" ]; then echo "  (dry run) All in One: $name -> username + “$note”"; else echo "  (dry run) All in One: $name -> username + green PW box"; fi
    return 0
  fi
  if [ "$FORCE" = 0 ] && is_done "$key"; then ok "All in One: $name (done earlier)"; return 0; fi
  if [ -z "$STOKEN" ] || [ -z "$SHEET_ID" ]; then
    human "$key" "In your All in One “Passwords” tab (pinned in Chrome), fill in:
${name}
UN: ${user:-your username}
PW: ${note:-your password}" "All in One: $name"
    return
  fi
  local map hit kc unrow="" spot row same
  map="$(_pw_map)"
  # ALREADY THERE (Megan, 2026-11-12: "this is already filled but shouldn't it
  # still highlight green?"): the same username is in the block -> green those
  # boxes so they can see it, and don't add a second copy.
  if [ -n "$user" ]; then
    same="$(echo "$map" | awk -F'\t' -v L="$labels" -v U="$(echo "$user" | tr 'A-Z' 'a-z')" 'BEGIN{n=split(tolower(L),a,"|")} $1=="BLOCK"{l=tolower($2); gsub(/^ +| +$/,"",l); for(i=1;i<=n;i++) if(l==a[i]){m=split($5,h,"|"); for(j=1;j<=m;j++){split(h[j],p,"="); if(p[2]==U){print $3"\t"p[1]; exit}}}}')"
    if [ -n "$same" ]; then
      kc="${same%%	*}"; unrow="${same##*	}"
      local sc; sc="$(_col $((kc+1)))"
      _paint "$unrow" $((kc+1)) green; _paint $((unrow+1)) $((kc+1)) green
      human "$key" "Click your All in One tab (pinned in Chrome).

Your ${name} login is already there, in GREEN (${sc}${unrow}, ${sc}$((unrow+1))).
Check it's right." "All in One: $name (already there)"
      _paint "$unrow" $((kc+1)) clear; _paint $((unrow+1)) $((kc+1)) clear
      return
    fi
  fi
  hit="$(echo "$map" | awk -F'\t' -v L="$labels" 'BEGIN{n=split(tolower(L),a,"|")} $1=="BLOCK"{l=tolower($2); gsub(/^ +| +$/,"",l); for(i=1;i<=n;i++) if(l==a[i] && $4>0){print $3"\t"$4; exit}}')"
  if [ -n "$hit" ]; then
    kc="${hit%%	*}"; unrow="${hit##*	}"
  else
    # no block, or every pair in it is already filled -> a new block below the
    # last one in the right-most column of blocks
    spot="$(echo "$map" | awk -F'\t' '$1=="SPOT"{print $2"\t"$3}')"
    kc="${spot%%	*}"; row="${spot##*	}"
    [ -n "$kc" ] || { kc=5; row=1; }
    _put "$(_col $((kc-1)))$row" "$name"; _put "$(_col $kc)$((row+1))" "UN"; _put "$(_col $kc)$((row+2))" "PW"
    unrow=$((row+1))
  fi
  local vcol=$((kc+1)) uncell pwcell
  uncell="$(_col $vcol)$unrow"; pwcell="$(_col $vcol)$((unrow+1))"
  [ -n "$user" ] && _put "$uncell" "$user"
  [ -z "$user" ] && [ -z "$note" ] && _paint "$unrow" $vcol green
  if [ -n "$note" ]; then
    _put "$pwcell" "$note"; mark_done "$key"; ok "All in One: $name filled ($note)"; return
  fi
  _paint $((unrow+1)) $vcol green
  if [ -n "$user" ]; then
    human "$key" "Click your All in One tab (pinned in Chrome).

Lucy typed your ${name} username.
Type your ${name} password in the GREEN box (${pwcell})." "All in One: $name"
  else
    human "$key" "Click your All in One tab (pinned in Chrome).

Type the ${name} username and password in the GREEN boxes (${uncell}, ${pwcell})." "All in One: $name"
    _paint "$unrow" $vcol clear
  fi
  _paint $((unrow+1)) $vcol clear
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
chk_chrome() {   # signed in to Chrome as reception (newer Chrome has no separate sync switch)
  local f="$CHROME_DIR/Preferences"
  grep -o '"account_info":\[[^]]*\]' "$f" 2>/dev/null | grep -qi "\"email\":\"$RECEPTION_EMAIL\"" && return
  printf "Chrome isn't signed in as:\n%s\n\nClick your picture at the top right of Chrome.\nSign in with that email." "$RECEPTION_EMAIL"
}
chk_slack() {
  local f
  for f in "$HOME/Library/Application Support/Slack/storage/root-state.json" \
           "$HOME/Library/Containers/com.tinyspeck.slackmacgap/Data/Library/Application Support/Slack/storage/root-state.json"; do
    grep -Eq '"workspaces":\{"[A-Z0-9]+"' "$f" 2>/dev/null && return
  done
  printf "Slack isn't signed in.\n\nIn Slack, sign in with:\n%s" "$RECEPTION_EMAIL"
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
  printf "Magnet isn't on the laptop yet.\n\nMagnet costs \$4.99 (one time).\nIn the App Store, click the price.\nPay with Touch ID or the Apple account password.\nWait until it's done."
}

# --- Lucy reads the Gmail's forwarding + filters (Megan, 2026-11-11: "add a
# check that the forwarding addresses were confirmed and that the correct
# filters were set up" -> option B). Gmail keeps these on Google's servers,
# so the person grants ONE read-only permission (gmail.settings.basic + their
# email address) on a Google page; Lucy reads, checks, then REVOKES it. No
# token is ever written to disk. Built-in tools only (a new Mac has no Python):
#   nc     -> catches Google's redirect on 127.0.0.1
#   curl   -> token exchange + Gmail API
#   plutil -> reads Google's JSON replies
# The Google app is the repo's own desktop client (oauth-client.json, already
# public; Google treats a desktop client's secret as non-confidential).
# If the person declines or Google refuses, the step stays on the to-do list
# for the launch team to check by eye -- it never pretends to have checked.
GTOKEN=""; GMAIL_AS=""
OAUTH_CLIENT_URL="https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/oauth-client.json"
_json() { plutil -extract "$2" raw -o - "$1" 2>/dev/null; }   # file  key.path
_urldecode() { local v="${1//+/ }"; printf '%b' "${v//%/\\x}"; }

# One Google consent, used twice: the OWNER's Gmail (filters) and the
# RECEPTION account (the All in One sheet it's shared with).
#   _google_consent  email  scope-url  scope-word  why  tick-name
# -> 0 and fills C_TOKEN / C_REFRESH / C_AS / C_CID / C_SEC; 2 = box unticked.
C_TOKEN=""; C_REFRESH=""; C_AS=""; C_CID=""; C_SEC=""
_google_consent() {
  local want="$1" scope="$2" word="$3" why="$4" tick="$5" t port state url raw code req
  C_TOKEN=""; C_REFRESH=""; C_AS=""
  t="$(mktemp -d)"
  curl -fsSL "$OAUTH_CLIENT_URL" -o "$t/c.json" || { rm -rf "$t"; return 1; }
  C_CID="$(_json "$t/c.json" installed.client_id)"; C_SEC="$(_json "$t/c.json" installed.client_secret)"
  [ -n "$C_CID" ] || { rm -rf "$t"; return 1; }
  port=$(( 49200 + RANDOM % 600 )); state="lucy$RANDOM$RANDOM"
  # offline = a refresh token too, so a long call doesn't outlive the 1-hour
  # access token. It lives in memory only and is revoked at the end.
  url="https://accounts.google.com/o/oauth2/v2/auth?response_type=code&access_type=offline&prompt=consent"
  url="$url&client_id=$C_CID&redirect_uri=http://127.0.0.1:$port&state=$state&login_hint=$want"
  url="$url&scope=${scope}%20email"
  ( printf 'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n<html><body style="font:22px -apple-system;padding:40px">✅ Done. You can close this tab and go back to Lucy.</body></html>' \
      | nc -l 127.0.0.1 "$port" > "$t/req" 2>/dev/null ) &
  local ncpid=$!
  open_chrome "$url"
  _dialog "Step $N of $TOTAL — $TITLE" "${why}

A Google page just opened in Chrome.

1. Pick: ${want}
2. Google says “Google hasn't verified this app”.
That's OK. It's ours.
3. Click “Advanced” (bottom left).
4. Click “Go to Recruiting Report (unsafe)” at the bottom.
5. Tick the box next to ${tick} (or “Select all”).
6. Click “Continue”." "OK" "OK" >/dev/null
  local i=0
  while kill -0 $ncpid 2>/dev/null && [ $i -lt 120 ]; do sleep 1; i=$((i+1)); done
  kill $ncpid 2>/dev/null
  req="$(head -1 "$t/req" 2>/dev/null)"
  echo "$req" | grep -q "state=$state" || { rm -rf "$t"; return 1; }
  raw="$(echo "$req" | sed -n 's/.*[?&]code=\([^& ]*\).*/\1/p')"
  [ -n "$raw" ] || { rm -rf "$t"; return 1; }
  code="$(_urldecode "$raw")"
  curl -fsS https://oauth2.googleapis.com/token \
    --data-urlencode "code=$code" --data-urlencode "client_id=$C_CID" \
    --data-urlencode "client_secret=$C_SEC" --data-urlencode "redirect_uri=http://127.0.0.1:$port" \
    --data-urlencode "grant_type=authorization_code" -o "$t/tok.json" 2>/dev/null
  C_TOKEN="$(_json "$t/tok.json" access_token)"; C_REFRESH="$(_json "$t/tok.json" refresh_token)"
  [ -n "$C_TOKEN" ] || { rm -rf "$t"; return 1; }
  # Google's page lets them untick the box; then the token can't do the job
  # (tested 2026-11-11: HTTP 403 "insufficient authentication scopes").
  if ! _json "$t/tok.json" scope | grep -q "$word"; then
    curl -fsS -d "token=${C_REFRESH:-$C_TOKEN}" https://oauth2.googleapis.com/revoke >/dev/null 2>&1
    C_TOKEN=""; C_REFRESH=""; rm -rf "$t"; return 2
  fi
  curl -fsS -H "Authorization: Bearer $C_TOKEN" https://openidconnect.googleapis.com/v1/userinfo -o "$t/me.json" 2>/dev/null
  C_AS="$(_json "$t/me.json" email | tr 'A-Z' 'a-z')"
  rm -rf "$t"; return 0
}
_consent_retry() {   # same args as _google_consent; asks again if the box wasn't ticked
  local tries=0 rc
  while [ $tries -lt 3 ]; do
    _google_consent "$@"; rc=$?
    [ $rc = 2 ] || return $rc
    tries=$((tries+1))
    _dialog "Step $N of $TOTAL — $TITLE" "Almost! The ${5} box wasn't ticked.

Lucy will open the Google page again.
This time tick the box next to ${5} (or “Select all”). Then click “Continue”." "OK" "OK" >/dev/null
  done
  return 1
}

GREFRESH=""
gmail_auth_retry() {   # owner email -> GTOKEN (+ GMAIL_AS)
  [ $DRY_RUN = 1 ] && { echo "  (dry run) Lucy would ask Google for Gmail settings access (to make + check filters)"; return 1; }
  [ -n "$GTOKEN" ] && [ "$GMAIL_AS" = "$1" ] && return 0
  _consent_retry "$1" "https://www.googleapis.com/auth/gmail.settings.basic" "gmail.settings.basic" \
    "Lucy will set up your Gmail filters for you." "Gmail" || return 1
  GTOKEN="$C_TOKEN"; GREFRESH="$C_REFRESH"; GMAIL_AS="$C_AS"; return 0
}
gmail_auth() { gmail_auth_retry "$@"; }

gmail_done() {   # throw the permission away
  [ -n "$GTOKEN" ] && curl -fsS -d "token=${GREFRESH:-$GTOKEN}" https://oauth2.googleapis.com/revoke >/dev/null 2>&1
  GTOKEN=""; GREFRESH=""; GMAIL_AS=""
}
_gmail_get() {   # settings-path  out-file  -> 0 on HTTP 200/204 (GMAIL_HTTP keeps the code)
  GMAIL_HTTP="$(curl -sS -w '%{http_code}' -H "Authorization: Bearer $GTOKEN" \
    "https://gmail.googleapis.com/gmail/v1/users/me/settings/$1" -o "$2" 2>/dev/null)"
  # 204 = read fine, nothing there (seen 2026-11-11 on an account with no
  # forwarding/filters) -- that's an answer, not an error.
  [ "$GMAIL_HTTP" = 204 ] && : > "$2"
  [ "$GMAIL_HTTP" = 200 ] || [ "$GMAIL_HTTP" = 204 ]
}

# LUCY MAKES THE FILTERS (Megan, 2026-11-12: "since we're doing the google
# allow can we make the forwarding and filters for them?"). The same read +
# settings permission lets Lucy CREATE filters (users.settings.filters.create).
# She can't ADD a forwarding address: Google keeps that for Workspace admins
# only, so the person still types it in and the launch team approves it.
_fwd_status() {   # forward-to -> accepted | pending | (empty)
  local t i e st=""; t="$(mktemp -d)"
  if _gmail_get forwardingAddresses "$t/fa.json"; then
    i=0
    while e="$(_json "$t/fa.json" forwardingAddresses.$i.forwardingEmail)"; [ -n "$e" ]; do
      [ "$(echo "$e" | tr 'A-Z' 'a-z')" = "$1" ] && st="$(_json "$t/fa.json" forwardingAddresses.$i.verificationStatus)"
      i=$((i+1))
    done
  fi
  rm -rf "$t"; echo "$st"
}
chk_fwd_added() {   # forward-to
  [ -n "$GTOKEN" ] || return 0
  [ -n "$(_fwd_status "$1")" ] && return
  printf "Lucy can't find %s as a forwarding address yet.\n\n1. Click “Add a forwarding address”.\n2. Type it.\n3. Click Next. Then Proceed. Then OK.\nThen click “Check again”." "$1"
}
_has_filter() {   # filters.json  from  subject  to
  local i=0 f_from f_subj fwd
  while f_from="$(_json "$1" filter.$i.criteria.from)" || _json "$1" filter.$i.id >/dev/null; do
    fwd="$(_json "$1" filter.$i.action.forward | tr 'A-Z' 'a-z')"
    f_subj="$(_json "$1" filter.$i.criteria.subject)"
    if echo "$f_from" | grep -qiF "$2" && [ "$fwd" = "$4" ] \
       && { [ -z "$3" ] || echo "$f_subj" | grep -qiF "$3"; }; then return 0; fi
    i=$((i+1)); [ $i -gt 400 ] && break
  done
  return 1
}
make_filters() {   # forward-to  "from|subject|Name" ...   (only the missing ones)
  [ -n "$GTOKEN" ] || return 1
  local to="$1"; shift
  local t e from subj name crit code; t="$(mktemp -d)"
  _gmail_get filters "$t/fl.json" || { rm -rf "$t"; return 1; }
  for e in "$@"; do
    IFS='|' read -r from subj name <<< "$e"
    _has_filter "$t/fl.json" "$from" "$subj" "$to" && continue
    crit="\"from\":\"$from\""; [ -n "$subj" ] && crit="$crit,\"subject\":\"$subj\""
    code="$(curl -sS -w '%{http_code}' -o "$t/new.json" -X POST \
      -H "Authorization: Bearer $GTOKEN" -H "Content-Type: application/json" \
      -d "{\"criteria\":{$crit},\"action\":{\"forward\":\"$to\"}}" \
      https://gmail.googleapis.com/gmail/v1/users/me/settings/filters 2>/dev/null)"
    [ "$code" = 200 ] && ok "Lucy made the filter: $name" || echo "  filter $name: Google said $code" >&2
  done
  rm -rf "$t"; return 0
}

chk_gmail_setup() {   # gmail-we-expect  forward-to  "from|subject|Name" ...
  local want="$1" to="$2"; shift 2
  [ -n "$GTOKEN" ] || { printf "Lucy couldn't open your Gmail settings.\n\nAsk the launch team to check your forwarding and filters."; return; }
  if [ -n "$GMAIL_AS" ] && [ "$GMAIL_AS" != "$want" ]; then
    printf "Lucy got permission for:\n%s\nbut the codes go to:\n%s\n\nAsk the launch team." "$GMAIL_AS" "$want"; return
  fi
  local t i e status="" from subj fwd ok_f miss=""
  t="$(mktemp -d)"
  if ! _gmail_get forwardingAddresses "$t/fa.json"; then
    rm -rf "$t"; printf "Lucy couldn't read your Gmail settings (Google said %s).\n\nAsk the launch team to check your forwarding and filters." "${GMAIL_HTTP:-no answer}"; return
  fi
  i=0
  while e="$(_json "$t/fa.json" forwardingAddresses.$i.forwardingEmail)"; [ -n "$e" ]; do
    if [ "$(echo "$e" | tr 'A-Z' 'a-z')" = "$to" ]; then status="$(_json "$t/fa.json" forwardingAddresses.$i.verificationStatus)"; fi
    i=$((i+1))
  done
  if [ -z "$status" ]; then
    rm -rf "$t"; printf "%s isn't a forwarding address yet.\n\nIn Gmail: Settings → Forwarding → “Add a forwarding address”. Type it. Then click “Check again”." "$to"; return
  elif [ "$status" != accepted ]; then
    rm -rf "$t"; printf "Forwarding to %s isn't approved yet.\n\nAsk the launch team to approve it." "$to"; return
  fi
  if ! _gmail_get filters "$t/fl.json"; then
    rm -rf "$t"; printf "Lucy couldn't read your Gmail filters (Google said %s).\n\nAsk the launch team to check them." "${GMAIL_HTTP:-no answer}"; return
  fi
  for e in "$@"; do
    IFS='|' read -r from subj name <<< "$e"
    ok_f=0; _has_filter "$t/fl.json" "$from" "$subj" "$to" && ok_f=1
    [ $ok_f = 1 ] || miss="$miss$name
"
  done
  rm -rf "$t"
  [ -n "$miss" ] && printf "These filters are missing:\n%s\nIn Gmail: Settings → Filters → “Import filters”. Pick the file from the Desktop again. Then click “Check again”." "$miss"
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
bold "  Laptop Set Up — $ROLE_NAME"
[ $DRY_RUN = 1 ] && bold "  DRY RUN — nothing will change, no pop-ups"
bold "════════════════════════════════════════════"

if [ $DRY_RUN = 0 ]; then
  _dialog "Laptop Set Up — $ROLE_NAME" "Hi! Let's set up this $ROLE_NAME laptop.

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
# ROLE: the owner (and, until told otherwise, an admin) signs in to their OWN
# Apple account; reception's laptop uses the reception iCloud (Maud 11/11).
if [ "$ROLE" = reception ]; then COMPUTER=office; else COMPUTER=owner; fi
PERSON_NAME="$(recall PERSON_NAME)"
while [ -z "$PERSON_NAME" ]; do
  if [ $DRY_RUN = 1 ]; then PERSON_NAME="Example Person"; break; fi
  PERSON_NAME="$(osascript - "Laptop Set Up" "$( [ "$ROLE" = owner ] && echo "Type the first and last name of the ICD we're setting up." || echo "Type the first and last name of the $ROLE_NAME we're setting up." )" <<'APPLESCRIPT' 2>/dev/null
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
# ROLE: the All in One is named after the ICD (owner), not the admin or
# reception person setting up (Megan, 2026-11-12: "this should be the ICD
# name - this is the admin's name"). On the owner's laptop they're the same.
ICD_NAME="$(recall ICD_NAME)"
if [ "$ROLE" = owner ]; then ICD_NAME="$PERSON_NAME"; fi
while [ -z "$ICD_NAME" ]; do
  if [ $DRY_RUN = 1 ]; then ICD_NAME="Example Owner"; break; fi
  ICD_NAME="$(osascript - "Laptop Set Up — $ROLE_NAME" "Type the first and last name of the ICD (owner) you work for." <<'APPLESCRIPT' 2>/dev/null
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
  ICD_NAME="$(echo "$ICD_NAME" | sed 's/^ *//; s/ *$//')"
done
remember ICD_NAME "$ICD_NAME"

# ------------------------------------------------------------------------
step_0() {
section "Zoom app"
# Purpose (Megan, 2026-11-12): make sure they have the Zoom APP and are signed
# in to it, not using Zoom in the browser -- same for owner, admin, reception.
# ZOOM COMES FIRST (Megan, 2026-11-11: "this should be with the zoom account
# launch prompt and be their personal email"). The launch team runs the rest
# of the setup on that call, so Zoom is installed before anything else -- it's
# small and downloads first -- and they sign in with their PERSONAL email.
wait_for_file "zoom.us.pkg" "Getting Zoom ready"
install_pkgs "zoom.us"
run open -a zoom.us 2>/dev/null
human zoom "Zoom is open.
(Look behind this box.)

Sign in to the Zoom APP (not the browser):
1. Click “Sign in”.
2. Click “Google”. Pick your personal Gmail.
(No Zoom account yet? Click “Sign up” → “Google” instead.)" "Zoom app signed in"
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
  # ROLE: on an admin/reception laptop the ICD has usually made the reception
  # Gmail already -- but sometimes the admin does (Megan, 2026-11-12). Ask.
  ALREADY=""
  if [ "$ROLE" != owner ] && [ $DRY_RUN = 0 ]; then
    if [ "$(_dialog "Step $N of $TOTAL — $TITLE" "Has the reception Gmail already been made?

${RECEPTION_EMAIL}" "No, make it now,Yes, it's made" "Yes, it's made")" = "Yes, it's made" ]; then
      ALREADY=1
      if [ "$(_dialog "Step $N of $TOTAL — $TITLE" "Is this the reception email?

${RECEPTION_EMAIL}" "No, it's different,Yes, that's it" "Yes, that's it")" != "Yes, that's it" ]; then
        RECEPTION_EMAIL="$(ask_email "Type the reception email:" "")"
      fi
      is_done reception_email || mark_done reception_email
      ok "Reception email (already made): $RECEPTION_EMAIL"
    fi
  fi
  [ -z "$ALREADY" ] && open_chrome "https://accounts.google.com/signup"
  if [ -z "$ALREADY" ] && human reception_email "Google is open.

Make this Gmail:
${RECEPTION_EMAIL}

Name: ${SHORT_NAME} Reception" "Reception email created" "I did it" required; then
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
# Newer Chrome has no "Turn on sync" (Megan's test 2026-11-12): being signed
# in to Chrome already saves passwords to the Google account. Older Chrome
# still shows the button, so both are covered.
human chrome_sync "Make sure Chrome is signed in as reception.

1. Click your picture at the top right of Chrome.
2. It should show: ${RECEPTION_EMAIL}
(See “Turn on sync”? Click it. Then “Yes, I'm in”.)" "Chrome signed in as reception"
verify chrome_sync "Chrome signed in as reception" chk_chrome
# No Zoom password to save: they make Zoom with "Sign up -> Google", so it
# logs in through their personal Gmail and has no password of its own.
# (Every other login is saved -- Megan 2026-11-11: "It can all be saved".)

# ------------------------------------------------------------------------
}
step_1.5() {
section "Your All in One sheet"
# Maud makes "All in One - First Last" before the call and shares it with
# reception as Editor; its "Passwords" tab gets every login from here on
# (Maud + Megan, 2026-11-12). It moved up from near the end so it's open
# before the first password is saved.
ALLIN_NAME="All in One - ${ICD_NAME}"
human drive_shared "Wait for the launch team to share your All in One with:
${RECEPTION_EMAIL}

It's named: ${ALLIN_NAME}" "All in One shared with reception (launch team)" "They confirmed it done"
open_chrome "https://drive.google.com/drive/search?q=%22$(echo "$ALLIN_NAME" | sed 's/ /%20/g')%22"
human allin_open "Google Drive is open.

1. Open “${ALLIN_NAME}”.
2. Click the “Passwords” tab at the bottom.

Lucy fills in this tab as you go, and pins it for you." "All in One open"
pin_tabs allin_pin "All in One|docs.google.com/spreadsheets"
if sheets_auth; then
  sleep 3; find_allin_sheet || echo "  ⚠️  Lucy couldn't find the All in One tab in the Reception Chrome -> typed by hand"
else
  echo "  ⚠️  Google Sheets permission didn't go through -> All in One typed by hand"
fi
allin_login allin_gmail "Gmail" "$RECEPTION_EMAIL"
# Zoom on this laptop is the person's PERSONAL account -> not saved. Only a
# COMPANY Zoom login goes in the All in One, if the office has one (Megan,
# 2026-11-12).
if [ $DRY_RUN = 1 ] || ! is_done allin_zoom_asked; then
  if [ $DRY_RUN = 0 ] && [ "$(_dialog "Step $N of $TOTAL — $TITLE" "Does the office have a COMPANY Zoom login?

(Not your personal one.)" "No,Yes" "No")" = "Yes" ]; then
    allin_login allin_zoom "Zoom" ""
  fi
  [ $DRY_RUN = 0 ] && mark_done allin_zoom_asked
fi
}

step_2() {
section "Apple account (iCloud)"
# ROLE: owners and admins are already signed in to their OWN Apple account on
# their Mac -- nothing to do or check (Megan, 2026-11-12). Only RECEPTION
# creates an iCloud account, with the reception email.
# Saved: the OWNER's Apple login (on the owner's laptop) and RECEPTION's.
# An admin's personal Apple account is never saved (Megan, 2026-11-12).
if [ "$ROLE" = admin ]; then ok "Apple account: the admin's own (not saved)"; return 0; fi
if [ "$ROLE" = owner ]; then
  ok "Apple account: the owner's own, already signed in"
  save_password pw_apple "Apple account" "apple.com" "$(defaults read MobileMeAccounts Accounts 2>/dev/null | sed -n 's/.*AccountID = "\{0,1\}\([^";]*\).*/\1/p' | head -1)" "Apple Accounts|Apple Account|Apple"
  return 0
fi
if [ "$COMPUTER" = owner ] && [ $DRY_RUN = 0 ] && [ -z "$(chk_apple_any)" ]; then
  # A new Mac signs in to Apple during its own first-time setup, before the
  # call (Megan, 2026-11-11) -- so usually there's nothing to do here.
  ok "Apple account already signed in"; is_done icloud || mark_done icloud
  save_password pw_apple "Apple account" "apple.com" "$(defaults read MobileMeAccounts Accounts 2>/dev/null | sed -n 's/.*AccountID = "\{0,1\}\([^";]*\).*/\1/p' | head -1)" "Apple Accounts|Apple Account|Apple"
elif [ "$COMPUTER" = owner ]; then
  run open "x-apple.systempreferences:com.apple.systempreferences.AppleIDSettings"
  human icloud "System Settings is open.
(The gray ⚙️ window. Look behind this box.)

1. Click “Sign in”.
2. Sign in with YOUR OWN Apple account." "Owner's own iCloud signed in"
  verify icloud "Apple account signed in" chk_apple_any
  save_password pw_apple "Apple account" "apple.com" "$(defaults read MobileMeAccounts Accounts 2>/dev/null | sed -n 's/.*AccountID = "\{0,1\}\([^";]*\).*/\1/p' | head -1)" "Apple Accounts|Apple Account|Apple"
else
  run open "x-apple.systempreferences:com.apple.systempreferences.AppleIDSettings"
  human icloud "System Settings is open.
(The gray ⚙️ window. Look behind this box.)

1. Click “Sign in”.
2. Click “Create Apple Account”.
3. Use this email:
${RECEPTION_EMAIL}

Already signed in to a different Apple account? Ask the launch team." "iCloud for reception email created"
  verify icloud "Apple account signed in as reception" chk_apple
  save_password pw_apple "Apple account" "apple.com" "$(defaults read MobileMeAccounts Accounts 2>/dev/null | sed -n 's/.*AccountID = "\{0,1\}\([^";]*\).*/\1/p' | head -1)" "Apple Accounts|Apple Account|Apple"
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

Magnet costs \$4.99 (one time). It's not free.

1. Click the price button (“\$4.99”).
2. A box opens. There is no Buy button.
   Pay with Touch ID (finger on the top-right key),
   or type the Apple account password if it asks.
3. Wait until it's done." "Magnet installed"
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
section "Gmail, Calendar, Drive"
open_chrome "https://mail.google.com/" "https://calendar.google.com/" "https://drive.google.com/"
# PIN, NOT BOOKMARK (Maud, 2026-11-12) -- Lucy pins them herself.
sleep 3
pin_tabs chrome_google "Gmail|mail.google.com" "Calendar|calendar.google.com" "Drive|drive.google.com"
verify chrome_google "Chrome signed in as reception, sync on" chk_chrome

# ------------------------------------------------------------------------
}
step_7() {
section "Sign in to work websites"
for entry in "${WORK_SITES[@]}"; do
  IFS='|' read -r sname surl <<< "$entry"
  open_chrome "$surl"
  extra=""
  # Maud makes their BlueInk login and the launch team gives it to them on the
  # call (2026-11-11); then it's a normal log in + save + pin like the others.
  [ "$sname" = "BlueInk" ] && extra="
The launch team will give you your BlueInk login."
  human "site_$sname" "${sname} is open.

1. Log in.${extra}
2. Chrome asks to save the password. Click “Save”.

Lucy pins this tab and fills in your All in One." "Chrome: logged in to $sname + saved"
  # what to look for in the saved address (Apex lives on herbjoyent.com)
  needle="$(echo "$sname" | tr 'A-Z' 'a-z')"; [ "$sname" = "Apex" ] && needle="herbjoyent"
  verify "site_$sname" "$sname: password saved" chk_passwords "$sname|$needle"
  pin_tabs "pin_$sname" "$sname|$needle"
  allin_login "allin_$sname" "$sname" "$(_saved_username "$needle")"
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
# ROLE: on an admin/reception laptop these are the ICD's logins, not theirs
# (Megan, 2026-11-12: "this needs to say ICD login not your").
if [ "$ROLE" = owner ]; then WHOSE="your"; else WHOSE="${ICD_NAME:-the ICD}'s"; fi
OWNER_EMAIL="$(recall OWNER_EMAIL)"
if [ -z "$OWNER_EMAIL" ]; then
  OWNER_EMAIL="$(ask_email "Next: ${WHOSE} Sara+, Sterling and OwnerVille login codes will go to reception.

What email address is ${WHOSE} Sara+ account set up with?" "")"
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

# ONE Google "Allow" covers this step and the next: Lucy checks the
# forwarding, then makes the filters herself. No permission -> the old
# import-the-file steps come back as the fallback.
if ! is_done filters_reception || ! is_done filters_lucy; then
  gmail_auth_retry "$OWNER_EMAIL"
fi
if is_done filters_reception; then
  ok "Owner's Gmail forwards login codes to reception (done earlier)"
else
  open_chrome "$OWNER_GMAIL#settings/fwdandpop"
  human fwd_reception_added "Gmail is open for:
${OWNER_EMAIL}
(the email ${WHOSE} Sara+ account uses)
Sign in to it if it asks.

1. Click “Add a forwarding address”.
2. Type:
${RECEPTION_EMAIL}
3. Click Next. Then Proceed. Then OK.

Don't change anything else." "Owner's Gmail: reception added as a forwarding address"
  verify fwd_reception_added "reception added as a forwarding address" chk_fwd_added "$RECEPTION_EMAIL"
  human fwd_reception_confirmed "Wait for the launch team to approve your forwarding." "Launch team approved the reception forwarding" "They confirmed it done"
  if is_done fwd_reception_confirmed || [ $DRY_RUN = 1 ]; then
    if make_filters "$RECEPTION_EMAIL" \
         "security.info@saraplus.com||Sara+ codes" \
         "$STERLING|Authentication Request|Sterling codes" \
         "noreply@ownerville.com|Your Account Verification Code|OwnerVille codes"; then
      mark_done filters_reception
    else
      open_chrome "$OWNER_GMAIL#settings/filters"
      human filters_reception "Gmail is open.

1. Scroll to the bottom. Click “Import filters”.
2. Click “Choose File”. Pick this from the Desktop:
Gmail-Filters-1-Reception
3. Click “Open file”. Then “Create filters”." "Owner's Gmail forwards Sara+, Sterling and OwnerVille login codes to reception"
    fi
    verify filters_reception "Gmail forwards login codes to reception (forwarding approved, 3 filters)" \
      chk_gmail_setup "$OWNER_EMAIL" "$RECEPTION_EMAIL" \
      "security.info@saraplus.com||Sara+ codes" \
      "$STERLING|Authentication Request|Sterling codes" \
      "noreply@ownerville.com|Your Account Verification Code|OwnerVille codes"
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
(the email ${WHOSE} Sara+ account uses)
Sign in to it if it asks.

1. Click “Add a forwarding address”.
2. Type:
${LUCY_BG_INBOX}
3. Click Next. Then Proceed. Then OK.

Don't change anything else." "Owner's Gmail: Lucy added as a forwarding address"
  verify fwd_lucy_added "Lucy added as a forwarding address" chk_fwd_added "$LUCY_BG_INBOX"
  human fwd_lucy_approved "Wait for the launch team to approve your forwarding." "Launch team approved the Lucy forwarding" "They confirmed it done"
  if is_done fwd_lucy_approved || [ $DRY_RUN = 1 ]; then
    if make_filters "$LUCY_BG_INBOX" "$STERLING||Sterling background checks"; then
      mark_done filters_lucy
    else
      open_chrome "$OWNER_GMAIL#settings/filters"
      human filters_lucy "Gmail is open.

1. Scroll to the bottom. Click “Import filters”.
2. Click “Choose File”. Pick this from the Desktop:
Gmail-Filters-2-Lucy-Background-Checks
3. Click “Open file”. Then “Create filters”." "Owner's Gmail forwards Sterling background checks to Lucy"
    fi
    verify filters_lucy "Gmail forwards background checks to Lucy (forwarding approved, filter)" \
      chk_gmail_setup "$OWNER_EMAIL" "$LUCY_BG_INBOX" "$STERLING||Sterling background checks"
  fi
fi
gmail_done
[ $DRY_RUN = 1 ] && rm -rf "$OUT"

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
# The laptop's Slack is a NEW account on the RECEPTION email -- that's the one
# the launch team makes admin; their own Slack stays on their phone (Megan +
# Maud, 2026-11-12). Slack signs in with a code emailed to reception, so
# there's no password to save -- it's logged in the All in One like Excel.
human slack_invite "Wait for the launch team to invite the reception email to Slack:
${RECEPTION_EMAIL}

(The invite lands in that Gmail.)" "Launch team invited reception to Slack" "They confirmed it done"
human slack_signin "Slack is open.
(Look behind this box.)

Make a new Slack account for reception:
1. Click “Create an account” (or “Sign in”).
2. Type: ${RECEPTION_EMAIL}
3. Slack emails a code. Open Gmail (pinned in Chrome). Type the code.
4. Join the company Slack from the invite.
" "Slack: reception account signed in"
verify slack_signin "Slack signed in" chk_slack
allin_login allin_slack "Slack" "$RECEPTION_EMAIL" "code sent to email"
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
# The owner is already a Slack admin; the RECEPTION email is the one that
# needs it (Maud, 2026-11-12).
human slack_admin "Ask the launch team to make the reception email a Slack admin:
${RECEPTION_EMAIL}

They will do it on the Zoom call." "Slack: reception made admin (AO)" "They confirmed it done"

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
allin_login allin_excel "Microsoft Office|Miscrosoft Office|Excel" "alphaletereception@gmail.com" "code sent to email"

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

1. Make sure this laptop is on the office Wi-Fi.
2. Turn on the printer. Make sure the printer is on the office Wi-Fi too.
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
STEPS=($(declare -F | awk '{print $3}' | grep -E '^step_[0-9.]+$' | sort -t_ -k2 -g))
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

gmail_done   # never leave a Google permission behind, whatever step they stopped at
sheets_done

# ----------------------------------------------------------------- report
REPORT="$HOME/Desktop/Laptop-Setup-Report.txt"
[ $DRY_RUN = 1 ] && REPORT="$(mktemp)"
{
  echo "Laptop Set Up — $(scutil --get ComputerName 2>/dev/null) — $(date '+%Y-%m-%d %H:%M')"
  echo "For: $PERSON_NAME ($ROLE_NAME, ICD: $ICD_NAME)    Reception email: $RECEPTION_EMAIL    Sara+ email: $OWNER_EMAIL"
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
