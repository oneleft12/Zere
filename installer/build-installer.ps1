#Requires -Version 5.1
<#
.SYNOPSIS
    Сборка установщика ZERE — ZereSetup.exe (один exe, без прав администратора).

.DESCRIPTION
    Почему не Inno Setup (см. также build-setup.ps1): на Windows 11 включённый
    Smart App Control (WDAC) блокирует свежесобранный неподписанный Setup.exe —
    «заблокирован политикой Device Guard». Файлы, собранные системным csc.exe
    из .NET Framework, фильтр пропускает (так же запускается zere.exe), поэтому
    установщик собирается им: мастер на WinForms + встроенный архив
    дистрибутива + запуск installer\install.ps1.

    1. Наполняет installer\stage через `git archive HEAD` (только
       отслеживаемые git-файлы: без .git, .venv, bin/obj, zere.db, logs).
    2. Упаковывает stage в payload.zip и встраивает его ресурсом в exe.
    3. Компилирует installer\ZereSetup.cs системным csc.exe.
    Результат: installer\Output\ZereSetup.exe

.PARAMETER WorkingTree
    Архивировать не HEAD, а текущее рабочее дерево (учесть некоммиченные
    изменения, кроме gitignored-файлов). Удобно для отладки установщика.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
    powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -WorkingTree
#>
[CmdletBinding()]
param(
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
$sourcePath = Join-Path $PSScriptRoot 'ZereSetup.cs'
$stageDir = Join-Path $PSScriptRoot 'stage'
$stageZip = Join-Path $PSScriptRoot 'stage.zip'
$payloadZip = Join-Path $PSScriptRoot 'payload.zip'
$outputDir = Join-Path $PSScriptRoot 'Output'
$setupPath = Join-Path $outputDir 'ZereSetup.exe'
$iconPath = Join-Path $root 'assets\zere.ico'

# --- 1. Версия из config/config.json ---
$version = '1.8.0'
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
Write-Host ('=== Сборка установщика ZERE ' + $version + ' (ZereSetup.exe) ===') -ForegroundColor Cyan

# --- 2. csc.exe из .NET Framework ---
$csc = $null
foreach ($candidate in @(
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'))) {
    if (Test-Path -LiteralPath $candidate) { $csc = $candidate; break }
}
if ($null -eq $csc) {
    Write-Fail2 'не найден csc.exe из .NET Framework 4.x (он есть в любой Windows 10/11)'
    exit 2
}
Write-Info ('csc: ' + $csc)

if (-not (Test-Path -LiteralPath $sourcePath)) {
    Write-Fail2 ('нет исходника установщика: ' + $sourcePath)
    exit 2
}

# --- 3. Stage: git-архив ---
if (Test-Path $stageDir) { Remove-Item -LiteralPath $stageDir -Recurse -Force }
if (Test-Path $stageZip) { Remove-Item -LiteralPath $stageZip -Force }
if (Test-Path $payloadZip) { Remove-Item -LiteralPath $payloadZip -Force }
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

if (-not (Test-Path (Join-Path $stageDir 'installer\install.ps1'))) {
    Write-Fail2 'В stage нет installer\install.ps1 — выполняйте сборку из репозитория ZERE.'
    exit 2
}
if (-not (Test-Path (Join-Path $stageDir 'zere.exe'))) {
    Write-Fail2 'В stage нет zere.exe — без приложения установщик бессмыслен (соберите scripts\build-zere-exe.ps1).'
    exit 2
}
$staged = @(Get-ChildItem -LiteralPath $stageDir -Recurse -File).Count
Write-Info ('файлов в stage: ' + $staged)

# --- 4. payload.zip (встраивается в exe) ---
Write-Info 'упаковка payload.zip'
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stageDir,
    $payloadZip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)
$payloadMb = [math]::Round((Get-Item $payloadZip).Length / 1MB, 1)
Write-Info ('payload.zip: ' + $payloadMb + ' МБ')

# --- 5. Версия в исходнике (атрибуты сборки) ---
# Версию задаёт config/config.json; исходник правится во временной копии,
# чтобы файл в репозитории не «замирал» на старой версии.
$parts = @((($version -replace '[^0-9.]', '').Trim('.') -split '\.'))
while ($parts.Count -lt 3) { $parts += '0' }
$fileVersion = ($parts[0..2] -join '.')
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ('zere-setup-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
$tempSource = Join-Path $tempDir 'ZereSetup.cs'
$sourceText = Get-Content -LiteralPath $sourcePath -Raw -Encoding UTF8
$sourceText = $sourceText -replace 'AssemblyVersion\("\d+\.\d+\.\d+\.\d+"\)', ('AssemblyVersion("' + $fileVersion + '.0")')
$sourceText = $sourceText -replace 'AssemblyFileVersion\("\d+\.\d+\.\d+\.\d+"\)', ('AssemblyFileVersion("' + $fileVersion + '.0")')
Write-Utf8NoBom -Path $tempSource -Text $sourceText

# --- 6. Компиляция ---
if (-not (Test-Path $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }

$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$cscArgs = @(
    '/nologo', '/target:winexe', '/platform:anycpu', '/optimize+',
    ('/out:' + $setupPath),
    # Кириллица в строках мастера: csc без явной кодировки читает файл как
    # ANSI и портит русский текст.
    '/codepage:65001',
    '/r:System.dll',
    '/r:System.Core.dll',
    '/r:System.Drawing.dll',
    '/r:System.Windows.Forms.dll',
    '/r:System.IO.Compression.dll',
    '/r:System.IO.Compression.FileSystem.dll',
    ('/resource:' + $payloadZip + ',payload.zip'),
    $tempSource
)
if (Test-Path -LiteralPath $iconPath) {
    $cscArgs = @('/win32icon:' + $iconPath) + $cscArgs
}

Write-Info ('csc -> ' + $setupPath)
& $csc $cscArgs
$code = $LASTEXITCODE

# Временные файлы больше не нужны
Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $stageDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $payloadZip -Force -ErrorAction SilentlyContinue

if ($code -ne 0) {
    Write-Fail2 ('csc завершился с ошибкой (код ' + $code + ')')
    exit 1
}

if (Test-Path $setupPath) {
    $sizeMb = [math]::Round((Get-Item $setupPath).Length / 1MB, 1)
    Write-Host ''
    Write-Host ('ГОТОВО: ' + $setupPath + ' (' + $sizeMb + ' МБ)') -ForegroundColor Green
    Write-Host '   Установка: двойной клик по ZereSetup.exe (права администратора не нужны).' -ForegroundColor Gray
    exit 0
}
Write-Fail2 'Файл установщика не найден в installer\Output'
exit 1
