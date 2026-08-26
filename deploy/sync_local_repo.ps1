<#
Sincroniza el repo local de esta maquina con origin/main. 2am hora Central.

POR QUE EXISTE. El working tree de esta caja se va quedando atras de origin sin
que nadie lo note: relanzar el Hub deja archivos actualizados en el arbol sin
mover el puntero de la rama, asi que `git status` muestra decenas de archivos
"modificados" que en realidad son copias VIEJAS, y la rama figura adelantada por
commits que ya estan arriba con otro SHA. Medido el 2026-08-26: 584 commits
atras, 23 archivos "modificados" (ninguno con trabajo unico) y 53 commits
"adelante" (todos ya en origin). Mientras dura, cualquier sesion que trabaje en
este repo esta leyendo codigo viejo.

POR QUE HACE STASH Y NO DESCARTA. Hoy los 23 archivos eran todos obsoletos, pero
eso no esta garantizado: otra sesion puede tener trabajo de verdad sin commitear
cuando esto corra. Un `checkout -f` a secas lo borraria en silencio a las 2am. En
vez de eso, todo lo que difiera de origin se guarda en un stash fechado antes de
resetear — recuperable con `git stash list` / `git stash pop`. Nada se pierde,
aunque el arbol quede limpio.

LA HORA. Esta maquina esta en Argentina (UTC-3, SIN horario de verano); Central
SI lo tiene. La diferencia es 2h en verano y 3h en invierno, asi que una hora
local fija se desfasaria sola el 1 de noviembre. La tarea se dispara a las 04:00
y a las 05:00 locales, y este script SALE sin hacer nada salvo que en Central
sean las 2. Se corrige solo en cada cambio de DST, sin tocar nada.

    powershell -File deploy\sync_local_repo.ps1 -DryRun   # no escribe
    powershell -File deploy\sync_local_repo.ps1 -Force    # ignora el chequeo de hora
#>
param(
    [switch]$DryRun,
    [switch]$Force
)

# PS 5.1 convierte el stderr de un comando nativo en excepcion bajo 'Stop',
# y git avisa de CRLF por stderr en casi toda invocacion. Chequeamos
# $LASTEXITCODE explicitamente en cada paso, que es la garantia de verdad.
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repo 'output\logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$log = Join-Path $logDir 'sync-local-repo.log'

function Say($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

# --- la ventana: solo a las 2am Central --------------------------------------
$ct = [System.TimeZoneInfo]::FindSystemTimeZoneById('Central Standard Time')
$central = [System.TimeZoneInfo]::ConvertTime((Get-Date), $ct)
if (-not $Force -and $central.Hour -ne 2) {
    Say ("no es la ventana (Central {0}, se corre a las 02) - salgo" -f $central.ToString('HH:mm'))
    exit 0
}
Say ("=== sync local repo | Central {0} | local {1}{2} ===" -f `
     $central.ToString('yyyy-MM-dd HH:mm'), (Get-Date -Format 'HH:mm'), `
     $(if ($DryRun) { ' | DRY-RUN' } else { '' }))

Set-Location $repo
git fetch origin --quiet
if ($LASTEXITCODE -ne 0) { Say 'git fetch fallo - salgo sin tocar nada'; exit 1 }

$behind = (git rev-list --count HEAD..origin/main).Trim()
$ahead  = (git rev-list --count origin/main..HEAD).Trim()
$dirty  = @(git status --porcelain)
Say ("estado: $behind atras, $ahead adelante, $($dirty.Count) archivo(s) en el arbol")

if ($behind -eq '0' -and $ahead -eq '0' -and $dirty.Count -eq 0) {
    Say 'ya sincronizado - nada que hacer'
    exit 0
}

# --- que se perderia? separar copias viejas de trabajo real -------------------
$real = @()
foreach ($line in $dirty) {
    $path = $line.Substring(3).Trim()
    if ([string]::IsNullOrWhiteSpace($path)) { continue }
    git diff --quiet origin/main -- "$path" | Out-Null
    if ($LASTEXITCODE -ne 0) { $real += $path }
}
if ($real.Count -gt 0) {
    Say ("{0} archivo(s) DIFIEREN de origin - van al stash antes de resetear:" -f $real.Count)
    foreach ($p in $real | Select-Object -First 15) { Say "    $p" }
} else {
    Say 'ningun archivo del arbol difiere de origin (todas copias viejas)'
}

if ($DryRun) {
    Say 'DRY-RUN: aca haria stash (si hace falta) + checkout -f -B main origin/main'
    exit 0
}

if ($real.Count -gt 0) {
    $tag = "sync-local-repo {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm')
    git stash push --include-untracked -m $tag -- $real | ForEach-Object { Say "    $_" }
    if ($LASTEXITCODE -eq 0) { Say "guardado en stash: '$tag' (recuperar con: git stash list)" }
    else { Say 'el stash fallo - NO reseteo, prefiero dejar el arbol como esta'; exit 1 }
}

git checkout -f -B main origin/main | ForEach-Object { Say "    $_" }
if ($LASTEXITCODE -ne 0) { Say 'el checkout fallo'; exit 1 }
Say ("listo - HEAD ahora {0}" -f (git log --oneline -1))
exit 0
