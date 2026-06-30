#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║  Mini "Session Check" desktop button.                              ║
# ║  Double-click to check OV / Tableau / AppStream and auto-launch    ║
# ║  any login that's needed before tomorrow's 4am runs.              ║
# ║                                                                    ║
# ║  One-time install on the mini:                                     ║
# ║    cp ~/recruiting-report/deploy/session_check.command ~/Desktop/  ║
# ║    chmod +x ~/Desktop/session_check.command                        ║
# ║  Then double-click "session_check" on the Desktop. (First time,    ║
# ║  macOS may warn — right-click → Open → Open to allow.)            ║
# ╚══════════════════════════════════════════════════════════════════╝
cd ~/recruiting-report 2>/dev/null || {
    echo "Can't find ~/recruiting-report on this machine."
    read -n 1 -s -r -p "Press any key to close…"; exit 1
}
PYTHONPATH=. .venv/bin/python -m automations.shared.session_check
echo ""
read -n 1 -s -r -p "Press any key to close this window…"
echo ""
