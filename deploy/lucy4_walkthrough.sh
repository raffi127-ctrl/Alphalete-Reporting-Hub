#!/bin/bash
#
# Lucy 4 — GUIDED setup. One command, and it asks you the rest.
#
#   curl -fsSL https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/deploy/lucy4_walkthrough.sh -o /tmp/lucy4.sh && bash /tmp/lucy4.sh
#
# WHY THIS EXISTS (Megan 2026-09-17: "I'd really rather it just prompt me").
# The run sheet was ten commands typed in two places, and the steps that are
# easy to skip are exactly the ones that cost a day — the Google account you
# sign in with, and whether the ownerville session is being REFRESHED rather
# than merely present. A human reading output decides those; this script checks
# them.
#
# THREE RULES IT FOLLOWS
#   1. Verify by EFFECT, never by exit code. A credential push is done when the
#      file is on disk here, not when the queue row says done.
#   2. Re-runnable. Every step detects what is already finished and skips it, so
#      closing the window is never a problem — just run it again.
#   3. It never types a password and never asks you for one. Credentials come
#      from Lucy 1 over the queue.
#
# Runs entirely AT LUCY 4. The credential pushes are queued onto Lucy 1's tab
# from here, so there is no second machine to walk over to.
#
# Bash 3.2 (macOS default) — no associative arrays, no mapfile.

set -u

REPO="$HOME/recruiting-report"
NAME="Lucy 4"
PY="$REPO/.venv/bin/python"
SETUP_URL="https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/deploy/setup_lucy_machine.sh"

B=$'\033[1m'; DIM=$'\033[2m'; R=$'\033[0m'
PINK=$'\033[38;5;205m'; GREEN=$'\033[32m'; AMBER=$'\033[33m'; RED=$'\033[31m'

hr()   { printf '%s\n' "${DIM}────────────────────────────────────────────────────────${R}"; }
say()  { printf '%s\n' "$1"; }
head2(){ printf '\n%s\n' "${PINK}${B}$1${R}"; hr; }
ok()   { printf '%s\n' "  ${GREEN}✓${R} $1"; }
warn() { printf '%s\n' "  ${AMBER}!${R} $1"; }
bad()  { printf '%s\n' "  ${RED}✗${R} $1"; }
note() { printf '%s\n' "    ${DIM}$1${R}"; }

pause() { printf '\n%s' "${B}$1${R} "; read -r _ignored; }

# yn "question" [default y|n] -> 0 for yes
yn() {
    local q="$1" d="${2:-y}" a
    while true; do
        if [ "$d" = "y" ]; then printf '\n%s %s' "${B}$q${R}" "[Y/n] ";
        else printf '\n%s %s' "${B}$q${R}" "[y/N] "; fi
        read -r a
        [ -z "$a" ] && a="$d"
        case "$a" in [Yy]*) return 0 ;; [Nn]*) return 1 ;; esac
    done
}

py() { ( cd "$REPO" && PYTHONPATH=. "$PY" "$@" ); }

have_repo() { [ -x "$PY" ] && [ -d "$REPO/automations" ]; }

# ---------------------------------------------------------------- intro
clear 2>/dev/null
printf '%s\n' "${PINK}${B}"
cat <<'ART'
   Lucy 4 — setup walkthrough
ART
printf '%s' "${R}"
hr
cat <<TXT
This will ask you a handful of questions and do the rest itself.

  1. Install the Hub on this machine        (~10-20 min, mostly waiting)
  2. Three switches in System Settings      (it opens each one for you)
  3. Let the reports use Messages           (one Allow click)
  4. Bring the passwords over from Lucy 1   (nothing typed)
  5. Check it actually works                (~7 min, it waits for you)

You can stop any time and run this again — it picks up where it left off.
Nothing here needs a password except step 1, which asks for this Mac's.
TXT
pause "Press Return to start."

# ---------------------------------------------------------------- 1. install
head2 "1 of 5 · Install the Hub"

if have_repo && [ "$(cat "$REPO/.machine-profile" 2>/dev/null)" = "$NAME" ]; then
    ok "Already installed and named '$NAME' — skipping."
else
    say "This installs the reporting app, names this machine '$NAME', and starts"
    say "the background jobs it needs. It will ask for:"
    say ""
    say "  ${B}·${R} this Mac's password   (once, for system settings)"
    say "  ${B}·${R} a GitHub sign-in      (opens in your browser)"
    say "  ${B}·${R} a Google sign-in      (opens in your browser)"
    say ""
    printf '%s\n' "  ${AMBER}${B}For the Google one, sign in as alphaletereporting@gmail.com.${R}"
    note "Not a personal account. Signing in wrong doesn't show an error now —"
    note "it fails weeks later with a message that is literally blank."
    pause "Press Return and it will start."

    curl -fsSL "$SETUP_URL" -o /tmp/setup_lucy.sh || {
        bad "Couldn't download the installer. Check this Mac is on the internet."
        exit 1
    }
    bash /tmp/setup_lucy.sh Lucy 4

    if have_repo; then ok "Installed."
    else
        bad "The installer didn't finish."
        say "  Read what it printed above, fix that, then run this walkthrough again."
        exit 1
    fi
fi

# ---------------------------------------------------------------- 2. toggles
head2 "2 of 5 · Three switches"

say "These can't be done in code — each one would mean writing your password"
say "to a file. It opens each panel; you flip the switch and come back."

# -- filevault FIRST. macOS refuses automatic login while FileVault is on (the
# option is greyed out), so asking for auto-login first sent the person at Lucy 4
# to a switch they could not flip (2026-09-19, Lucy 4's own setup).
fv_off() { case "$(fdesetup status 2>/dev/null)" in *"FileVault is Off"*) return 0 ;; esac; return 1; }
if fv_off; then
    ok "FileVault is already off."
else
    say ""
    say "${B}a) FileVault OFF${R} — with it on, a restart stops at a password"
    say "   prompt and the reports never start. macOS also won't allow"
    say "   automatic login (the next switch) until this is off."
    if yn "Open Privacy & Security now?"; then
        open "x-apple.systempreferences:com.apple.preference.security?FileVault" 2>/dev/null
        say "   Scroll to FileVault and click Turn Off. It decrypts in the"
        say "   background — you don't have to wait here for that."
        pause "Clicked Turn Off? Press Return."
    fi
fi

# -- auto login. The plist is world-readable: no sudo. (It used `sudo -n`,
# which fails silently once step 1's password timestamp has expired, so it
# always reported auto-login as off.)
if [ -n "$(defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>/dev/null)" ]; then
    ok "Automatic login is already on."
else
    say ""
    say "${B}b) Automatic login${R} — so the machine comes back by itself after a"
    say "   power cut, instead of sitting at the login screen all weekend."
    if yn "Open Users & Groups now?"; then
        open "x-apple.systempreferences:com.apple.preferences.users" 2>/dev/null
        say "   Set 'Automatically log in as' to this machine's user."
        if ! fv_off; then
            say "   ${AMBER}Greyed out? FileVault is still decrypting — the Privacy &${R}"
            say "   ${AMBER}Security panel shows progress. Once it's done this unlocks.${R}"
        fi
        pause "Done? Press Return."
    fi
fi

# -- messages sign-in
say ""
say "${B}c) Sign in to Messages${R} with the Lucy Apple ID, so the texting"
say "   reports can send from this machine later."
if yn "Open Messages now?"; then
    open -a Messages 2>/dev/null
    pause "Signed in? Press Return."
fi

# ---------------------------------------------------------------- 3. messages grant
head2 "3 of 5 · Let the reports use Messages"

say "macOS asks permission per program, and it has to be the ${B}scheduled job${R}"
say "that asks — not you, and not Terminal. Sending a test text yourself grants"
say "Terminal and changes nothing for the reports."
say ""
say "This is also the one thing that can't be done remotely later, which is why"
say "it happens now even though no texting report is assigned to this box yet."

if [ -f "$REPO/deploy/grant_orchestrator_messages.sh" ]; then
    if yn "Run it? A dialog will pop up — click Allow."; then
        bash "$REPO/deploy/grant_orchestrator_messages.sh"
        pause "Press Return when you've read what it said."
    else
        warn "Skipped. Texting reports can't move here until this is done."
    fi
else
    warn "grant_orchestrator_messages.sh isn't here yet — finish step 1 first."
fi

# ---------------------------------------------------------------- 4. credentials
head2 "4 of 5 · Bring the passwords over from Lucy 1"

say "Nothing gets typed. Lucy 1 already has these, and it sends them across."
say "That also means the AppStream username can't be mistyped — the spelling"
say "has a space in it and getting it wrong doesn't raise an error, it just"
say "quietly stops every report that uses it."

# file-key:landing-path  (bash 3.2 — parallel strings, not a hash)
CRED_KEYS="ownerville-creds gmail-app-password"
cred_path() {
    case "$1" in
        ownerville-creds)   printf '%s' "$REPO/ownerville-creds.json" ;;
        gmail-app-password) printf '%s' "$HOME/.config/recruiting-report/gmail-app-password" ;;
    esac
}

NEEDED=""
for k in $CRED_KEYS; do
    [ -f "$(cred_path "$k")" ] || NEEDED="$NEEDED $k"
done
[ -f "$HOME/.config/recruiting-report/slack-user-token" ] || NEEDED="$NEEDED slack-tokens"

if [ -z "$NEEDED" ]; then
    ok "Everything is already here — skipping."
else
    say ""
    say "Still needed:${B}$NEEDED${R}"
    if yn "Ask Lucy 1 to send them?"; then
        for k in $CRED_KEYS; do
            [ -f "$(cred_path "$k")" ] && continue
            py -m automations.day_orchestrator.mini_control --by "Lucy 4 setup" \
               --enqueue push_cred_file "$k $NAME" --machine "Lucy 1" >/dev/null 2>&1 \
               && ok "asked Lucy 1 for $k" || warn "couldn't queue $k"
        done
        if [ ! -f "$HOME/.config/recruiting-report/slack-user-token" ]; then
            py -m automations.day_orchestrator.mini_control --by "Lucy 4 setup" \
               --enqueue push_slack_tokens "$NAME" --machine "Lucy 1" >/dev/null 2>&1 \
               && ok "asked Lucy 1 for the Slack tokens" || warn "couldn't queue Slack tokens"
        fi

        say ""
        say "Waiting for them to land. Lucy 1 checks its queue every couple of"
        say "minutes, so this usually takes 2-5."
        WAITED=0
        while [ $WAITED -lt 600 ]; do
            MISSING=""
            for k in $CRED_KEYS; do
                [ -f "$(cred_path "$k")" ] || MISSING="$MISSING $k"
            done
            [ -f "$HOME/.config/recruiting-report/slack-user-token" ] || MISSING="$MISSING slack"
            [ -z "$MISSING" ] && break
            printf '\r    %s' "${DIM}waiting${MISSING} … ${WAITED}s${R}"
            sleep 15; WAITED=$((WAITED + 15))
        done
        printf '\r%s\r' "                                                            "
        if [ -z "${MISSING:-}" ]; then
            ok "All credentials arrived."
        else
            warn "Still missing:$MISSING"
            note "Not necessarily broken — Lucy 1 may be busy with a long report."
            note "Carry on; run this walkthrough again later and it will pick them up."
        fi
    fi
fi

# the browser the reports drive
if [ -d "$HOME/Library/Application Support/lucy-chrome" ] \
   || [ -d "$REPO/.chrome-pinned" ]; then
    ok "The reports' browser is installed."
else
    say ""
    if yn "Install the browser the reports drive? (a few minutes)"; then
        py -m automations.day_orchestrator.mini_control --by "Lucy 4 setup" \
           --enqueue install_pinned_chrome --machine "$NAME" >/dev/null 2>&1 \
           && ok "queued — it installs in the background" \
           || warn "couldn't queue it; run this walkthrough again later"
    fi
fi

# ---------------------------------------------------------------- 5. verify
head2 "5 of 5 · Check it actually works"

say "Four checks. The last one is the one that matters."

# -- logins
say ""
say "${B}Logins${R} — both OwnerVille and AppStream, on this machine."
if py -m automations.shared.login_check; then
    ok "Both logins are good."
else
    bad "A login failed — read the lines above; it names which one."
    note "Re-run this walkthrough after fixing it."
fi

# -- who this machine is
say ""
say "${B}Identity${R} — which accounts this machine is using."
py - <<'PYEOF' 2>/dev/null || warn "couldn't read identity (finish step 1?)"
from automations.shared import fleet
from automations.shared import session_holder as sh
me = sh._this_machine()
m = fleet.get(me)
print("    this machine says it is: %s" % me)
if m:
    print("    OwnerVille account:      %s (%s)" % (m.ownerville_account, m.owner_display_name))
    print("    AppStream account:       %s" % fleet.APPSTREAM_ACCOUNT)
else:
    print("    ⚠ not in the fleet roster — the name marker is wrong")
PYEOF

# -- THE session check
say ""
say "${B}The session${R} — and this is the one that caught nobody out until it did."
say ""
say "Lucy 3 passed every check on setup day and then ran ${B}nothing${R} for four"
say "hours on its first morning. Its login existed; it just was not being kept"
say "fresh. A session that was made once looks identical to a healthy one for"
say "twenty minutes, and is dead after that."
say ""
say "So: measure it, wait six minutes, measure again. If it got ${B}younger${R},"
say "something is refreshing it and this machine is genuinely fine."

age_now() {
    py - <<'PYEOF' 2>/dev/null
from automations.day_orchestrator import readiness
warm, age, reason = readiness.session_status()
print("%.1f" % age if age != float("inf") else "none")
PYEOF
}

A1="$(age_now)"
if [ "$A1" = "none" ] || [ -z "$A1" ]; then
    bad "There's no session yet."
    say "    The background job may still be signing in — it does that by itself,"
    say "    nobody has to clear a 'verify you're human' box."
    if yn "Give it a nudge and wait 3 minutes?"; then
        py -m automations.day_orchestrator.mini_control --by "Lucy 4 setup" \
           --enqueue restart_holder --machine "$NAME" >/dev/null 2>&1
        sleep 180
        A1="$(age_now)"
    fi
fi

if [ "$A1" != "none" ] && [ -n "$A1" ]; then
    ok "Session is there — ${A1} minutes old. Now waiting six minutes."
    i=360
    while [ $i -gt 0 ]; do
        printf '\r    %s' "${DIM}checking again in $((i/60))m $((i%60))s …${R}"
        sleep 10; i=$((i - 10))
    done
    printf '\r%s\r' "                                                  "
    A2="$(age_now)"
    if [ "$A2" = "none" ] || [ -z "$A2" ]; then
        bad "The session disappeared. Something is stopping the background job."
    elif [ "$(printf '%s\n' "$A2 $A1" | awk '{print ($1 <= $2) ? "fresh" : "stale"}')" = "fresh" ]; then
        ok "Now ${A2} minutes old — younger than before. It is being kept fresh. ${GREEN}This is the good outcome.${R}"
    else
        bad "It aged from ${A1} to ${A2} minutes — nothing is refreshing it."
        say "    This is exactly the Lucy 3 failure. The machine will look healthy"
        say "    and run nothing. Tell Megan's Claude: 'Lucy 4 session is not"
        say "    refreshing' before giving this box any reports."
    fi
fi

# -- code up to date
say ""
say "${B}Code${R} — a machine never updates itself, so pull once now."
py -m automations.day_orchestrator.mini_control --by "Lucy 4 setup" \
   --enqueue update --machine "$NAME" >/dev/null 2>&1 \
   && ok "update queued" || warn "couldn't queue the update"

# ---------------------------------------------------------------- done
head2 "Done"
cat <<TXT
Lucy 4 is set up and reachable.

It is deliberately ${B}not${R} running anything yet — it has no reports and is off
the 4am schedule until someone gives it one. An empty profile card on the Hub
is the correct state today, not a fault.

Tell Megan's Claude "Lucy 4 is done" and it will confirm the rest from there.
TXT
hr
