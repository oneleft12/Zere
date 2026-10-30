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

.PARAMETER CertThumbprint
    Отпечаток сертификата подписи в хранилище (USB-токен, облачный HSM,
    Certum). Подписываются И zere.exe внутри дистрибутива, И ZereSetup.exe —
    иначе Smart App Control блокирует приложение при первом запуске.

.PARAMETER PfxPath
    Файл .pfx с ключом (старые сертификаты, локальные сборки).

.PARAMETER PfxPassword
    Пароль .pfx.

.PARAMETER SelfTestSign
    Подписать самоподписанным сертификатом, чтобы проверить конвейер.
    Windows такую подпись не считает доверенной: для распространения нужен
    сертификат УЦ (docs\SIGNING.md).

.PARAMETER NoOllama
    Сборка «только облачный ключ»: в мастере галочка «Установить без Ollama»
    стоит сразу, тихая установка (/SILENT) тоже идёт без Ollama. Ollama и
    модель (~5 ГБ) не ставятся — ZERE отвечает через API-ключ из панели
    («ИИ»). Обратный ключ /WITHOLLAMA ставит Ollama в любом случае.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
    powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -WorkingTree
    powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -NoOllama
    powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -CertThumbprint ABCD1234
    powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -SelfTestSign
#>
[CmdletBinding()]
param(
    [switch]$WorkingTree,
    [switch]$NoOllama,
    [string]$CertThumbprint = '',
    [string]$PfxPath = '',
    [string]$PfxPassword = '',
    [switch]$SelfTestSign
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
$signScript = Join-Path $PSScriptRoot 'sign.ps1'
$stageDir = Join-Path $PSScriptRoot 'stage'
$stageZip = Join-Path $PSScriptRoot 'stage.zip'
$payloadZip = Join-Path $PSScriptRoot 'payload.zip'
$outputDir = Join-Path $PSScriptRoot 'Output'
$setupPath = Join-Path $outputDir 'ZereSetup.exe'
$iconPath = Join-Path $root 'assets\zere.ico'

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
Write-Host ('=== Сборка установщика ZERE ' + $version + ' (ZereSetup.exe) ===') -ForegroundColor Cyan
if ($NoOllama) {
    Write-Info 'вариант: без Ollama — ZERE работает через облачный ключ (галочка предустановлена)'
}

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
    repository = 'oneleft12/Jarvis'
    branch     = ([string]$repoBranch).Trim()
    commit     = ([string]$repoCommit).Trim()
    version    = $version
    # Какой установщик стоит: standard (с Ollama) или no-ollama (только
    # облачный ключ). Видно в панели и в журналах поддержки.
    variant    = $(if ($NoOllama) { 'no-ollama' } else { 'standard' })
    builtAt    = (Get-Date).ToUniversalTime().ToString('o')
}
Write-Utf8NoBom -Path $buildInfoPath -Text ($buildInfo | ConvertTo-Json)
Write-Info ('метка сборки: ' + $buildInfo.commit + ' (' + $buildInfo.branch + ')')


# --- 3.1. Подпись приложения ДО упаковки -------------------------------------
# zere.exe запускают ярлыки, и Smart App Control проверяет его при запуске:
# подпись установщика без подписи приложения не помогает. Поэтому подписываем
# копию в stage (файл в репозитории не трогаем) — она и уйдёт в payload.
$signingConfigured = ($CertThumbprint -ne '') -or ($PfxPath -ne '') -or $SelfTestSign
if ($signingConfigured) {
    $signTargets = @(Join-Path $stageDir 'zere.exe')
    $speakerInStage = Join-Path $stageDir 'publish\speaker\ZERE.Speaker.exe'
    if (Test-Path -LiteralPath $speakerInStage) { $signTargets += $speakerInStage }

    # Хэш-таблица, а не массив: массивы в PowerShell сплатятся ПОЗИЦИОННО,
    # и «-Files» уехал бы значением первого параметра.
    $signParams = @{ Files = $signTargets }
    if ($SelfTestSign) { $signParams.SelfTest = $true; $signParams.AllowSelfSigned = $true }
    if ($CertThumbprint -ne '') { $signParams.Thumbprint = $CertThumbprint }
    if ($PfxPath -ne '') { $signParams.Pfx = $PfxPath; $signParams.PfxPassword = $PfxPassword }

    & $signScript @signParams
    if ($LASTEXITCODE -ne 0) {
        Write-Fail2 'подпись приложения (zere.exe) не удалась — установщик не собран'
        exit 1
    }
} else {
    Write-Host '   [!]  подпись не настроена: Windows 11 со Smart App Control заблокирует' -ForegroundColor Yellow
    Write-Host '        неподписанный exe. Как включить — docs\SIGNING.md (-CertThumbprint / -SelfTestSign)' -ForegroundColor Yellow
}

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
if ($NoOllama) {
    # Сборка «только облачный ключ»: Options.Parse ставит SkipOllama=true,
    # поэтому галочка в мастере предустановлена, а /SILENT идёт без Ollama.
    # Обратный ключ /WITHOLLAMA снимает это для конкретного запуска.
    $cscArgs = @('/define:ZERE_NO_OLLAMA_DEFAULT') + $cscArgs
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

# --- 7. Подпись установщика --------------------------------------------------
# Ставится последней: подпись покрывает байты файла, и любое изменение после
# неё её ломает. ZereUninstall.exe — копия этого файла, подпись сохраняется.
if ($signingConfigured) {
    $signParams = @{ Files = @($setupPath) }
    if ($SelfTestSign) { $signParams.SelfTest = $true; $signParams.AllowSelfSigned = $true }
    if ($CertThumbprint -ne '') { $signParams.Thumbprint = $CertThumbprint }
    if ($PfxPath -ne '') { $signParams.Pfx = $PfxPath; $signParams.PfxPassword = $PfxPassword }

    & $signScript @signParams
    if ($LASTEXITCODE -ne 0) {
        Write-Fail2 'подпись ZereSetup.exe не удалась — файл оставлен неподписанным, распространять нельзя'
        exit 1
    }
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
