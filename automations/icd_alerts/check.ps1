# Is this computer the right one? Installs NOTHING.
#
#   irm https://raw.githubusercontent.com/raffi127-ctrl/Alphalete-Reporting-Hub/main/automations/icd_alerts/check.ps1 | iex
#
# The twin of check.sh. Same rule, same answer, no Python and nothing
# downloaded beyond this script -- it has to work on a machine with nothing
# set up on it yet, which is the entire point.
#
# Win32_Battery is the Windows equivalent of the battery question: a desktop
# reports none. A laptop with the battery removed would read as a desktop,
# which is a machine that behaves like one anyway.

$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host 'Checking this computer...'
Write-Host ''
Write-Host ("  Computer: " + $env:COMPUTERNAME)

$battery = $null
try {
  $battery = Get-CimInstance -ClassName Win32_Battery -ErrorAction SilentlyContinue
} catch {
  $battery = $null
}

if ($battery) {
  Write-Host '  Type:     laptop (it has a battery)'
  Write-Host ''
  Write-Host 'This computer cannot be used.' -ForegroundColor Red
  Write-Host ''
  Write-Host '  Lucy has to read your numbers all day. A laptop stops the moment'
  Write-Host '  its lid is closed or it goes to sleep, so your channel would go'
  Write-Host '  quiet without anybody noticing.'
  Write-Host ''
  Write-Host '  Please run the setup on a desktop that stays on in the office.'
  Write-Host ''
  return
}

Write-Host '  Type:     desktop (no battery)'
Write-Host ''
Write-Host 'This computer can be used.' -ForegroundColor Green
Write-Host ''
Write-Host '  Nothing has been installed. Go back to your setup page and run'
Write-Host '  the install line when you are ready.'
Write-Host ''
