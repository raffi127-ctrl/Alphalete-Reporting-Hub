@echo off
REM Double-click this file (or pin it to the Start Menu) to launch the Reports
REM dashboard on Windows. Mirrors what launch_dashboard.command does on macOS:
REM   - Auto-pulls latest from GitHub when there are no local changes
REM   - Reinstalls Python deps if requirements.txt changed
REM   - Frees port 8501 if a previous run is still holding it
REM   - Starts Streamlit, then opens the browser

REM enabledelayedexpansion is required because we SET variables (DIRTY, LOCAL,
REM REMOTE, port-kill PIDs) inside nested `if (...)` / `for ... (...)` blocks
REM and immediately READ them in subsequent lines of the same block. Without
REM delayed expansion, %VAR% expands at parse time (empty/stale) instead of
REM run time. Use !VAR! inside the blocks.
setlocal enabledelayedexpansion

REM Force UTF-8 for the cmd window AND every Python process spawned from
REM here. Without this, Python 3.13 on Windows defaults stdout to cp1252,
REM and any report log line containing a non-ASCII char (the arrow in
REM "[OK] tab <- office", any owner name with an accent) crashes with
REM UnicodeEncodeError. PYTHONIOENCODING propagates into subprocess env,
REM so the Hub-spawned report runs also pick it up.
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

cd /d "%~dp0"

REM ---- Auto-update from GitHub (skip if there are local edits) ----
if exist ".git" (
    REM Count dirty files via porcelain output.
    for /f %%i in ('git status --porcelain 2^>nul ^| find /c /v ""') do set "DIRTY=%%i"
    if "!DIRTY!"=="0" (
        echo Checking for updates...
        git fetch --quiet origin main
        for /f %%a in ('git rev-parse @ 2^>nul') do set "LOCAL=%%a"
        for /f %%a in ('git rev-parse origin/main 2^>nul') do set "REMOTE=%%a"
        if not "!LOCAL!"=="!REMOTE!" (
            echo Updates found - pulling...
            git pull --ff-only --quiet origin main
            if !ERRORLEVEL! EQU 0 (
                echo Updated to latest version.
                REM Reinstall deps if requirements changed. We use ORIG_HEAD
                REM (set by git after a pull) instead of HEAD@{1}; cmd.exe's
                REM if-block parser chokes on the `{` in HEAD@{1} and bails
                REM with "on was unexpected at this time". ORIG_HEAD is the
                REM same ref in this context but contains no curly braces.
                git diff ORIG_HEAD HEAD --name-only 2>nul | findstr /C:"requirements.txt" >nul
                if !ERRORLEVEL! EQU 0 (
                    echo Updating Python packages...
                    ".venv\Scripts\pip.exe" install --quiet -r automations\recruiting_report\requirements.txt
                )
            ) else (
                echo Auto-update failed; continuing with current version.
            )
        ) else (
            echo Already up to date.
        )
    ) else (
        echo Local changes detected; skipping auto-update.
    )
)

REM ---- Free port 8501 if a previous dashboard is still listening ----
set "PORT=8501"
REM Escape the parens in `(pid %%p)` with ^ — inside a for-loop body, cmd.exe
REM treats unescaped ( and ) as block delimiters and bails with "on was
REM unexpected at this time".
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":!PORT! " ^| findstr "LISTENING"') do (
    echo Stopping previous dashboard ^(pid %%p^) on port !PORT!...
    taskkill /PID %%p /F >nul 2>&1
)

REM ---- Open the browser to the dashboard a couple seconds after Streamlit starts ----
start "" /B cmd /c "timeout /T 3 /NOBREAK >nul && start http://localhost:!PORT!"

REM ---- Run Streamlit ----
".venv\Scripts\python.exe" -m streamlit run automations\dashboard.py ^
    --server.headless true ^
    --server.address 0.0.0.0 ^
    --server.port !PORT!
