#Requires -Version 5.1
<#
.SYNOPSIS
    Сборка дистрибутива JarvisInstaller.exe (Inno Setup 6).

.DESCRIPTION
    1. Наполняет installer\stage через `git archive HEAD` — в дистрибутив
       попадают только отслеживаемые git-файлы (без .git, .venv, bin/obj,
       jarvis.db, logs и прочих локальных данных).
    2. Запускает ISCC.exe для installer\Jarvis.iss.
    Результат: installer\Output\JarvisInstaller.exe

.PARAMETER Edition
    Редакция для install.ps1: python (по умолчанию) | dotnet | both.

.PARAMETER WorkingTree
    Архивировать не HEAD, а текущее рабочее дерево (учесть некоммиченные
    изменения, кроме gitignored-файлов). Удобно для отладки установщика.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1
    powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -Edition both -WorkingTree
#>
[CmdletBinding()]
param(
    [ValidateSet('python', 'dotnet', 'both')]
    [string]$Edition = 'python',
    [switch]$WorkingTree
)

$ErrorActionPreference = 'Stop'

function Write-Info([string]$Msg) { Write-Host ('   ' + $Msg) -ForegroundColor Gray }
function Write-Fail2([string]$Msg) { Write-Host ('   [X]  ' + $Msg) -ForegroundColor Red }

$root = Split-Path -Parent $PSScriptRoot
$issPath = Join-Path $PSScriptRoot 'Jarvis.iss'
$stageDir = Join-Path $PSScriptRoot 'stage'
$stageZip = Join-Path $PSScriptRoot 'stage.zip'
$outputDir = Join-Path $PSScriptRoot 'Output'

# --- 1. Версия из config/config.json ---
$version = '1.7.0'
$cfgPath = Join-Path $root 'config\config.json'
if (Test-Path $cfgPath) {
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.version) { $version = [string]$cfg.version }
    } catch {
        Write-Info ('config/config.json не разобран, версия по умолчанию ' + $version)
    }
}
Write-Host ''
Write-Host ('=== Сборка дистрибутива JARVIS ' + $version + ' (редакция: ' + $Edition + ') ===') -ForegroundColor Cyan

# --- 2. ISCC.exe ---
function Find-ISCC {
    $candidates = @()
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe') }
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe') }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe') }
    $cmd = Get-Command 'iscc.exe' -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { $candidates += $cmd.Source }
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    return $null
}

$iscc = Find-ISCC
if ($null -eq $iscc) {
    Write-Fail2 'Inno Setup 6 не найден.'
    Write-Info 'Скачайте: https://jrsoftware.org/isdl.php и установите (по умолчанию в Program Files (x86)).'
    exit 2
}
Write-Info ('ISCC: ' + $iscc)

# --- 3. Stage: git-архив ---
if (Test-Path $stageDir) { Remove-Item -LiteralPath $stageDir -Recurse -Force }
if (Test-Path $stageZip) { Remove-Item -LiteralPath $stageZip -Force }
New-Item -ItemType Directory -Path $stageDir -Force | Out-Null

$git = Get-Command 'git.exe' -ErrorAction SilentlyContinue
if ($null -eq $git) {
    Write-Fail2 'git не найден — нечем наполнить stage.'
    exit 2
}

if ($WorkingTree) {
    Write-Info 'рабочее дерево: git ls-files -co --exclude-standard'
    Push-Location $root
    try {
        $files = & git ls-files -co --exclude-standard
        if ($LASTEXITCODE -ne 0) { throw 'git ls-files завершился с ошибкой' }
        foreach ($f in $files) {
            $src = Join-Path $root $f
            if (Test-Path -LiteralPath $src -PathType Container) { continue }
            $dst = Join-Path $stageDir $f
            $dstDir = Split-Path -Parent $dst
            if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Info 'git archive HEAD'
    Push-Location $root
    try {
        & git archive --format=zip --output="$stageZip" HEAD
        if ($LASTEXITCODE -ne 0) { throw 'git archive завершился с ошибкой (закоммичены ли изменения?)' }
    } finally {
        Pop-Location
    }
    Expand-Archive -LiteralPath $stageZip -DestinationPath $stageDir -Force
    Remove-Item -LiteralPath $stageZip -Force
}

if (-not (Test-Path (Join-Path $stageDir 'installer\Jarvis.iss'))) {
    Write-Fail2 'В stage нет installer\Jarvis.iss — выполняйте сборку из репозитория JARVIS.'
    exit 2
}
$staged = @(Get-ChildItem -LiteralPath $stageDir -Recurse -File).Count
Write-Info ('файлов в stage: ' + $staged)

# --- 4. Компиляция ---
if (-not (Test-Path $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }
# VersionInfoVersion: только цифры и точки (1.7.0 -> 1.7.0.0)
$fileVersion = ($version -replace '[^0-9.]', '').Trim('.')
if ($fileVersion -eq '') { $fileVersion = '1.7.0.0' }
$parts = @($fileVersion -split '\.')
while ($parts.Count -lt 4) { $parts += '0' }
$fileVersion = ($parts[0..3] -join '.')
Write-Info 'компиляция ISCC...'
& $iscc ("/DStageDir=" + $stageDir) ("/DEdition=" + $Edition) ("/DFileVersion=" + $fileVersion) $issPath
$code = $LASTEXITCODE
if ($null -eq $code) { $code = -1 }

# Stage больше не нужен
Remove-Item -LiteralPath $stageDir -Recurse -Force -ErrorAction SilentlyContinue

if ($code -ne 0) {
    Write-Fail2 ('ISCC завершился с ошибкой (код ' + $code + ')')
    exit 1
}

$setup = Join-Path $outputDir 'JarvisInstaller.exe'
if (Test-Path $setup) {
    $sizeMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host ''
    Write-Host ('ГОТОВО: ' + $setup + ' (' + $sizeMb + ' МБ)') -ForegroundColor Green
    exit 0
}
Write-Fail2 'Файл установщика не найден в installer\Output'
exit 1
