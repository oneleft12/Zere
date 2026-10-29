#Requires -Version 5.1
<#
.SYNOPSIS
    Деинсталлятор ZERE — удаляет установленные установщиком компоненты.

.DESCRIPTION
    По умолчанию удаляет ТОЛЬКО то, что создал установщик:
      - ярлыки (рабочий стол, меню «Пуск»)
      - лаунчер ZERE.bat
      - виртуальное окружение .venv
      - C#-публикацию publish\app
      - манифест installer\install-manifest.json
    Исходный код, git-репозиторий и данные НЕ трогаются.

.PARAMETER Prefix
    Корень установки (по умолчанию — родительская папка скрипта).

.PARAMETER RemoveAssets
    Дополнительно удалить голосовые артефакты:
    ZERE.Voice\Models\*.bin, папку модели GigaAM (sherpa-onnx-*),
    менеджер Python tools\uv.exe (на нём работают ChatTTS и клонирование),
    временные WAV синтеза ChatTTS.
    Git-трекаемые файлы не удаляются.

.PARAMETER PurgeData
    Дополнительно удалить пользовательские данные:
    zere.db (память и история), logs\, backups\, config\panel.token,
    voice\reference.wav (голосовой референс), voice\input\.

.PARAMETER Yes
    Не запрашивать подтверждений.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1
    powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1 -PurgeData -Yes
#>
[CmdletBinding()]
param(
    [string]$Prefix = '',
    [switch]$RemoveAssets,
    [switch]$PurgeData,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Msg) { Write-Host ('' + [char]10 + '== ' + $Msg) -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host ('   [OK] ' + $Msg) -ForegroundColor Green }
function Write-Info([string]$Msg) { Write-Host ('   ' + $Msg) -ForegroundColor Gray }
function Write-Warn2([string]$Msg) { Write-Host ('   [!]  ' + $Msg) -ForegroundColor Yellow }

function Remove-ItemSafe {
    param([string]$Path, [string]$Label)
    if (Test-Path -LiteralPath $Path) {
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force
            Write-Ok ('удалено: ' + $Label)
            return $true
        } catch {
            Write-Warn2 ('не удалось удалить ' + $Label + ': ' + $_.Exception.Message)
            return $false
        }
    }
    Write-Info ('не найдено, пропущено: ' + $Label)
    return $false
}

# --- Корень ---
if ($Prefix -eq '') { $Prefix = Split-Path -Parent $PSScriptRoot }
$Prefix = [System.IO.Path]::GetFullPath($Prefix)

Write-Host ''
Write-Host '=================================================' -ForegroundColor Cyan
Write-Host '   ZERE — деинсталлятор' -ForegroundColor Cyan
Write-Host ('   Корень: ' + $Prefix) -ForegroundColor Gray
Write-Host '=================================================' -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $Prefix 'main.py'))) {
    Write-Warn2 ('В папке нет main.py — похоже, это не корень ZERE: ' + $Prefix)
    exit 2
}

# Манифест (если есть) — для отчёта
$manifestPath = Join-Path $PSScriptRoot 'install-manifest.json'
if (Test-Path $manifestPath) {
    try {
        $mf = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Info ('Установлено: ' + $mf.installedAt + ', редакция ' + $mf.edition + ', модель ' + $mf.model)
    } catch {
        Write-Info 'Манифест повреждён — игнорируется'
    }
}

# --- План ---
Write-Step 'Что будет удалено'
$plan = @(
    'Ярлыки: рабочий стол (ZERE.lnk, ZERE - panel.url) и меню «Пуск»\ZERE',
    'Приложение zere.exe',
    'Лаунчер ZERE.bat',
    'Виртуальное окружение .venv',
    'C#-публикация publish\app'
)
if ($RemoveAssets) {
    $plan += 'Голосовые артефакты: ZERE.Voice\Models\*.bin и sherpa-onnx-*, tools\uv.exe, ZERE.Voice\ChatTts\output_*.wav'
    $plan += 'Наследие Piper: бинарники и голоса в ZERE.Voice\Piper (движок заменён на ChatTTS)'
}
if ($PurgeData) {
    $plan += 'Пользовательские данные: zere.db, logs\, backups\, config\panel.token, voice\reference.wav, voice\input\'
}
$plan += 'Исходный код и git-репозиторий НЕ удаляются'
foreach ($p in $plan) { Write-Host ('   - ' + $p) -ForegroundColor White }

if (-not $Yes) {
    $answer = Read-Host 'Продолжить удаление? [y/N]'
    $answer = $answer.Trim()
    if ($answer -notmatch '(?i)^(y|д|да|yes)$') {
        Write-Warn2 'Удаление отменено.'
        exit 0
    }
}

trap {
    Write-Warn2 ('Фатальная ошибка деинсталлятора: ' + $_.Exception.Message)
    exit 2
}

# --- 1. Ярлыки ---
Write-Step 'Ярлыки'
$desktop = [Environment]::GetFolderPath('Desktop')
$startMenu = [Environment]::GetFolderPath('StartMenu')
$null = Remove-ItemSafe -Path (Join-Path $desktop 'ZERE.lnk') -Label 'ярлык на рабочем столе'
$null = Remove-ItemSafe -Path (Join-Path $desktop 'ZERE - panel.url') -Label 'ярлык панели на рабочем столе'
$null = Remove-ItemSafe -Path (Join-Path $startMenu 'Programs\ZERE') -Label 'папка в меню «Пуск»'

# --- 2. Лаунчер ---
Write-Step 'Лаунчер'
$null = Remove-ItemSafe -Path (Join-Path $Prefix 'ZERE.bat') -Label 'ZERE.bat'
$null = Remove-ItemSafe -Path (Join-Path $Prefix 'zere.exe') -Label 'zere.exe'

# --- 3. Окружение и публикация ---
Write-Step 'Окружение и сборки'
$null = Remove-ItemSafe -Path (Join-Path $Prefix '.venv') -Label '.venv'
$null = Remove-ItemSafe -Path (Join-Path $Prefix 'publish\app') -Label 'publish\app'
$pubDir = Join-Path $Prefix 'publish'
if ((Test-Path $pubDir) -and -not (Get-ChildItem $pubDir -Force | Select-Object -First 1)) {
    Remove-Item -LiteralPath $pubDir -Force -ErrorAction SilentlyContinue
}
$null = Remove-ItemSafe -Path $manifestPath -Label 'install-manifest.json'

# --- 4. Голосовые артефакты ---
if ($RemoveAssets) {
    Write-Step 'Голосовые артефакты'
    $modelsDir = Join-Path $Prefix 'ZERE.Voice\Models'
    if (Test-Path $modelsDir) {
        Get-ChildItem -LiteralPath $modelsDir -Filter '*.bin' -File -ErrorAction SilentlyContinue | ForEach-Object {
            try { Remove-Item -LiteralPath $_.FullName -Force; Write-Ok ('удалено: ' + $_.Name) }
            catch { Write-Warn2 ('не удалось удалить ' + $_.Name) }
        }
        # Пакет модели GigaAM (основной STT) — целиком папкой
        foreach ($gigaam in @('sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16')) {
            $p = Join-Path $modelsDir $gigaam
            if (Test-Path $p) { $null = Remove-ItemSafe -Path $p -Label ('модель GigaAM ' + $gigaam) }
        }
    }
    # Наследие Piper: движок заменён на ChatTTS (код и модели удалены из
    # репозитория), но у кого Piper стоял раньше — бинарники остались в
    # рабочей копии. Убираем их по флагу -RemoveAssets.
    $legacyPiperDir = Join-Path $Prefix 'ZERE.Voice\Piper'
    if (Test-Path $legacyPiperDir) {
        foreach ($pattern in @('*.exe', '*.dll', '*.onnx')) {
            Get-ChildItem -LiteralPath $legacyPiperDir -Filter $pattern -File -ErrorAction SilentlyContinue | ForEach-Object {
                try { Remove-Item -LiteralPath $_.FullName -Force; Write-Ok ('удалено (наследие Piper): ' + $_.Name) }
                catch { Write-Warn2 ('не удалось удалить ' + $_.Name) }
            }
        }
        foreach ($dirName in @('espeak-ng-data', 'pkgconfig')) {
            $p = Join-Path $legacyPiperDir $dirName
            if (Test-Path $p) { $null = Remove-ItemSafe -Path $p -Label ('ZERE.Voice\Piper\' + $dirName) }
        }
    }

    # Менеджер Python uv (нужен ChatTTS и клонированию голоса) — это скачанный
    # установщиком бинарник, не исходник: удаляем вместе с голосовыми артефактами.
    $toolsDir = Join-Path $Prefix 'tools'
    foreach ($tool in @('uv.exe', 'uvx.exe', 'uvw.exe')) {
        $p = Join-Path $toolsDir $tool
        if (Test-Path $p) { $null = Remove-ItemSafe -Path $p -Label ('tools\' + $tool) }
    }

    # Временные WAV синтеза ChatTTS (создаются и удаляются на лету)
    $chatTtsDir = Join-Path $Prefix 'ZERE.Voice\ChatTts'
    if (Test-Path $chatTtsDir) {
        Get-ChildItem -LiteralPath $chatTtsDir -Filter 'output_*.wav' -File -ErrorAction SilentlyContinue | ForEach-Object {
            try { Remove-Item -LiteralPath $_.FullName -Force; Write-Ok ('удалено: ' + $_.Name) }
            catch { Write-Warn2 ('не удалось удалить ' + $_.Name) }
        }
    }
}

# --- 5. Пользовательские данные ---
if ($PurgeData) {
    Write-Step 'Пользовательские данные'
    $null = Remove-ItemSafe -Path (Join-Path $Prefix 'zere.db') -Label 'zere.db (память и история)'
    $null = Remove-ItemSafe -Path (Join-Path $Prefix 'logs') -Label 'logs\'
    $null = Remove-ItemSafe -Path (Join-Path $Prefix 'backups') -Label 'backups\'
    $null = Remove-ItemSafe -Path (Join-Path $Prefix 'config\panel.token') -Label 'config\panel.token'
    $null = Remove-ItemSafe -Path (Join-Path $Prefix 'voice\reference.wav') -Label 'voice\reference.wav'
    $null = Remove-ItemSafe -Path (Join-Path $Prefix 'voice\input') -Label 'voice\input\'
}

Write-Host ''
Write-Host 'Удаление завершено.' -ForegroundColor Green
Write-Info 'Не удаляются (и удаляются только вручную): Python, Ollama, модель Ollama, winget-пакеты.'
Write-Info 'Модель Ollama удалить: ollama rm <имя_модели>'
exit 0
