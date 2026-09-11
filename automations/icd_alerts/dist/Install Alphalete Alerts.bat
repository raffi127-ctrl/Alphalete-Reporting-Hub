@echo off
REM Double-click me. Everything happens in the window that opens.
REM
REM THIS FILE FINDS A PYTHON AND GETS OUT OF THE WAY. All the real work is in
REM setup.py, shared with the Mac installer, so a fix lands on both.
REM
REM NO PARENTHESISED IF-BLOCKS ANYWHERE BELOW, ON PURPOSE. cmd.exe expands
REM %errorlevel% when it PARSES a block, not when it runs it, so the classic
REM   if not defined PY (
REM     python -c "..."
REM     if %errorlevel%==0 set "PY=python"
REM   )
REM reads the errorlevel from BEFORE the block and silently picks the wrong
REM answer. goto labels have no such trap. Blocks are also the construct that
REM misbehaves if the file ever loses its CRLF line endings, which is why
REM package.py writes this file as CRLF.
cd /d "%~dp0"

echo.
echo Starting Alphalete Alerts setup...
echo.

set "PY="

py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
if errorlevel 1 goto trypython
set "PY=py -3"
goto haspython

:trypython
python -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)" >nul 2>&1
if errorlevel 1 goto nopython
set "PY=python"
goto haspython

:nopython
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

:haspython
%PY% setup.py
set STATUS=%errorlevel%
echo.
pause
exit /b %STATUS%
