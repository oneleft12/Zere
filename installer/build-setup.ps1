#Requires -Version 5.1
<#
.SYNOPSIS
    Сборка дистрибутива ZereInstaller.exe (Inno Setup 6).

.DESCRIPTION
    1. Наполняет installer\stage через `git archive HEAD` — в дистрибутив
       попадают только отслеживаемые git-файлы (без .git, .venv, bin/obj,
       zere.db, logs и прочих локальных данных).
    2. Запускает ISCC.exe для installer\Zere.iss.
    Результат: installer\Output\ZereInstaller.exe

.PARAMETER Edition
    Редакция для install.ps1: both (по умолчанию) | python | dotnet.
    both — дистрибутив несёт обе редакции; python — облегчённая сборка
    без .NET SDK.

.PARAMETER WorkingTree
    Архивировать не HEAD, а текущее рабочее дерево (учесть некоммиченные
    изменения, кроме gitignored-файлов). Удобно для отладки установщика.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1
    powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -Edition python
    powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -WorkingTree
#>
[CmdletBinding()]
param(
    [ValidateSet('python', 'dotnet', 'both')]
    [string]$Edition = 'both',
    [switch]$WorkingTree
)

$ErrorActionPreference = 'Stop'

function Write-Info([string]$Msg) { Write-Host ('   ' + $Msg) -ForegroundColor Gray }
function Write-Fail2([string]$Msg) { Write-Host ('   [X]  ' + $Msg) -ForegroundColor Red }

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

$root = Split-Path -Parent $PSScriptRoot
$issPath = Join-Path $PSScriptRoot 'Zere.iss'
$stageDir = Join-Path $PSScriptRoot 'stage'
$stageZip = Join-Path $PSScriptRoot 'stage.zip'
$outputDir = Join-Path $PSScriptRoot 'Output'

# --- 1. Версия из config/config.json ---
$version = '1.9.0'
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
Write-Host ('=== Сборка дистрибутива ZERE ' + $version + ' (редакция: ' + $Edition + ') ===') -ForegroundColor Cyan

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

if (-not (Test-Path (Join-Path $stageDir 'installer\Zere.iss'))) {
    Write-Fail2 'В stage нет installer\Zere.iss — выполняйте сборку из репозитория ZERE.'
    exit 2
}
$staged = @(Get-ChildItem -LiteralPath $stageDir -Recurse -File).Count
Write-Info ('файлов в stage: ' + $staged)

# --- 2.1. Метка сборки (config/build-info.json) -----------------------------
# Установленная сборка не имеет .git (дистрибутив собран `git archive`),
# поэтому панель → «Обновления» не может сравнить её с веткой. Метка хранит
# коммит, ветку и репозиторий: UpdateService без .git идёт в GitHub API и
# накладывает zipball ветки, не трогая config/, data/, logs/ и базы.
$repoCommit = ''
$repoBranch = ''
Push-Location $root
try {
    $repoCommit = (& git rev-parse HEAD 2>$null | Select-Object -First 1)
    $repoBranch = (& git rev-parse --abbrev-ref HEAD 2>$null | Select-Object -First 1)
} catch {
    Write-Info 'git rev-parse не удался — сборка будет без метки версии'
} finally {
    Pop-Location
}
$buildInfoPath = Join-Path $stageDir 'config\build-info.json'
$buildInfoDir = Split-Path $buildInfoPath -Parent
if (-not (Test-Path -LiteralPath $buildInfoDir)) { New-Item -ItemType Directory -Path $buildInfoDir -Force | Out-Null }
$buildInfo = [ordered]@{
    repository = 'oneleft12/Zere'
    branch     = ([string]$repoBranch).Trim()
    commit     = ([string]$repoCommit).Trim()
    version    = $version
    builtAt    = (Get-Date).ToUniversalTime().ToString('o')
}
Write-Utf8NoBom -Path $buildInfoPath -Text ($buildInfo | ConvertTo-Json)
Write-Info ('метка сборки: ' + $buildInfo.commit + ' (' + $buildInfo.branch + ')')


# --- 4. Компиляция ---
if (-not (Test-Path $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }
# VersionInfoVersion: только цифры и точки. Четвёртое поле — номер сборки
# (число коммитов): две сборки одной версии различимы в свойствах файла,
# иначе 1.9.0 от 1.9.0 не отличить.
$fileVersion = ($version -replace '[^0-9.]', '').Trim('.')
if ($fileVersion -eq '') { $fileVersion = '1.9.0' }
$parts = @($fileVersion -split '\.')
while ($parts.Count -lt 3) { $parts += '0' }
$buildNumber = 0
Push-Location $root
try {
    $rev = & git rev-list --count HEAD 2>$null
    if ($LASTEXITCODE -eq 0 -and $rev) { $buildNumber = [int]($rev | Select-Object -First 1) }
} catch {
    Write-Info 'номер сборки недоступен (git rev-list) — четвёртое поле 0'
} finally {
    Pop-Location
}
$fileVersion = (($parts[0..2]) + $buildNumber) -join '.'
Write-Info ('версия ' + $version + ', сборка ' + $buildNumber + ' -> ' + $fileVersion)
Write-Info 'компиляция ISCC...'
& $iscc ("/DStageDir=" + $stageDir) ("/DEdition=" + $Edition) ("/DMyAppVersion=" + $version) ("/DFileVersion=" + $fileVersion) $issPath
$code = $LASTEXITCODE
if ($null -eq $code) { $code = -1 }

# Stage больше не нужен
Remove-Item -LiteralPath $stageDir -Recurse -Force -ErrorAction SilentlyContinue

if ($code -ne 0) {
    Write-Fail2 ('ISCC завершился с ошибкой (код ' + $code + ')')
    exit 1
}

$setup = Join-Path $outputDir 'ZereInstaller.exe'
if (Test-Path $setup) {
    $sizeMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host ''
    Write-Host ('ГОТОВО: ' + $setup + ' (' + $sizeMb + ' МБ)') -ForegroundColor Green
    exit 0
}
Write-Fail2 'Файл установщика не найден в installer\Output'
exit 1
