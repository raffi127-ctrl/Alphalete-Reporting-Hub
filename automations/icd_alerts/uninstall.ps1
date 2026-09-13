# Take Lucy Reports off this Windows PC, completely.
#
#   irm https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/uninstall.ps1 | iex
#
# The twin of uninstall.sh. Same three things removed, same confirmation, same
# reason: revoking an office used to turn its key off on our side while its
# computer kept waking up and talking to a relay that refused it.

$ErrorActionPreference = 'Stop'

$BASE   = Join-Path $env:USERPROFILE '.lucy-reports'
$CONFIG = Join-Path $env:USERPROFILE '.config\lucy-reports'
$TASK   = 'Lucy Reports'

Write-Host ''
Write-Host 'This removes Lucy ECOsystem from this computer:'
Write-Host ''
$found = $false
$task = schtasks /Query /TN "$TASK" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host '  * the schedule that wakes it up'; $found = $true }
if (Test-Path $BASE)   { Write-Host "  * the program itself       ($BASE)"; $found = $true }
if (Test-Path $CONFIG) { Write-Host "  * your saved logins        ($CONFIG)"; $found = $true }
if (-not $found) {
  Write-Host '  (nothing found - it is not installed on this computer)'
  Write-Host ''
  return
}
Write-Host ''
Write-Host 'Your numbers in Slack are not affected by this, and nothing on'
Write-Host "Alphalete's side is deleted."
Write-Host ''
$answer = Read-Host 'Type REMOVE and press Enter to go ahead'
if ($answer -ne 'REMOVE') {
  Write-Host ''
  Write-Host 'Nothing was changed.'
  return
}

Write-Host ''
# Stop it FIRST -- deleting the program out from under a running tick leaves a
# half-finished browser and a task that keeps retrying it.
schtasks /Delete /TN "$TASK" /F 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host '  stopped the schedule' }

foreach ($d in @($BASE, $CONFIG)) {
  if (Test-Path $d) {
    Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue
    Write-Host "  removed $d"
  }
}

Write-Host ''
Write-Host 'Lucy ECOsystem is off this computer.'
Write-Host ''
Write-Host 'If this office is coming back, the setup link you were sent still works.'
Write-Host ''
