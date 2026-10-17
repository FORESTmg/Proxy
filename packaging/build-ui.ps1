<#
    FOREST's Proxy Auto-updater — сборка ПОМОЩНИКА ИНТЕРФЕЙСА (Qt) отдельным файлом.

    Отдельный артефакт нужен потому, что Qt весит десятки мегабайт: основная
    программа остаётся лёгкой и без сторонних зависимостей, а значок в трее,
    меню и уведомления живут в forest-ui.exe.

    Что делает (идемпотентно):
      1. находит 64-битный Python 3;
      2. поднимает packaging\.build-venv и ставит PyInstaller + PySide6-Essentials
         (пины в requirements-build.txt / requirements-ui.txt);
      3. собирает forest-ui.exe по спеке forest-ui.spec в packaging\dist\;
      4. печатает размер и SHA256 (рядом — .sha256).

    Примеры:
      powershell -ExecutionPolicy Bypass -File packaging\build-ui.ps1
      powershell -ExecutionPolicy Bypass -File packaging\build-ui.ps1 -NoVenv
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$NoVenv,
    [string]$Python = ''
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Here

$VenvDir = Join-Path $Here '.build-venv'
$BuildDir = Join-Path $Here 'build-ui'
$DistDir = Join-Path $Here 'dist'
$ExePath = Join-Path $DistDir 'forest-ui.exe'
$SpecPath = Join-Path $Here 'forest-ui.spec'
$ReqBuild = Join-Path $Here 'requirements-build.txt'
$ReqUi = Join-Path $Here 'requirements-ui.txt'

function Info($m) { Write-Host "[ui] $m" }
function Die($m) { Write-Host "[ui] ОШИБКА: $m" -ForegroundColor Red; exit 1 }

function Select-Stdout {
    param($Out, [string]$Prefix)
    return ($Out | Where-Object { $_ -is [string] -and $_ -like "$Prefix*" } |
            Select-Object -Last 1)
}

function Get-PythonExe {
    param([string]$Explicit)
    $probe = "import sys;print('PYEXE:'+sys.executable) if (sys.version_info[0]==3 and sys.maxsize>2**32) else sys.exit(3)"
    $cands = @()
    if ($Explicit) { $cands += , @($Explicit) }
    elseif ($env:FOREST_PYTHON) { $cands += , @($env:FOREST_PYTHON) }
    $cands += , @('py', '-3.12')
    $cands += , @('py', '-3.13')
    $cands += , @('py', '-3.11')
    $cands += , @('py', '-3')
    $cands += , @('python')
    foreach ($c in $cands) {
        $exe = $c[0]
        $pre = @()
        if ($c.Count -gt 1) { $pre = $c[1..($c.Count - 1)] }
        $out = & $exe @pre -c $probe 2>&1
        $line = Select-Stdout $out 'PYEXE:'
        if ($LASTEXITCODE -eq 0 -and $line) {
            return @{ Exe = $exe; Pre = $pre; Path = $line.Substring(6) }
        }
    }
    return $null
}

function Invoke-Py {
    param($Py, [string[]]$ArgsList)
    Write-Host ("[ui]   > python " + ($ArgsList -join ' ')) -ForegroundColor DarkGray
    & $Py.Exe @($Py.Pre) @ArgsList 2>&1 | ForEach-Object { Write-Host "    $_" }
    if ($LASTEXITCODE -ne 0) { Die ("python " + ($ArgsList -join ' ') + " вернул код $LASTEXITCODE") }
}

function Has-Mod($Py, $Name) {
    $null = & $Py.Exe @($Py.Pre) -c "import importlib.util as u,sys;sys.exit(0 if u.find_spec('$Name') else 1)" 2>&1
    return ($LASTEXITCODE -eq 0)
}

$base = Get-PythonExe -Explicit $Python
if (-not $base) { Die 'не найден 64-битный Python 3' }
Info "базовый Python: $($base.Path)"

if ($NoVenv) {
    $py = $base
    $where = 'системный Python'
} else {
    $venvPy = Join-Path $VenvDir 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPy)) {
        Info "создаю окружение сборки: $VenvDir"
        Invoke-Py $base @('-m', 'venv', $VenvDir)
    }
    $py = @{ Exe = $venvPy; Pre = @(); Path = $venvPy }
    $where = 'packaging\.build-venv'
}

if (-not (Has-Mod $py 'PyInstaller')) {
    Info "ставлю PyInstaller ($where)"
    Invoke-Py $py @('-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', '-r', $ReqBuild)
}
if (-not (Has-Mod $py 'PySide6')) {
    Info "ставлю PySide6-Essentials ($where) — это большая загрузка, подождите"
    Invoke-Py $py @('-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', '-r', $ReqUi)
}

if (-not $env:SOURCE_DATE_EPOCH) { $env:SOURCE_DATE_EPOCH = '1735689600' }
New-Item -ItemType Directory -Force -Path $DistDir, $BuildDir | Out-Null
Info "собираю помощник интерфейса по спеке forest-ui.spec"
Invoke-Py $py @('-m', 'PyInstaller', '--noconfirm', '--clean',
    '--distpath', $DistDir, '--workpath', $BuildDir, $SpecPath)

if (-not (Test-Path -LiteralPath $ExePath)) { Die "файл не появился: $ExePath" }

$fi = Get-Item -LiteralPath $ExePath
$hash = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLower()
$mib = [math]::Round($fi.Length / 1MB, 2)
"$hash  forest-ui.exe" | Out-File -Encoding ascii (Join-Path $DistDir 'forest-ui.exe.sha256')

Write-Host ''
Write-Host '============ помощник интерфейса готов ============' -ForegroundColor Green
Write-Host "файл:   $ExePath"
Write-Host "размер: $($fi.Length) байт ($mib МиБ)"
Write-Host "sha256: $hash"
Write-Host '==================================================' -ForegroundColor Green
exit 0
