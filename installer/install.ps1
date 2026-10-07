#Requires -Version 5.1
<#
.SYNOPSIS
    Установщик ZERE — подготовка окружения на Windows.

.DESCRIPTION
    Выполняет полный цикл установки:
      1. Проверка/установка Python 3.12+ (winget) и создание виртуального окружения .venv
      2. Установка зависимостей из requirements.txt
      3. Установка/запуск Ollama и загрузка модели из config/config.json (по умолчанию qwen3.5:2b)
      4. Загрузка голосовых артефактов: GigaAM-v3 (основной STT), Whisper ggml-base.bin,
         uv (менеджер Python для ChatTTS и клонирования голоса)
         (все скачивания проверяются по SHA-256)
      5. Опционально: .NET SDK 10 + dotnet publish C#-версии (-Edition dotnet|both)
      6. Сборка web-панели (npm), если отсутствует panel/dist
      7. Генерация недостающих config/*.json, лаунчера ZERE.bat, ярлыков, манифеста
      8. Финальный smoke-тест (compileall)

.PARAMETER Prefix
    Корень установки. По умолчанию — родительская папка скрипта (репозиторий).
    Inno Setup передаёт сюда каталог назначения.

.PARAMETER Edition
    python (по умолчанию) | dotnet | both.

.PARAMETER Model
    Модель Ollama. По умолчанию берётся из config/config.json.

.PARAMETER CheckOnly
    Только проверка, без изменений (dry-run).

.PARAMETER Yes
    Не запрашивать подтверждений (для Inno Setup и автоматизации).

.PARAMETER NoLaunch
    Не предлагать запуск ZERE в конце установки.

.PARAMETER SkipOllama
    Не устанавливать/проверять Ollama и модель.

.PARAMETER SkipVoice
    Не скачивать голосовые артефакты (GigaAM, Whisper, uv).

.PARAMETER SkipShortcuts
    Не создавать ярлыки на рабочем столе и в меню «Пуск».

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\install.ps1
    powershell -ExecutionPolicy Bypass -File installer\install.ps1 -CheckOnly
    powershell -ExecutionPolicy Bypass -File installer\install.ps1 -Edition both -Yes -NoLaunch
#>
[CmdletBinding()]
param(
    [string]$Prefix = '',
    [ValidateSet('python', 'dotnet', 'both')]
    [string]$Edition = 'python',
    [string]$Model = '',
    [switch]$SkipOllama,
    [switch]$SkipVoice,
    [switch]$SkipShortcuts,
    [switch]$CheckOnly,
    [switch]$Yes,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Константы: артефакты для скачивания + контрольные SHA-256
# ---------------------------------------------------------------------------
$Artifacts = @{
    GigaAm        = @{
        Url    = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16.tar.bz2'
        Sha256 = 'f9620a0099019c6afcee26525ef9ed3297fa50dd5691c1902af0c948fc1a470b'
        Size   = 170197019
        Label  = 'модель GigaAM-v3 для распознавания речи (~163 МБ)'
    }
    Whisper      = @{
        Url    = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin'
        Sha256 = '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe'
        Size   = 147951465
        Label  = 'модель Whisper ggml-base.bin (~141 МБ)'
    }
    Uv           = @{
        Url    = 'https://github.com/astral-sh/uv/releases/download/0.12.23/uv-x86_64-pc-windows-msvc.zip'
        Sha256 = '75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90'
        Size   = 18043715
        Label  = 'менеджер Python uv (~18 МБ; нужен для ChatTTS и клонирования)'
    }
}

$DefaultConfigJson = @'
{
  "version": "1.8.0",
  "assistantName": "ZERE",
  "language": "ru",
  "model": "qwen3.5:2b",
  "voiceEnabled": true,
  "voiceVolume": 0.5,
  "autoMemory": true,
  "ollamaTimeoutMinutes": 10,
  "ttsEngine": "chattts",
  "sttEngine": "gigaam",
  "voiceReferencePath": "",
  "llmKeepAlive": -1,
  "llmMaxTokens": 96,
  "llmTimeoutSeconds": 60
}
'@

$DefaultPluginsJson = @'
{
  "ActivePersonalityId": "personality",
  "PluginSettings": {}
}
'@

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# ---------------------------------------------------------------------------
# Консольные помощники
# ---------------------------------------------------------------------------
function Write-Step([string]$Msg) { Write-Host ('' + [char]10 + '== ' + $Msg) -ForegroundColor Cyan }
function Write-Ok([string]$Msg)   { Write-Host ('   [OK] ' + $Msg) -ForegroundColor Green }
function Write-Warn2([string]$Msg) { Write-Host ('   [!]  ' + $Msg) -ForegroundColor Yellow }
function Write-Fail2([string]$Msg) { Write-Host ('   [X]  ' + $Msg) -ForegroundColor Red }
function Write-Info([string]$Msg) { Write-Host ('   ' + $Msg) -ForegroundColor Gray }

$script:Results = New-Object System.Collections.ArrayList

function Add-Result {
    param(
        [string]$Name,
        [ValidateSet('ok', 'skip', 'warn', 'fail')][string]$Status,
        [string]$Detail = '',
        [switch]$Critical
    )
    $null = $script:Results.Add([pscustomobject]@{
        Name     = $Name
        Status   = $Status
        Detail   = $Detail
        Critical = [bool]$Critical
    })
}

function Finish {
    param(
        [bool]$Ok,
        [string]$Name,
        [string]$OkDetail = 'готово',
        [string]$FailDetail = 'ошибка',
        [switch]$Critical
    )
    if ($Ok) {
        Write-Ok $OkDetail
        Add-Result -Name $Name -Status ok -Detail $OkDetail
    } else {
        Write-Fail2 $FailDetail
        Add-Result -Name $Name -Status fail -Detail $FailDetail -Critical:$Critical
    }
}

function Skip-Result {
    param([string]$Name, [string]$Detail = 'уже установлено')
    Write-Info $Detail
    Add-Result -Name $Name -Status skip -Detail $Detail
}

# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------
function Invoke-Native {
    <# Запуск внешней команды: не даёт EAP=Stop превратить stderr в исключение. #>
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$Stream
    )
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Stream) {
            # Вывод на консоль через Out-Host: иначе строки попадают в результат
            # функции (pipeline output) и ломают типизацию у вызывающего кода.
            & $FilePath @Arguments | Out-Host
            $code = $LASTEXITCODE
            if ($null -eq $code) { $code = -1 }
            return @{ Output = ''; ExitCode = $code }
        }
        $out = & $FilePath @Arguments 2>&1 | ForEach-Object { $_.ToString() }
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = -1 }
        return @{ Output = ($out -join [Environment]::NewLine); ExitCode = $code }
    } catch {
        return @{ Output = ('EXCEPTION: ' + $_.Exception.Message); ExitCode = -1 }
    } finally {
        $ErrorActionPreference = $oldEap
    }
}

function Update-SessionPath {
    # После winget-установок PATH в реестре обновлён, в текущей сессии — нет.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $parts = @()
    if ($machine) { $parts += $machine }
    if ($user) { $parts += $user }
    if ($parts.Count -gt 0) {
        $env:Path = ($parts -join ';') + ';' + $env:Path
    }
}

function Get-Winget {
    $c = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
    if ($null -ne $c) { return $c.Source }
    $p = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\winget.exe'
    if (Test-Path $p) { return $p }
    return $null
}

function Invoke-Winget {
    param([string[]]$Arguments)
    $winget = Get-Winget
    if ($null -eq $winget) { return @{ Output = 'winget не найден'; ExitCode = -1 } }
    $all = $Arguments + @('--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity')
    return Invoke-Native -FilePath $winget -Arguments $all
}

function Test-TcpPort {
    param([int]$Port = 11434)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $ok = $client.Connect('127.0.0.1', $Port)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-FileIntegrity {
    param([string]$Path, [long]$Size = 0, [string]$Sha256 = '')
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path
    if ($item.PSIsContainer) { return $false }
    if ($Size -gt 0 -and $item.Length -ne $Size) { return $false }
    if ($Sha256 -ne '') {
        $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
        if ($hash -ine $Sha256) { return $false }
    }
    return $true
}

function Get-Artifact {
    <# Скачивание файла с проверкой размера и SHA-256. Битый файл удаляется. #>
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Dest,
        [Parameter(Mandatory = $true)][string]$Sha256,
        [long]$Size = 0
    )
    if (Test-FileIntegrity -Path $Dest -Size $Size -Sha256 $Sha256) { return $true }

    $dir = Split-Path -Parent $Dest
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    $tmp = $Dest + '.download'
    if (Test-Path $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }

    Write-Info ('скачивание: ' + $Url)
    $code = -1
    $curl = Get-Command 'curl.exe' -ErrorAction SilentlyContinue
    if ($null -ne $curl) {
        $r = Invoke-Native -FilePath $curl.Source -Arguments @('-L', '--fail', '--retry', '3', '--retry-delay', '3', '-o', $tmp, $Url)
        $code = $r.ExitCode
    } else {
        try {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing
            $code = 0
        } catch {
            $code = -1
            Write-Warn2 ('ошибка скачивания: ' + $_.Exception.Message)
        } finally {
            $ProgressPreference = 'Continue'
        }
    }

    if ($code -ne 0 -or -not (Test-Path $tmp)) {
        if (Test-Path $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
        return $false
    }
    if (-not (Test-FileIntegrity -Path $tmp -Size $Size -Sha256 $Sha256)) {
        Write-Warn2 'файл не прошёл проверку SHA-256 — удалён, скачивание повторено не будет'
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        return $false
    }
    Move-Item -LiteralPath $tmp -Destination $Dest -Force
    return $true
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $dir = Split-Path -Parent $Path
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8NoBom)
}

# ---------------------------------------------------------------------------
# Состояние компонентов (используется и в -CheckOnly, и в установке)
# ---------------------------------------------------------------------------
function Get-PythonCandidates {
    $found = @()
    $py = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        $r = Invoke-Native -FilePath $py.Source -Arguments @('-0p')
        foreach ($line in ($r.Output -split "`r?`n")) {
            if ($line -match '([A-Za-z]:[\\/].*?python\.exe)\s*$') {
                $found += $Matches[1]
            }
        }
    }
    foreach ($name in @('python.exe', 'python3.exe')) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $c) { $found += $c.Source }
    }
    return @($found | Select-Object -Unique)
}

function Get-PythonVersionOf {
    param([string]$Exe)
    # Важно: без двойных кавычек внутри аргумента — Windows PowerShell 5.1
    # некорректно передаёт их нативным командам (аргумент искажается).
    $r = Invoke-Native -FilePath $Exe -Arguments @('-c', 'import sys;print(''%d.%d'' % sys.version_info[:2])')
    $txt = ($r.Output -split "`r?`n" | Select-Object -Last 1).Trim()
    if ($r.ExitCode -eq 0 -and $txt -match '^\d+\.\d+$') {
        try { return [version]$txt } catch { return $null }
    }
    return $null
}

function Get-PythonState {
    $res = @{ Ok = $false; Exe = $null; Version = $null; Detail = 'Python 3.12+ не найден' }
    $best = $null; $bestVer = $null
    foreach ($c in (Get-PythonCandidates)) {
        $v = Get-PythonVersionOf -Exe $c
        if ($null -ne $v -and ($null -eq $bestVer -or $v -gt $bestVer)) {
            $best = $c; $bestVer = $v
        }
    }
    $min = New-Object version '3.12'
    if ($null -ne $bestVer -and $bestVer -ge $min) {
        $res.Ok = $true
        $res.Exe = $best
        $res.Version = $bestVer
        $res.Detail = ('Python {0}: {1}' -f $bestVer, $best)
    } elseif ($null -ne $bestVer) {
        $res.Detail = ('найден Python {0}, требуется 3.12+' -f $bestVer)
    }
    return $res
}

function Get-VenvState {
    param([string]$VenvPy)
    $res = @{ Venv = $false; Deps = $false; Detail = 'виртуальное окружение не создано' }
    if (Test-Path -LiteralPath $VenvPy) {
        $res.Venv = $true
        $r = Invoke-Native -FilePath $VenvPy -Arguments @('-m', 'pip', 'show', 'faster-whisper')
        # sherpa-onnx — рантайм основного STT (GigaAM), см. requirements.txt
        $r2 = Invoke-Native -FilePath $VenvPy -Arguments @('-m', 'pip', 'show', 'sherpa-onnx')
        if (($r.ExitCode -eq 0) -and ($r2.ExitCode -eq 0)) {
            $res.Deps = $true
            $res.Detail = '.venv готов, зависимости установлены'
        } else {
            $res.Detail = '.venv создан, зависимости не установлены'
        }
    }
    return $res
}

function Get-OllamaExe {
    $c = Get-Command 'ollama.exe' -ErrorAction SilentlyContinue
    if ($null -ne $c) { return $c.Source }
    $p = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $p) { return $p }
    $p2 = Join-Path $env:ProgramFiles 'Ollama\ollama.exe'
    if (Test-Path $p2) { return $p2 }
    return $null
}

function Get-OllamaState {
    param([string]$WantedModel)
    $res = @{ Installed = $false; Running = $false; Model = $false; Exe = $null; Detail = 'Ollama не установлен' }
    $exe = Get-OllamaExe
    if ($null -eq $exe) { return $res }
    $res.Installed = $true
    $res.Exe = $exe
    $res.Running = Test-TcpPort -Port 11434
    if ($res.Running -and $WantedModel -ne '') {
        $r = Invoke-Native -FilePath $exe -Arguments @('list')
        if ($r.ExitCode -eq 0) {
            foreach ($line in ($r.Output -split "`r?`n")) {
                if ($line -match ('^\s*' + [regex]::Escape($WantedModel) + '\s')) { $res.Model = $true; break }
            }
        }
        if ($res.Model) {
            $res.Detail = 'Ollama запущен, модель ' + $WantedModel + ' загружена'
        } else {
            $res.Detail = 'Ollama запущен, модель ' + $WantedModel + ' не загружена'
        }
    } elseif ($res.Running) {
        $res.Detail = 'Ollama запущен'
    } else {
        $res.Detail = 'Ollama установлен, сервер не запущен'
    }
    return $res
}

function Get-DotnetExe {
    $c = Get-Command 'dotnet.exe' -ErrorAction SilentlyContinue
    if ($null -ne $c) { return $c.Source }
    $p = Join-Path $env:ProgramFiles 'dotnet\dotnet.exe'
    if (Test-Path $p) { return $p }
    return $null
}

function Test-DotnetSdk10 {
    param([string]$Exe)
    $r = Invoke-Native -FilePath $Exe -Arguments @('--list-sdks')
    foreach ($line in ($r.Output -split "`r?`n")) {
        if ($line -match '^10\.') { return $true }
    }
    return $false
}

# ---------------------------------------------------------------------------
# Шаги установки
# ---------------------------------------------------------------------------
function Install-PythonEngine {
    $ids = @('Python.Python.3.14', 'Python.Python.3.13', 'Python.Python.3.12')
    foreach ($id in $ids) {
        Write-Info ('winget install ' + $id + ' (пользовательская область, без UAC если возможно)')
        $r = Invoke-Winget -Arguments @('install', '--id', $id, '-e', '--scope', 'user')
        if ($r.ExitCode -ne 0) {
            Write-Info 'повтор без ограничения области установки (возможен запрос UAC)'
            $r = Invoke-Winget -Arguments @('install', '--id', $id, '-e')
        }
        if ($r.ExitCode -ne 0) {
            Write-Warn2 ('winget не смог установить ' + $id)
            continue
        }
        Update-SessionPath
        $st = Get-PythonState
        if ($st.Ok) { return $st }
    }
    return $null
}

function Install-Venv {
    param([string]$VenvDir, [string]$VenvPy, [string]$PythonExe, [string]$Root)
    if (-not (Test-Path -LiteralPath $VenvPy)) {
        Write-Info ('создание окружения: ' + $VenvDir)
        $r = Invoke-Native -FilePath $PythonExe -Arguments @('-m', 'venv', $VenvDir)
        if ($r.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $VenvPy)) {
            Write-Fail2 ('не удалось создать .venv: ' + $r.Output)
            return $false
        }
    }
    Write-Info 'обновление pip'
    $null = Invoke-Native -FilePath $VenvPy -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', '--disable-pip-version-check', '-q')
    Write-Info 'установка зависимостей из requirements.txt (может занять несколько минут)'
    Push-Location $Root
    try {
        & $VenvPy -m pip install -r (Join-Path $Root 'requirements.txt') --disable-pip-version-check | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($null -eq $code) { $code = -1 }
    return ($code -eq 0)
}

function Install-OllamaEngine {
    Write-Info 'winget install Ollama.Ollama'
    $r = Invoke-Winget -Arguments @('install', '--id', 'Ollama.Ollama', '-e')
    Update-SessionPath
    $exe = Get-OllamaExe
    if ($null -eq $exe) { return $null }
    return $exe
}

function Start-OllamaServer {
    param([string]$Exe)
    if (Test-TcpPort -Port 11434) { return $true }
    Write-Info 'запуск сервера Ollama (ollama serve)'
    Start-Process -FilePath $Exe -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-TcpPort -Port 11434) { return $true }
    }
    return $false
}

function Install-OllamaModel {
    param([string]$Exe, [string]$WantedModel)
    Write-Info ('ollama pull ' + $WantedModel + ' (загрузка модели, нужен интернет)')
    $r = Invoke-Native -FilePath $Exe -Arguments @('pull', $WantedModel) -Stream
    return ($r.ExitCode -eq 0)
}

function Install-VoiceAssets {
    param([string]$Root)
    $modelsDir = Join-Path $Root 'ZERE.Voice\Models'
    $toolsDir = Join-Path $Root 'tools'
    $ok = $true

    # 1. Whisper
    $whisperDest = Join-Path $modelsDir 'ggml-base.bin'
    if (Test-FileIntegrity -Path $whisperDest -Size $Artifacts.Whisper.Size -Sha256 $Artifacts.Whisper.Sha256) {
        Write-Info 'Whisper ggml-base.bin уже на месте (SHA-256 совпал)'
    } else {
        Write-Info $Artifacts.Whisper.Label
        if (-not (Get-Artifact -Url $Artifacts.Whisper.Url -Dest $whisperDest -Sha256 $Artifacts.Whisper.Sha256 -Size $Artifacts.Whisper.Size)) {
            Write-Fail2 'не удалось скачать/проверить модель Whisper'
            $ok = $false
        }
    }

    # 1b. GigaAM-v3 — основной STT (отчёт docs/STT_ENGINE_RESEARCH.md, §5):
    # архив tar.bz2 распаковывается tar.exe (есть в Windows 10 1803+).
    $gigaamDirName = 'sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16'
    $gigaamDir = Join-Path $modelsDir $gigaamDirName
    $gigaamReady = (Test-Path -LiteralPath (Join-Path $gigaamDir 'encoder.int8.onnx')) -and
                   (Test-Path -LiteralPath (Join-Path $gigaamDir 'tokens.txt'))
    if ($gigaamReady) {
        Write-Info 'модель GigaAM уже на месте'
    } else {
        Write-Info $Artifacts.GigaAm.Label
        $gzPath = Join-Path $env:TEMP 'zere-installer\gigaam.tar.bz2'
        if (-not (Get-Artifact -Url $Artifacts.GigaAm.Url -Dest $gzPath -Sha256 $Artifacts.GigaAm.Sha256 -Size $Artifacts.GigaAm.Size)) {
            Write-Fail2 'не удалось скачать модель GigaAM (голос уйдёт на Whisper)'
            $ok = $false
        } else {
            try {
                $tar = Get-Command 'tar.exe' -ErrorAction SilentlyContinue
                if ($null -eq $tar) { $tar = Get-Command 'tar' -ErrorAction SilentlyContinue }
                if ($null -eq $tar) { throw 'tar не найден (нужен Windows 10 1803+)' }
                & $tar.Source -xjf $gzPath -C $modelsDir
                if ($LASTEXITCODE -ne 0) { throw ('tar: код ' + $LASTEXITCODE) }
                Write-Ok 'модель GigaAM распакована в ZERE.Voice\Models'
            } catch {
                Write-Fail2 ('ошибка распаковки GigaAM: ' + $_.Exception.Message)
                $ok = $false
            } finally {
                Remove-Item -LiteralPath $gzPath -Force -ErrorAction SilentlyContinue
            }
        }
    }

    # 2. uv — менеджер Python: на нём работают ChatTTS (TTS-движок) и
    # клонирование голоса (xVibePocketTTS). Отдельного «архива движка TTS»
    # больше нет: ChatTTS uv скачивает сам при первом синтезе (~2–3 ГБ с torch).
    $uvExe = Join-Path $toolsDir 'uv.exe'
    if (Test-Path -LiteralPath $uvExe) {
        Write-Info 'uv уже установлен'
    } else {
        Write-Info $Artifacts.Uv.Label
        $zipPath = Join-Path $env:TEMP 'zere-installer\uv-windows.zip'
        if (-not (Get-Artifact -Url $Artifacts.Uv.Url -Dest $zipPath -Sha256 $Artifacts.Uv.Sha256 -Size $Artifacts.Uv.Size)) {
            Write-Fail2 'не удалось скачать/проверить архив uv'
            $ok = $false
        } else {
            try {
                if (-not (Test-Path -LiteralPath $toolsDir)) {
                    New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
                }
                Expand-Archive -LiteralPath $zipPath -DestinationPath $toolsDir -Force
                Write-Ok 'uv распакован в tools\'
            } catch {
                Write-Fail2 ('ошибка распаковки uv: ' + $_.Exception.Message)
                $ok = $false
            }
        }
    }
    return $ok
}

function Publish-DotnetEdition {
    param([string]$Root, [string]$DotnetExe)
    $proj = Join-Path $Root 'ZERE.App\ZERE.App.csproj'
    if (-not (Test-Path $proj)) {
        Write-Fail2 ('проект не найден: ' + $proj)
        return $false
    }
    $out = Join-Path $Root 'publish\app'
    Write-Info ('dotnet publish -> ' + $out)
    Push-Location $Root
    try {
        & $DotnetExe publish $proj -c Release -o $out --nologo | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($null -eq $code) { $code = -1 }
    if ($code -ne 0) { return $false }
    return (Test-Path (Join-Path $out 'ZERE.App.exe'))
}

function Publish-Speaker {
    param([string]$Root, [string]$DotnetExe)
    $proj = Join-Path $Root 'ZERE.Speaker\ZERE.Speaker.csproj'
    if (-not (Test-Path $proj)) {
        Write-Fail2 ('проект не найден: ' + $proj)
        return $false
    }
    $out = Join-Path $Root 'publish\speaker'
    Write-Info ('dotnet publish хелпера озвучки -> ' + $out)
    Push-Location $Root
    try {
        & $DotnetExe publish $proj -c Release -o $out --nologo | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($null -eq $code) { $code = -1 }
    if ($code -ne 0) { return $false }
    return (Test-Path (Join-Path $out 'ZERE.Speaker.exe'))
}

function Build-Panel {
    param([string]$Root)
    $dist = Join-Path $Root 'panel\dist\index.html'
    if (Test-Path $dist) { return $true }
    $npm = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
    if ($null -eq $npm) { $npm = Get-Command 'npm' -ErrorAction SilentlyContinue }
    if ($null -eq $npm) { return $false }
    Write-Info 'сборка web-панели: npm install + npm run build'
    Push-Location (Join-Path $Root 'panel')
    try {
        & $npm.Source install --no-audit --no-fund | Out-Host
        if ($LASTEXITCODE -ne 0) { return $false }
        & $npm.Source run build | Out-Host
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($null -eq $code) { $code = -1 }
    return ($code -eq 0 -and (Test-Path $dist))
}

function Ensure-Config {
    param([string]$Root)
    $cfg = Join-Path $Root 'config\config.json'
    $plugins = Join-Path $Root 'config\plugins.json'
    $made = @()
    if (-not (Test-Path $cfg)) {
        Write-Utf8NoBom -Path $cfg -Text ($DefaultConfigJson + "`n")
        $made += 'config\config.json'
    }
    if (-not (Test-Path $plugins)) {
        Write-Utf8NoBom -Path $plugins -Text ($DefaultPluginsJson + "`n")
        $made += 'config\plugins.json'
    }
    if ($made.Count -gt 0) {
        Write-Info ('создано: ' + ($made -join ', '))
        return $true
    }
    return $false
}

function Install-Launcher {
    param([string]$Root)
    $src = Join-Path $PSScriptRoot 'ZereLauncher.bat'
    $dst = Join-Path $Root 'ZERE.bat'
    if (-not (Test-Path $src)) {
        Write-Fail2 ('не найден шаблон лаунчера: ' + $src)
        return $false
    }
    Copy-Item -LiteralPath $src -Destination $dst -Force
    return $true
}

function New-Shortcuts {
    param([string]$Root)
    $bat = Join-Path $Root 'ZERE.bat'
    if (-not (Test-Path $bat)) { return $false }
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath('Desktop')
    $startMenu = [Environment]::GetFolderPath('StartMenu')
    $smDir = Join-Path $startMenu 'Programs\ZERE'
    New-Item -ItemType Directory -Path $smDir -Force | Out-Null

    foreach ($dir in @($desktop, $smDir)) {
        $lnk = $shell.CreateShortcut((Join-Path $dir 'ZERE.lnk'))
        $lnk.TargetPath = $bat
        $lnk.WorkingDirectory = $Root
        $lnk.Description = 'Персональный AI-ассистент ZERE'
        $lnk.Save()
    }

    $panelUrl = 'http://127.0.0.1:8080'
    $urlText = "[InternetShortcut]`r`nURL=$panelUrl`r`n"
    [System.IO.File]::WriteAllText((Join-Path $desktop 'ZERE - panel.url'), $urlText, $Utf8NoBom)
    [System.IO.File]::WriteAllText((Join-Path $smDir 'ZERE - panel.url'), $urlText, $Utf8NoBom)
    return $true
}

function Write-InstallManifest {
    param([string]$Root, [string]$PythonExe)
    $manifest = [pscustomobject]@{
        installedAt = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
        prefix      = $Root
        edition     = $Edition
        model       = $Model
        python      = $PythonExe
        venv        = (Test-Path (Join-Path $Root '.venv\Scripts\python.exe'))
        launcher    = (Test-Path (Join-Path $Root 'ZERE.bat'))
        shortcuts   = @(
            (Join-Path ([Environment]::GetFolderPath('Desktop')) 'ZERE.lnk'),
            (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\ZERE')
        )
    }
    $json = $manifest | ConvertTo-Json -Depth 4
    Write-Utf8NoBom -Path (Join-Path $PSScriptRoot 'install-manifest.json') -Text ($json + "`n")
    return $true
}

function Invoke-SmokeTest {
    param([string]$VenvPy, [string]$Root)
    if (-not (Test-Path $VenvPy)) { return $false }
    Write-Info 'python -m compileall main.py zere'
    Push-Location $Root
    try {
        $r = Invoke-Native -FilePath $VenvPy -Arguments @('-m', 'compileall', '-q', 'main.py', 'zere')
    } finally {
        Pop-Location
    }
    return ($r.ExitCode -eq 0)
}

function Show-Report {
    Write-Host ''
    Write-Host '================ ИТОГИ ================' -ForegroundColor Cyan
    foreach ($r in $script:Results) {
        $icon = '[  ?  ]'
        $color = 'White'
        switch ($r.Status) {
            'ok'   { $icon = '[ OK ]'; $color = 'Green' }
            'skip' { $icon = '[SKIP]'; $color = 'DarkGray' }
            'warn' { $icon = '[WARN]'; $color = 'Yellow' }
            'fail' { $icon = '[FAIL]'; $color = 'Red' }
        }
        $line = ('{0} {1}' -f $icon, $r.Name)
        if ($r.Detail) { $line += (' — ' + $r.Detail) }
        Write-Host $line -ForegroundColor $color
    }
    Write-Host '=======================================' -ForegroundColor Cyan
}

trap {
    Write-Fail2 ('Фатальная ошибка установщика: ' + $_.Exception.Message)
    Show-Report
    exit 2
}

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
$startTime = Get-Date

if ($Prefix -eq '') {
    $Prefix = Split-Path -Parent $PSScriptRoot
}
try {
    $Prefix = [System.IO.Path]::GetFullPath($Prefix)
} catch {
    Write-Fail2 ('Некорректный путь установки: ' + $Prefix)
    exit 2
}
if (-not (Test-Path (Join-Path $Prefix 'main.py'))) {
    Write-Fail2 ('В папке нет main.py — это не корень ZERE: ' + $Prefix)
    exit 2
}

$venvDir = Join-Path $Prefix '.venv'
$venvPy = Join-Path $venvDir 'Scripts\python.exe'

# Модель из конфигурации (если не задана явно)
$cfgPath = Join-Path $Prefix 'config\config.json'
if ($Model -eq '' -and (Test-Path $cfgPath)) {
    try {
        $cfgObj = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfgObj.model) { $Model = [string]$cfgObj.model }
    } catch {
        Write-Warn2 ('config/config.json не разбирается: ' + $_.Exception.Message)
    }
}
if ($Model -eq '') { $Model = 'qwen3.5:2b' }

Write-Host ''
Write-Host '=================================================' -ForegroundColor Cyan
Write-Host '   ZERE — установщик (Windows)' -ForegroundColor Cyan
Write-Host ('   Корень:    ' + $Prefix) -ForegroundColor Gray
Write-Host ('   Редакция:  ' + $Edition) -ForegroundColor Gray
Write-Host ('   Модель:    ' + $Model) -ForegroundColor Gray
Write-Host ('   Режим:     ' + $(if ($CheckOnly) { 'проверка (-CheckOnly)' } else { 'установка' })) -ForegroundColor Gray
Write-Host '=================================================' -ForegroundColor Cyan

# --- Сбор состояния ---
$pyState = Get-PythonState
$venvState = Get-VenvState -VenvPy $venvPy
$ollamaState = Get-OllamaState -WantedModel $Model

$whisperPath = Join-Path $Prefix 'ZERE.Voice\Models\ggml-base.bin'
$uvExePath = Join-Path $Prefix 'tools\uv.exe'
$whisperOk = Test-FileIntegrity -Path $whisperPath -Size $Artifacts.Whisper.Size -Sha256 $Artifacts.Whisper.Sha256
# uv — менеджер Python: без него не работают ни ChatTTS (TTS), ни клонирование голоса
$uvOk = Test-Path -LiteralPath $uvExePath

$dotnetExe = Get-DotnetExe
$dotnetOk = ($null -ne $dotnetExe) -and (Test-DotnetSdk10 -Exe $dotnetExe)
$publishExe = Join-Path $Prefix 'publish\app\ZERE.App.exe'
$publishOk = Test-Path $publishExe

$speakerExe = Join-Path $Prefix 'publish\speaker\ZERE.Speaker.exe'
$speakerOk = Test-Path $speakerExe

$panelDistOk = Test-Path (Join-Path $Prefix 'panel\dist\index.html')
$launcherOk = Test-Path (Join-Path $Prefix 'ZERE.bat')

$needPython = -not $pyState.Ok
$needVenv = -not ($venvState.Venv -and $venvState.Deps)
$needOllama = (-not $SkipOllama) -and (-not $ollamaState.Installed)
$needServer = (-not $SkipOllama) -and $ollamaState.Installed -and (-not $ollamaState.Running)
$needModel = (-not $SkipOllama) -and $ollamaState.Running -and (-not $ollamaState.Model)
$needWhisper = (-not $SkipVoice) -and (-not $whisperOk)
$needUv = (-not $SkipVoice) -and (-not $uvOk)
$needDotnetSdk = (($Edition -eq 'dotnet') -or ($Edition -eq 'both')) -and (-not $dotnetOk)
$needPublish = (($Edition -eq 'dotnet') -or ($Edition -eq 'both')) -and (-not $publishOk)
$needSpeaker = $dotnetOk -and (-not $speakerOk)
$needPanel = -not $panelDistOk
$needLauncher = -not $launcherOk
$needShortcuts = (-not $SkipShortcuts)

if ($needPython)   { $script:PythonExe = $null } else { $script:PythonExe = $pyState.Exe }

# --- Режим проверки: только отчёт ---
if ($CheckOnly) {
    Write-Step 'Состояние компонентов'
    function _line([bool]$ok, [string]$text) {
        if ($ok) { Write-Ok $text } else { Write-Fail2 $text }
    }
    _line $pyState.Ok $pyState.Detail
    if ($needPython) { Write-Info '=> потребуется установка Python 3.12+' }
    _line ($venvState.Venv -and $venvState.Deps) $venvState.Detail
    if ($needVenv) { Write-Info '=> потребуется создание .venv и установка зависимостей' }
    if ($SkipOllama) {
        Write-Info 'Ollama: пропущено (-SkipOllama)'
    } else {
        _line $ollamaState.Installed $ollamaState.Detail
        if ($needOllama) { Write-Info '=> потребуется установка Ollama (winget)' }
        if ($needServer) { Write-Info '=> потребуется запуск сервера Ollama' }
        if ($needModel) { Write-Info ('=> потребуется загрузка модели ' + $Model) }
    }
    if ($SkipVoice) {
        Write-Info 'Голос: пропущено (-SkipVoice)'
    } else {
        _line $whisperOk ('Whisper ggml-base.bin: ' + $(if ($whisperOk) { 'SHA-256 совпал' } else { 'не установлен или битый' }))
        _line $uvOk ('uv (tools\uv.exe): ' + $(if ($uvOk) { 'на месте' } else { 'не установлен' }))
        if ($needWhisper -or $needUv) { Write-Info '=> потребуется скачивание голосовых артефактов (~165 МБ)' }
        Write-Info 'ChatTTS (TTS-движок) uv скачает сам при первом синтезе (~2–3 ГБ)'
    }
    if (($Edition -eq 'dotnet') -or ($Edition -eq 'both')) {
        _line $dotnetOk ('.NET SDK 10: ' + $(if ($dotnetOk) { 'найден' } else { 'не найден' }))
        _line $publishOk ('C#-сборка publish\app\ZERE.App.exe: ' + $(if ($publishOk) { 'есть' } else { 'нет' }))
    }
    _line $speakerOk ('C#-озвучка publish\speaker\ZERE.Speaker.exe: ' + $(if ($speakerOk) { 'есть' } else { 'нет (озвучка на Python)' }))
    _line $panelDistOk ('Web-панель panel\dist: ' + $(if ($panelDistOk) { 'собрана' } else { 'не собрана' }))
    _line $launcherOk ('Лаунчер ZERE.bat: ' + $(if ($launcherOk) { 'есть' } else { 'нет' }))

    $problems = @()
    if ($needPython) { $problems += 'Python' }
    if ($needVenv) { $problems += '.venv/зависимости' }
    if ($needOllama -or $needServer -or $needModel) { $problems += 'Ollama/модель' }
    if ($needWhisper -or $needUv) { $problems += 'голос' }
    if ($needDotnetSdk -or $needPublish) { $problems += '.NET/публикация' }
    if ($needPanel) { $problems += 'панель' }
    if ($needLauncher) { $problems += 'лаунчер' }
    Write-Host ''
    if ($problems.Count -eq 0) {
        Write-Host 'ВСЁ ГОТОВО — установка не требуется.' -ForegroundColor Green
        exit 0
    }
    Write-Host ('Требуются действия: ' + ($problems -join ', ')) -ForegroundColor Yellow
    exit 1
}

# --- План установки ---
Write-Step 'План установки'
$plan = @()
if ($needPython)   { $plan += 'Установить Python 3.12+ (winget)' }
if ($needVenv)     { $plan += 'Создать .venv и установить зависимости из requirements.txt' }
if ($needOllama)   { $plan += 'Установить Ollama (winget)' }
if ($needServer)   { $plan += 'Запустить сервер Ollama' }
if ($needModel)    { $plan += ('Загрузить модель Ollama "' + $Model + '" (интернет)' ) }
if ($needWhisper)  { $plan += ('Скачать ' + $Artifacts.Whisper.Label) }
if ($needUv)       { $plan += ('Скачать ' + $Artifacts.Uv.Label) }
if ($needDotnetSdk) { $plan += 'Установить .NET SDK 10 (winget)' }
if ($needPublish)  { $plan += 'Опубликовать C#-версию (dotnet publish)' }
if ($needSpeaker)  { $plan += 'Опубликовать C#-озвучку (dotnet publish ZERE.Speaker)' }
if ($needPanel)    { $plan += 'Собрать web-панель (npm)' }

if ($plan.Count -eq 0) {
    Write-Info 'Все компоненты уже установлены.'
    Write-Info 'Выполняется перепроверка целостности, настройка (config, ZERE.bat, ярлыки, манифест) и smoke-тест.'
} else {
    foreach ($p in $plan) { Write-Host ('   - ' + $p) -ForegroundColor White }
    Write-Host ('   - Настройка: config/*.json, ZERE.bat, ярлыки, манифест, smoke-тест') -ForegroundColor White
    if (-not $Yes) {
        $answer = Read-Host 'Продолжить установку? [Y/n]'
        $answer = $answer.Trim()
        if ($answer -ne '' -and $answer -notmatch '(?i)^(y|д|да|yes)$') {
            Write-Warn2 'Установка отменена пользователем.'
            exit 0
        }
    }
}

$failedCritical = $false

# --- 1. Python ---
Write-Step 'Python 3.12+'
if ($needPython) {
    if ($null -eq (Get-Winget)) {
        Finish -Ok $false -Name 'Python' -FailDetail 'winget недоступен — установите Python 3.12+ вручную (https://python.org) и перезапустите установщик' -Critical
        $failedCritical = $true
    } else {
        $st = Install-PythonEngine
        if ($null -ne $st) {
            $script:PythonExe = $st.Exe
            Finish -Ok $true -Name 'Python' -OkDetail ('установлен ' + $st.Detail)
        } else {
            Finish -Ok $false -Name 'Python' -FailDetail 'не удалось установить Python через winget' -Critical
            $failedCritical = $true
        }
    }
} else {
    Skip-Result -Name 'Python' -Detail $pyState.Detail
    $script:PythonExe = $pyState.Exe
}

# --- 2. venv + зависимости ---
Write-Step 'Виртуальное окружение и зависимости'
if (-not $failedCritical) {
    if ($needVenv) {
        $okV = Install-Venv -VenvDir $venvDir -VenvPy $venvPy -PythonExe $script:PythonExe -Root $Prefix
        Finish -Ok $okV -Name '.venv и зависимости' -OkDetail '.venv создан, зависимости установлены' -FailDetail 'ошибка создания .venv или pip install' -Critical:(-not $okV)
        if (-not $okV) { $failedCritical = $true }
    } else {
        Skip-Result -Name '.venv и зависимости' -Detail $venvState.Detail
    }
} else {
    Add-Result -Name '.venv и зависимости' -Status fail -Detail 'пропущено: нет Python' -Critical
}

# --- 3. Ollama ---
$ollamaExeNow = $ollamaState.Exe
if (-not $SkipOllama) {
    Write-Step 'Ollama и модель'
    if ($needOllama) {
        $exe = Install-OllamaEngine
        if ($null -eq $exe) {
            Finish -Ok $false -Name 'Ollama' -FailDetail 'winget не смог установить Ollama' -Critical
            $failedCritical = $true
        } else {
            $ollamaExeNow = $exe
            Write-Ok 'Ollama установлен'
            Add-Result -Name 'Ollama' -Status ok -Detail 'установлен через winget'
        }
    } elseif ($ollamaState.Installed) {
        Skip-Result -Name 'Ollama' -Detail $ollamaState.Detail
    }

    if (-not $failedCritical) {
        if ($needServer) {
            $started = Start-OllamaServer -Exe $ollamaExeNow
            Finish -Ok $started -Name 'Сервер Ollama' -OkDetail 'сервер запущен, порт 11434' -FailDetail 'сервер Ollama не запустился за 60 с' -Critical:(-not $started)
            if (-not $started) { $failedCritical = $true }
        } elseif ($ollamaState.Running) {
            Skip-Result -Name 'Сервер Ollama' -Detail 'уже запущен'
        }

        if ($needModel) {
            $mOk = Install-OllamaModel -Exe $ollamaExeNow -WantedModel $Model
            Finish -Ok $mOk -Name ('Модель ' + $Model) -OkDetail 'модель загружена' -FailDetail ('не удалось загрузить модель ' + $Model) -Critical:(-not $mOk)
            if (-not $mOk) { $failedCritical = $true }
        } elseif ($ollamaState.Running) {
            Skip-Result -Name ('Модель ' + $Model) -Detail 'уже загружена'
        }
    }
} else {
    Add-Result -Name 'Ollama' -Status skip -Detail 'пропущено (-SkipOllama)'
}

# --- 4. Голос ---
if (-not $SkipVoice) {
    Write-Step 'Голосовые компоненты (Whisper, uv)'
    $voiceOkAll = $true
    if ($needWhisper -or $needUv) {
        $voiceOkAll = Install-VoiceAssets -Root $Prefix
        Finish -Ok $voiceOkAll -Name 'Голосовые компоненты' -OkDetail 'скачано и проверено по SHA-256' -FailDetail 'часть артефактов не скачалась/не прошла проверку'
    } else {
        Skip-Result -Name 'Голосовые компоненты' -Detail 'Whisper + uv на месте (SHA-256 совпали)'
    }
} else {
    Add-Result -Name 'Голосовые компоненты' -Status skip -Detail 'пропущено (-SkipVoice)'
}

# --- 5. .NET-редакция ---
if (($Edition -eq 'dotnet') -or ($Edition -eq 'both')) {
    Write-Step '.NET-редакция (C#)'
    $dExe = Get-DotnetExe
    if ($needDotnetSdk) {
        Write-Info 'winget install Microsoft.DotNet.SDK.10'
        $null = Invoke-Winget -Arguments @('install', '--id', 'Microsoft.DotNet.SDK.10', '-e')
        Update-SessionPath
        $dExe = Get-DotnetExe
        if ($null -eq $dExe -or -not (Test-DotnetSdk10 -Exe $dExe)) {
            Finish -Ok $false -Name '.NET SDK 10' -FailDetail 'SDK не установлен (возможно, требовался UAC)' -Critical
            $failedCritical = $true
        } else {
            Finish -Ok $true -Name '.NET SDK 10' -OkDetail 'установлен'
        }
    } elseif ($dotnetOk) {
        Skip-Result -Name '.NET SDK 10' -Detail 'уже установлен'
    }
    if (-not $failedCritical -and $needPublish) {
        $pOk = Publish-DotnetEdition -Root $Prefix -DotnetExe $dExe
        Finish -Ok $pOk -Name 'C#-сборка' -OkDetail 'publish\app\ZERE.App.exe собран' -FailDetail 'dotnet publish завершился с ошибкой' -Critical:(-not $pOk)
        if (-not $pOk) { $failedCritical = $true }
    } elseif (-not $needPublish) {
        Skip-Result -Name 'C#-сборка' -Detail 'publish\app\ZERE.App.exe уже собран'
    }
    # Хелпер озвучки: с ним Python-редакция отдаёт DSP и вывод звука коду на C#
    if (-not $failedCritical -and $needSpeaker) {
        $spOk = Publish-Speaker -Root $Prefix -DotnetExe $dExe
        Finish -Ok $spOk -Name 'C#-озвучка' -OkDetail 'publish\speaker\ZERE.Speaker.exe собран' -FailDetail 'хелпер озвучки не собран — озвучка останется на Python'
    } elseif ($speakerOk) {
        Skip-Result -Name 'C#-озвучка' -Detail 'publish\speaker\ZERE.Speaker.exe уже собран'
    }
} else {
    Add-Result -Name '.NET-редакция' -Status skip -Detail 'редакция не выбрана'

    # Python-редакция тоже может озвучивать через C# — если есть .NET SDK.
    $spExe = Get-DotnetExe
    if ($null -ne $spExe) {
        Write-Step 'C#-озвучка (необязательно)'
        if ($needSpeaker) {
            $spOk = Publish-Speaker -Root $Prefix -DotnetExe $spExe
            if ($spOk) {
                Finish -Ok $true -Name 'C#-озвучка' -OkDetail 'publish\speaker\ZERE.Speaker.exe собран'
            } else {
                Skip-Result -Name 'C#-озвучка' -Detail 'не собралась — озвучка останется на Python'
            }
        } else {
            Skip-Result -Name 'C#-озвучка' -Detail 'publish\speaker\ZERE.Speaker.exe уже собран'
        }
    } else {
        Add-Result -Name 'C#-озвучка' -Status skip -Detail 'нет .NET SDK — озвучка на Python (работает)'
    }
}

# --- 6. Панель ---
Write-Step 'Web-панель'
if ($needPanel) {
    $npOk = Build-Panel -Root $Prefix
    if ($npOk) {
        Finish -Ok $true -Name 'Web-панель' -OkDetail 'panel\dist собрана'
    } else {
        Finish -Ok $false -Name 'Web-панель' -FailDetail 'dist отсутствует, а npm недоступен или сборка не удалась (панель необязательна)'
    }
} else {
    Skip-Result -Name 'Web-панель' -Detail 'panel\dist уже собрана'
}

# --- 7. Конфигурация ---
Write-Step 'Конфигурация'
$cfgMade = Ensure-Config -Root $Prefix
if ($cfgMade) {
    Finish -Ok $true -Name 'Конфигурация' -OkDetail 'созданы недостающие config/*.json'
} else {
    Skip-Result -Name 'Конфигурация' -Detail 'config/*.json на месте'
}

# --- 8. Лаунчер и ярлыки ---
Write-Step 'Лаунчер и ярлыки'
$lnOk = Install-Launcher -Root $Prefix
Finish -Ok $lnOk -Name 'Лаунчер ZERE.bat' -OkDetail 'создан ZERE.bat в корне' -FailDetail 'шаблон ZereLauncher.bat не найден'
if ($needShortcuts) {
    if ($lnOk) {
        try {
            $scOk = New-Shortcuts -Root $Prefix
            Finish -Ok $scOk -Name 'Ярлыки' -OkDetail 'рабочий стол + меню «Пуск»' -FailDetail 'не удалось создать ярлыки'
        } catch {
            Finish -Ok $false -Name 'Ярлыки' -FailDetail ('ошибка: ' + $_.Exception.Message)
        }
    } else {
        Add-Result -Name 'Ярлыки' -Status fail -Detail 'пропущено: нет лаунчера'
    }
} else {
    Add-Result -Name 'Ярлыки' -Status skip -Detail 'пропущено (-SkipShortcuts)'
}

# --- 9. Манифест ---
try {
    $null = Write-InstallManifest -Root $Prefix -PythonExe $script:PythonExe
    Finish -Ok $true -Name 'Манифест' -OkDetail 'installer\install-manifest.json записан'
} catch {
    Finish -Ok $false -Name 'Манифест' -FailDetail $_.Exception.Message
}

# --- 10. Smoke-тест ---
Write-Step 'Smoke-тест'
if (Test-Path $venvPy) {
    $smokeOk = Invoke-SmokeTest -VenvPy $venvPy -Root $Prefix
    Finish -Ok $smokeOk -Name 'Smoke-тест (compileall)' -OkDetail 'main.py + zere компилируются' -FailDetail 'ошибки компиляции в main.py/zere'
} else {
    Add-Result -Name 'Smoke-тест (compileall)' -Status fail -Detail 'нет .venv' -Critical
}

# --- Отчёт ---
Show-Report
$fails = @($script:Results | Where-Object { $_.Status -eq 'fail' })
$critFails = @($fails | Where-Object { $_.Critical })
$elapsed = (Get-Date) - $startTime

Write-Host ''
if ($critFails.Count -gt 0) {
    Write-Host ('УСТАНОВКА ЗАВЕРШЕНА С ОШИБКАМИ (' + $critFails.Count + ' критичных). См. [FAIL] выше.') -ForegroundColor Red
    exit 1
}
if ($fails.Count -gt 0) {
    Write-Host ('Установка завершена, есть некритичные проблемы (' + $fails.Count + '). ZERE должен запускаться.') -ForegroundColor Yellow
} else {
    Write-Host 'Установка ZERE завершена успешно.' -ForegroundColor Green
}
Write-Host ('Время: ' + [int]$elapsed.TotalSeconds + ' с') -ForegroundColor Gray

# --- Запуск ---
$batPath = Join-Path $Prefix 'ZERE.bat'
if (-not $NoLaunch -and (Test-Path $batPath)) {
    $answer = 'y'
    if (-not $Yes) {
        $answer = Read-Host 'Запустить ZERE сейчас? [Y/n]'
        $answer = $answer.Trim()
    }
    if ($answer -eq '' -or $answer -match '(?i)^(y|д|да|yes)$') {
        Start-Process -FilePath 'cmd.exe' -ArgumentList ('/k "' + $batPath + '"') | Out-Null
    }
}
exit 0
