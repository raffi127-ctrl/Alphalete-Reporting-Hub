# Alphalete Reporting Hub - one-shot installer for Windows.
#
# Run this in PowerShell (the whole thing, one line):
#   powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/install.ps1 | iex"
#
# Or, if you've already cloned the repo, from the repo folder:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# This is the Windows twin of install.sh. It installs Git + a wheel-friendly
# Python (via winget), clones/updates the repo, builds the venv, installs all
# packages, installs Chromium for patchright, writes the config, and drops a
# "Alphalete Reporting Hub" shortcut on the Desktop + Start Menu that points at
# launch_dashboard.bat.

$ErrorActionPreference = 'Stop'

$InstallDir = Join-Path $HOME 'recruiting-report'
$RepoUrl    = 'https://github.com/raffi127-ctrl/Alphalete-Reporting-Hub.git'
$ProdSheet  = '1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE'

function Say($m)  { Write-Host "-> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }
function Die($m)  { Write-Host "X $m" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "================================================" -ForegroundColor White
Write-Host "  Alphalete Reporting Hub - Windows installer"    -ForegroundColor White
Write-Host "================================================" -ForegroundColor White
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Prerequisites: winget, Git, and a wheel-friendly Python (3.11-3.13).
#    Python 3.14 is too new - several deps (cryptography, pandas) ship no
#    prebuilt packages for it yet, so pip would try to compile from source and
#    fail. Prefer 3.13; install it via winget if nothing suitable is found.
# ---------------------------------------------------------------------------
$haveWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)

function Ensure-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) { return }
    if (-not $haveWinget) {
        Die "Git is not installed and winget is unavailable. Install Git from https://git-scm.com/download/win then re-run this installer."
    }
    Say "Git not found - installing it (a window may appear; approve it)..."
    winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
    # winget doesn't refresh PATH in this session; add Git's default bin so the
    # git command resolves right now without opening a new window.
    $gitBin = 'C:\Program Files\Git\cmd'
    if (Test-Path (Join-Path $gitBin 'git.exe')) { $env:Path = "$gitBin;$env:Path" }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Die "Git was installed but isn't on PATH yet. Close this window, open a NEW PowerShell, and re-run the installer."
    }
}

function PyVersion($exe) {
    try { (& $exe -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null).Trim() }
    catch { '' }
}

# Returns the path/command of a usable Python (3.11-3.13), or $null.
function Find-Python {
    # Prefer the py launcher pinned to a known-good minor version.
    foreach ($v in '3.13','3.12','3.11') {
        try {
            $ver = (& py "-$v" -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null)
            if ($ver) { return @{ Cmd = 'py'; Arg = "-$v"; Ver = $ver.Trim() } }
        } catch {}
    }
    # Fall back to whatever `python` is, if it's in range.
    foreach ($name in 'python','python3') {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c) {
            $ver = PyVersion $c.Source
            if ($ver -in '3.11','3.12','3.13') { return @{ Cmd = $c.Source; Arg = $null; Ver = $ver } }
        }
    }
    # Look in winget/python.org default install locations (per-user and machine).
    foreach ($v in '313','312','311') {
        foreach ($base in @($env:LOCALAPPDATA + "\Programs\Python\Python$v",
                            "$env:ProgramFiles\Python$v",
                            "${env:ProgramFiles(x86)}\Python$v")) {
            $cand = Join-Path $base 'python.exe'
            if (Test-Path $cand) { return @{ Cmd = $cand; Arg = $null; Ver = ($v.Insert(1,'.')) } }
        }
    }
    return $null
}

Ensure-Git

$py = Find-Python
if (-not $py) {
    if (-not $haveWinget) {
        Die "No suitable Python (3.11-3.13) found and winget is unavailable. Install Python 3.13 from https://www.python.org/downloads/release/python-3130/ (check 'Add python.exe to PATH'), then re-run this installer."
    }
    Say "Installing Python 3.13 (a window may appear; approve it)..."
    winget install --id Python.Python.3.13 -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
    $py = Find-Python
    if (-not $py) {
        Die "Python 3.13 was installed but isn't visible yet. Close this window, open a NEW PowerShell, and re-run the installer."
    }
}
# Build a callable form of the chosen Python for splatting into calls.
$PyExe  = $py.Cmd
$PyArgs = @(); if ($py.Arg) { $PyArgs = @($py.Arg) }
Ok "Using Python $($py.Ver)"

# ---------------------------------------------------------------------------
# 2. Clone or update the repo.
# ---------------------------------------------------------------------------
if (Test-Path (Join-Path $InstallDir '.git')) {
    Say "Updating existing install at $InstallDir"
    git -C $InstallDir pull --ff-only
} elseif ((Test-Path $InstallDir) -and (Get-ChildItem $InstallDir -Force -ErrorAction SilentlyContinue)) {
    if (Test-Path (Join-Path $InstallDir 'automations\recruiting_report\fill.py')) {
        Say "Using existing files at $InstallDir"
    } else {
        Die "$InstallDir exists but doesn't look like the project. Move/rename it and re-run."
    }
} else {
    Say "Cloning into $InstallDir"
    git clone $RepoUrl $InstallDir
}
if (-not (Test-Path (Join-Path $InstallDir 'automations\recruiting_report\fill.py'))) {
    Die "The project isn't in place at $InstallDir - the clone/update likely failed (check your internet), then re-run."
}
Set-Location $InstallDir

# ---------------------------------------------------------------------------
# 3. Python venv + packages.
#    Rebuild the venv if it's broken (interpreter gone) or on a different
#    Python than the one we picked (e.g. a stale 3.14 venv from an earlier try).
# ---------------------------------------------------------------------------
$venvPy = Join-Path $InstallDir '.venv\Scripts\python.exe'
if (Test-Path '.venv') {
    $broken = $true
    if (Test-Path $venvPy) {
        try { & $venvPy -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $broken = $false } } catch {}
    }
    if ($broken) {
        Say "Existing .venv is broken - rebuilding..."
        Remove-Item -Recurse -Force '.venv'
    } else {
        $venvVer = PyVersion $venvPy
        if ($venvVer -and ($venvVer -ne $py.Ver)) {
            Say "Existing .venv is on Python $venvVer; rebuilding on $($py.Ver)"
            Remove-Item -Recurse -Force '.venv'
        }
    }
}
if (-not (Test-Path '.venv')) {
    Say "Creating Python venv"
    & $PyExe @PyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Die "Failed to create the Python virtual environment." }
}

Say "Upgrading pip"
& $venvPy -m pip install --quiet --upgrade pip

Say "Installing Python packages (this takes a minute)"
# Force ready-made wheels for the packages that otherwise compile native code
# (cryptography = Rust+OpenSSL; pandas/numpy/pyarrow/pillow/cffi = C). If a
# wheel is missing for this Python, fail FAST with a plain-English fix instead
# of dumping a wall of build errors. Pure-Python deps still install normally.
& $venvPy -m pip install --quiet `
    --only-binary=cryptography,cffi,pandas,numpy,pyarrow,pillow `
    -r automations\recruiting_report\requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Warn "Couldn't install ready-made packages for Python $($py.Ver)."
    Write-Host "   This Python may be too new. Easiest fix: install Python 3.13"
    Write-Host "   ( winget install --id Python.Python.3.13 -e ) and re-run this installer."
    Die "Package install failed."
}

# ---------------------------------------------------------------------------
# 4. Chromium for the patchright browser driver (one-time, ~150MB).
# ---------------------------------------------------------------------------
$marker = Join-Path $InstallDir '.venv\.patchright_chromium_installed'
$patch  = Join-Path $InstallDir '.venv\Scripts\patchright.exe'
if ((Test-Path $patch) -and -not (Test-Path $marker)) {
    Say "Installing Chromium for patchright (one-time)"
    & $patch install chromium 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { New-Item -ItemType File -Path $marker -Force | Out-Null }
    else { Warn "Chromium install hit a snag - the Hub will retry on first launch." }
} elseif (-not (Test-Path $patch)) {
    Warn "patchright CLI not found in .venv - skipping Chromium install."
}

# ---------------------------------------------------------------------------
# 5. Config: Sheet ID + bundled Pack Pass (oauth-client.json).
#    Matches the app, which reads ~/.config/recruiting-report (Path.home()).
# ---------------------------------------------------------------------------
$cfgDir = Join-Path $HOME '.config\recruiting-report'
New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null
# ASCII (no BOM): Windows PowerShell 5.1's -Encoding utf8 prepends a BOM, which
# makes Python's json.load choke on the leading U+FEFF. The Sheet ID is ASCII.
Set-Content -Path (Join-Path $cfgDir 'config.json') -Value "{""spreadsheet_id"": ""$ProdSheet""}" -Encoding ascii
Say "Wrote $cfgDir\config.json (Sheet ID baked in)"

$bundledPass = Join-Path $InstallDir 'oauth-client.json'
if (Test-Path $bundledPass) {
    Copy-Item $bundledPass (Join-Path $cfgDir 'oauth-client.json') -Force
    Say "Installed Pack Pass at $cfgDir\oauth-client.json"
} else {
    Warn "No bundled Pack Pass found - you'll be asked to drop it in via the dashboard on first launch."
}

# ---------------------------------------------------------------------------
# 6. Desktop + Start Menu shortcut -> launch_dashboard.bat.
# ---------------------------------------------------------------------------
$launcher = Join-Path $InstallDir 'launch_dashboard.bat'
function New-HubShortcut($path) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($path)
    $sc.TargetPath       = $launcher
    $sc.WorkingDirectory = $InstallDir
    $sc.WindowStyle      = 7           # start minimized
    $sc.Description       = 'Alphalete Reporting Hub'
    $sc.Save()
}
try {
    New-HubShortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Alphalete Reporting Hub.lnk')
    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    New-HubShortcut (Join-Path $startMenu 'Alphalete Reporting Hub.lnk')
    Say "Added 'Alphalete Reporting Hub' to your Desktop and Start Menu"
} catch {
    Warn "Couldn't create the shortcut automatically. You can launch the Hub any time by double-clicking:"
    Warn "   $launcher"
}

# ---------------------------------------------------------------------------
# 7. Done.
# ---------------------------------------------------------------------------
Write-Host ""
Ok "================================================"
Ok "  Install complete!"
Ok "================================================"
Write-Host ""
Write-Host "DAILY USE:"
Write-Host "  - Double-click the 'Alphalete Reporting Hub' icon on your Desktop"
Write-Host "  - Your browser opens to the Hub (http://localhost:8501)"
Write-Host "  - Sign in with your Pack Access password"
Write-Host ""
Write-Host "  The first time you run a report, a Google sign-in window opens."
Write-Host "  Use your work email (the one with access to the Sheet)."
Write-Host ""
