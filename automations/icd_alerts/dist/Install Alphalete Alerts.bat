@echo off
REM Double-click me. Everything happens in the window that opens.
REM
REM THIS FILE FINDS A PYTHON AND GETS OUT OF THE WAY. All the real work is in
REM setup.py, shared with the Mac installer, so a fix lands on both.
cd /d "%~dp0"

echo.
echo Starting Alphalete Alerts setup...
echo.

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
if %errorlevel%==0 set "PY=py -3"

if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
  if %errorlevel%==0 set "PY=python"
)

if not defined PY (
  echo This computer needs Python first. Installing it now...
  echo A Windows box may appear asking for permission - please say yes.
  echo.
  winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  echo.
  echo Python was installed. Please CLOSE this window and double-click
  echo the installer again so Windows picks it up.
  echo.
  pause
  exit /b 1
)

%PY% setup.py
set STATUS=%errorlevel%

echo.
pause
exit /b %STATUS%
