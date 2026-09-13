# Update Lucy Reports on this Windows PC, in place.
#
#   irm https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/update.ps1 | iex
#
# THE TWIN OF update.sh. Same file list, same temp-file-then-move, same proof
# that the agent still imports afterwards. It exists because without it a
# Windows office could be installed and then never updated -- stuck on
# whatever code shipped the day they enrolled, while every fix went to the
# Macs. That is a worse position than not being enrolled at all, because it
# looks fine from our side.
#
# It replaces the program files and NOTHING else: logins, settings and the
# scheduled task are untouched. Nothing to re-enter, nothing to re-approve.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
  [Net.ServicePointManager]::SecurityProtocol =
    [Net.SecurityProtocolType]::Tls12 -bor [Net.ServicePointManager]::SecurityProtocol
} catch {}

$RAW  = 'https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main'
$BUST = [int][double]::Parse((Get-Date -UFormat %s))
$BASE = Join-Path $env:USERPROFILE '.lucy-reports'
$APP  = Join-Path $BASE 'app'
$PY   = Join-Path $BASE 'venv\Scripts\python.exe'

if (-not (Test-Path $APP)) {
  Write-Host "Lucy Reports is not installed on this computer (no $APP)."
  Write-Host 'Run the installer instead.'
  return
}

Push-Location $APP
try {
  Write-Host 'Updating Lucy Reports...'

  # FETCHED, NOT BAKED IN -- the same lesson as update.sh. A list inside this
  # script goes stale the moment a module is added to the agent and not here,
  # and the update then runs, says "up to date", and leaves the machine
  # without it: a successful-looking no-op.
  try {
    $list = (Invoke-WebRequest -UseBasicParsing -Uri "$RAW/automations/icd_alerts/agent_files.txt?t=$BUST").Content
  } catch {
    Write-Host 'Could not reach the update server. Nothing was changed.'
    return
  }

  $fail = $false
  $count = 0
  foreach ($line in ($list -split "`r?`n")) {
    $f = $line.Trim()
    if ($f -eq '' -or $f.StartsWith('#')) { continue }
    $local = $f -replace '/', '\'
    $dir = Split-Path -Parent $local
    if ($dir) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $tmp = "$local.new"
    try {
      # To a temp file first: a half-downloaded module would leave the agent
      # unable to start at all, which is worse than running yesterday's code.
      Invoke-WebRequest -UseBasicParsing -Uri "$RAW/$f`?t=$BUST" -OutFile $tmp
      Move-Item -Force $tmp $local
      $count++
    } catch {
      Remove-Item -Force $tmp -ErrorAction SilentlyContinue
      Write-Host "  could not fetch $f"
      $fail = $true
    }
  }

  if ($fail -or $count -eq 0) {
    Write-Host ''
    Write-Host 'Some files did not download — nothing was half-replaced, and Lucy is'
    Write-Host 'still running the version she had. Try again on a normal wifi network.'
    return
  }

  # Prove it still starts. A syntax error in a file we just replaced would
  # otherwise show up as silence at the next tick.
  & $PY -c 'import automations.icd_alerts.run' 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host "Lucy Reports is up to date ($count files). Nothing else to do —"
    Write-Host 'your logins and settings are unchanged.'
  } else {
    Write-Host ''
    Write-Host 'The update downloaded but Lucy could not start with it.'
    Write-Host 'Please tell the reporting team — your old settings are untouched.'
  }
}
finally {
  Pop-Location
}
