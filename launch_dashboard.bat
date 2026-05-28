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

REM Disable click/colorama's ANSI wrapping on the Windows console. Streamlit's
REM signal handler calls click.secho("Stopping..."), which on Windows goes
REM through colorama -> WriteConsoleW. If a second signal arrives mid-write,
REM Python's BufferedWriter raises 'RuntimeError: reentrant call inside
REM <_io.BufferedWriter>' and the whole Hub server dies (Eve, 2026-05-22).
REM NO_COLOR is a widely-respected env var; click skips colorama when set,
REM so the reentrancy path doesn't exist.
set "NO_COLOR=1"

cd /d "%~dp0"

REM ---- Auto-update from GitHub ----
REM Two modes, decided by the gitignored `.dev-machine` marker:
REM   - DEV machine (marker present): only fast-forward when the tree is clean,
REM     so local uncommitted edits are never discarded.
REM   - TEAMMATE machine (no marker): hard-align to origin/main every launch so
REM     a stray tracked change (often just CRLF line-endings) or a wrong branch
REM     can NEVER strand them on stale code (the bug that hid every fix from
REM     Eve, 2026-05-25).
if exist ".git" (
    for /f %%a in ('git rev-parse @ 2^>nul') do set "PRE_HEAD=%%a"
    set "DID_UPDATE=0"

    if exist ".dev-machine" (
        REM --- DEV machine: protect local edits ---
        for /f %%i in ('git status --porcelain -uno 2^>nul ^| find /c /v ""') do set "DIRTY=%%i"
        if "!DIRTY!"=="0" (
            echo Checking for updates ^(dev^)...
            git fetch --quiet origin main
            for /f %%a in ('git rev-parse @ 2^>nul') do set "LOCAL=%%a"
            for /f %%a in ('git rev-parse origin/main 2^>nul') do set "REMOTE=%%a"
            if not "!LOCAL!"=="!REMOTE!" (
                echo Updates found - pulling...
                git pull --ff-only --quiet origin main
                if !ERRORLEVEL! EQU 0 (
                    echo Updated to latest version.
                    set "DID_UPDATE=1"
                ) else (
                    echo Auto-update failed; continuing with current version.
                )
            ) else (
                echo Already up to date.
            )
        ) else (
            echo Local changes detected; skipping auto-update ^(dev mode^).
        )
    ) else (
        REM --- TEAMMATE machine: force-align to origin/main every launch ---
        echo Syncing to latest...
        git fetch --quiet origin main
        if !ERRORLEVEL! EQU 0 (
            git checkout -f -B main origin/main >nul 2>&1
            if !ERRORLEVEL! EQU 0 (
                echo On latest code.
                set "DID_UPDATE=1"
            ) else (
                echo.
                echo ================================================================
                echo  WARNING: COULD NOT SYNC TO LATEST - you may be running OLD code.
                echo  If a report looks wrong, tell Megan. Manual fix ^(this folder^):
                echo     git fetch origin ^&^& git checkout -f -B main origin/main
                echo ================================================================
                echo.
            )
        ) else (
            echo WARNING: could not reach GitHub - offline? Running current version.
        )
    )

    REM ---- Always sync Python packages on launch.
    REM Previously gated on "requirements.txt was in this pull's diff", which
    REM silently missed teammates whose pull fell outside the change window
    REM (Eve hit ModuleNotFoundError: slack_sdk on 2026-05-28). pip install
    REM --quiet is ~2-4s when everything's already in place - cheap insurance.
    if exist ".venv\Scripts\pip.exe" (
        echo Syncing Python packages...
        ".venv\Scripts\pip.exe" install --quiet -r automations\recruiting_report\requirements.txt
        if !ERRORLEVEL! NEQ 0 (
            echo WARNING: pip install hit an error ^(offline?^) - reports will crash with ModuleNotFoundError if a dep is missing.
        )
    )
    if not exist ".venv\.patchright_chromium_installed" if exist ".venv\Scripts\patchright.exe" (
        echo First-time: installing Chromium for patchright ^(one-time, ~150MB^)...
        ".venv\Scripts\patchright.exe" install chromium >nul 2>&1
        if !ERRORLEVEL! EQU 0 (
            echo. > ".venv\.patchright_chromium_installed"
            echo Chromium installed for patchright.
        ) else (
            echo WARNING: patchright Chromium install failed - run manually:
            echo     .venv\Scripts\patchright.exe install chromium
        )
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
REM --server.fileWatcherType=none: disable Streamlit's auto-reload-on-file-change.
REM The Hub spawns report subprocesses that write to output/logs/active/*.log,
REM and Streamlit's default watcher detects those writes + tries to rerun the
REM dashboard mid-flight. On Windows that rerun trips through colorama's
REM WriteConsoleW and hits 'RuntimeError: reentrant call inside <_io.BufferedWriter>',
REM crashing the whole Hub server (Eve, 2026-05-22). Teammates get new code
REM via git pull + Hub restart anyway, so we don't lose anything by turning
REM auto-reload off.
".venv\Scripts\python.exe" -m streamlit run automations\dashboard.py ^
    --server.headless true ^
    --server.address 0.0.0.0 ^
    --server.port !PORT! ^
    --server.fileWatcherType=none
