# Install Lucy Reports on this Windows PC. ONE LINE, pasted into PowerShell:
#
#   $env:LUCY_KEY='KASH-XXXXX-XXXXX-XXXXX'; irm https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/install.ps1 | iex
#
# THE TWIN OF install.sh, and deliberately the same shape: same file list, same
# install.json, same setup.py, same relay fallback. Anything that drifts
# between the two becomes a bug that only one kind of office ever sees, and
# Windows is the kind we cannot easily test.
#
# THE KEY COMES THROUGH AN ENVIRONMENT VARIABLE, not an argument. `irm ... |
# iex` pipes a script into the interpreter and there is nowhere to put an
# argument -- the alternative is the [scriptblock]::Create dance, which is
# longer, easy to mistype and impossible to read down a phone. A variable set
# in front of it is one line a person can actually copy.
#
# WINDOWS HAS NEVER BEEN EXERCISED FOR REAL (still true when this was written).
# Every quirk handled below is a known Windows trap rather than something we
# have watched fail, so the first office to use this should be watched.

$ErrorActionPreference = 'Stop'

# Invoke-WebRequest renders a progress bar that can make a download an order of
# magnitude slower on Windows PowerShell. Silencing it is not cosmetic.
$ProgressPreference = 'SilentlyContinue'
# Windows PowerShell 5.1 still defaults to TLS 1.0/1.1 on some builds, which
# GitHub refuses outright -- it reads as "could not connect" on a machine whose
# internet is fine.
try {
  [Net.ServicePointManager]::SecurityProtocol =
    [Net.SecurityProtocolType]::Tls12 -bor [Net.ServicePointManager]::SecurityProtocol
} catch {}

$RAW  = 'https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main'
$BUST = [int][double]::Parse((Get-Date -UFormat %s))
$KEY  = $env:LUCY_KEY

if ([string]::IsNullOrWhiteSpace($KEY)) {
  Write-Host ''
  Write-Host 'This command needs your office code in front of it, like:'
  Write-Host "  `$env:LUCY_KEY='KASH-XXXXX-XXXXX-XXXXX'; irm $RAW/automations/icd_alerts/install.ps1 | iex"
  Write-Host ''
  Write-Host 'Ask the reporting team for yours.'
  return
}

# KASH-8ABCD-EFGHJ-KLMNP -> kash, and RYAN-ATT-8ABCD-EFGHJ-KLMNP -> ryan-att.
# Everything except the last three groups -- see install.sh for why.
$parts = $KEY -split '-'
if ($parts.Count -gt 3) {
  $OFFICE = ($parts[0..($parts.Count - 4)] -join '-').ToLower()
} else {
  $OFFICE = $parts[0].ToLower()
}
Write-Host ''
Write-Host "Setting up Lucy Reports for: $OFFICE"
Write-Host ''

# --- find a Python we can actually use --------------------------------------
# `py` (the Python launcher) is tried FIRST and on purpose. A bare `python` on
# Windows is very often the Microsoft Store stub: a placeholder that prints an
# advert and exits, which looks exactly like a broken install rather than a
# missing one. The version probe below is what tells them apart -- the stub
# cannot run it.
function Find-Python {
  foreach ($cand in @(@('py','-3'), @('python'), @('python3'))) {
    $exe = $cand[0]
    $pre = @()
    if ($cand.Count -gt 1) { $pre = $cand[1..($cand.Count - 1)] }
    try {
      $args = $pre + @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)')
      & $exe @args 2>$null
      if ($LASTEXITCODE -eq 0) { return ,@($exe, $pre) }
    } catch {}
  }
  return $null
}

$py = Find-Python
if ($null -eq $py) {
  Write-Host 'This PC needs Python first. Installing it now (this is free and'
  Write-Host 'from Microsoft) — it takes a couple of minutes.'
  Write-Host ''
  try {
    winget install --id Python.Python.3.12 -e --source winget `
      --accept-package-agreements --accept-source-agreements
  } catch {
    Write-Host 'Could not install Python automatically.'
  }
  Write-Host ''
  Write-Host 'Now CLOSE this window, open PowerShell again, and paste the same'
  Write-Host 'line one more time. (Windows only notices Python after a restart'
  Write-Host 'of the window.)'
  return
}
$PY_EXE = $py[0]
$PY_PRE = $py[1]

function Invoke-Py {
  param([string[]]$PyArgs)
  $all = $PY_PRE + $PyArgs
  & $PY_EXE @all
}

# --- fetch the program -------------------------------------------------------
$WORK = Join-Path ([System.IO.Path]::GetTempPath()) ("lucy-" + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $WORK -Force | Out-Null
Push-Location $WORK

try {
  Write-Host 'Fetching the program...'
  try {
    $list = (Invoke-WebRequest -UseBasicParsing -Uri "$RAW/automations/icd_alerts/agent_files.txt?t=$BUST").Content
  } catch {
    Write-Host 'Could not reach the update server. Nothing was changed.'
    return
  }

  function Get-One {
    param([string]$Remote, [string]$Local)
    $dir = Split-Path -Parent $Local
    if ($dir) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    try {
      Invoke-WebRequest -UseBasicParsing -Uri "$RAW/$Remote`?t=$BUST" -OutFile $Local
      return $true
    } catch {
      Write-Host "  could not fetch $Remote"
      return $false
    }
  }

  $fail = $false
  foreach ($line in ($list -split "`r?`n")) {
    $f = $line.Trim()
    if ($f -eq '' -or $f.StartsWith('#')) { continue }
    if (-not (Get-One $f $f)) { $fail = $true }
  }
  if (-not (Get-One 'automations/icd_alerts/dist/setup.py' 'setup.py')) { $fail = $true }
  if (-not (Get-One 'automations/icd_alerts/offices_public.json' 'offices.json')) { $fail = $true }
  if ($fail) {
    Write-Host ''
    Write-Host 'Some files did not download. Nothing was changed — try again on a normal wifi network.'
    return
  }

  # install.json, built here from the PUBLIC office config plus the key from
  # the command line. Byte-for-byte the same job as install.sh does, including
  # the relay fallback for an office that signed itself up and therefore is not
  # in the file on GitHub.
  $builder = @'
import json, ssl, sys, urllib.parse, urllib.request
office_key, relay_key = sys.argv[1], sys.argv[2]
pub = json.load(open("offices.json"))
rec = (pub.get("offices") or {}).get(office_key)
if not rec:
    try:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
        url = pub["relay_url"] + "?" + urllib.parse.urlencode({"office": office_key})
        with urllib.request.urlopen(url, timeout=30, context=ctx) as r:
            out = json.loads(r.read().decode("utf-8"))
        rec = out.get("office") if out.get("ok") else None
    except Exception:
        rec = None
if not rec:
    print("")
    print("That code is for an office I do not recognise (%r)." % office_key)
    print("Check it with the reporting team - nothing has been changed.")
    raise SystemExit(1)
rec = dict(rec)
rec["relay_url"] = pub["relay_url"]
rec["relay_key"] = relay_key
json.dump(rec, open("install.json", "w"), indent=2)
print("This is %s's copy (%s)." % (rec["owner"], office_key))
'@
  Set-Content -Path 'build_install.py' -Value $builder -Encoding UTF8
  Invoke-Py @('build_install.py', $OFFICE, $KEY)
  if ($LASTEXITCODE -ne 0) { return }

  Write-Host ''
  Invoke-Py @('setup.py')
}
finally {
  Pop-Location
  # The temp copy has served its purpose: setup.py installs the real one.
  try { Remove-Item -Recurse -Force $WORK -ErrorAction SilentlyContinue } catch {}
}
