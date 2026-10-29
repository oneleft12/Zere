#Requires -Version 5.1
<#
.SYNOPSIS
    Подпись файлов ZERE (Authenticode) — без Windows SDK и signtool.

.DESCRIPTION
    Smart App Control (Windows 11) пускает только приложения, подписанные
    сертификатом от доверенного УЦ, а SmartScreen показывает «Unknown
    publisher» у неподписанных файлов. Этот скрипт ставит подпись
    встроенными средствами PowerShell (Set-AuthenticodeSignature), поэтому
    signtool.exe (Windows SDK) не нужен.

    Источник сертификата — один из трёх:
      - -Thumbprint  — сертификат уже в хранилище (USB-токен, облачный HSM,
                       Certum SimplySign/ProCertum): ключ не покидает носитель;
      - -Pfx         — файл .pfx (старые сертификаты, тесты, локальная сборка);
      - -SelfTest    — самоподписанный сертификат «CN=ZERE Self-Test».
                       ТОЛЬКО для проверки конвейера: Windows ему не доверяет,
                       Smart App Control такой файл всё равно заблокирует.

    Подпись ставится с меткой времени (по умолчанию DigiCert): без неё после
    истечения сертификата подпись становится недействительной.

.PARAMETER Files
    Файлы для подписи: .exe, .dll, .ps1 (.ps1 не понимает Smart App Control,
    но подпись полезна против подмены).

.PARAMETER Thumbprint
    Отпечаток сертификата в CurrentUser\My или LocalMachine\My.

.PARAMETER Pfx
    Путь к .pfx с ключом.

.PARAMETER PfxPassword
    Пароль .pfx (открытый текст; в CI — из секрета).

.PARAMETER SelfTest
    Взять/создать самоподписанный сертификат для проверки конвейера.

.PARAMETER TimestampServer
    Сервер метки времени.

.PARAMETER AllowSelfSigned
    Считать успехом самоподписанную подпись (по умолчанию успех — только
    «Valid», то есть цепочка доверия проходит).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\sign.ps1 -Files installer\Output\ZereSetup.exe -Thumbprint ABCD1234

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\sign.ps1 -Files installer\Output\ZereSetup.exe -SelfTest -AllowSelfSigned
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string[]]$Files,
    [string]$Thumbprint = '',
    [string]$Pfx = '',
    [string]$PfxPassword = '',
    [switch]$SelfTest,
    [string]$TimestampServer = 'http://timestamp.digicert.com',
    [switch]$AllowSelfSigned
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Msg) { Write-Host ('== ' + $Msg) -ForegroundColor Cyan }
function Write-Ok([string]$Msg) { Write-Host ('   [OK] ' + $Msg) -ForegroundColor Green }
function Write-Warn2([string]$Msg) { Write-Host ('   [!]  ' + $Msg) -ForegroundColor Yellow }
function Write-Fail2([string]$Msg) { Write-Host ('   [X]  ' + $Msg) -ForegroundColor Red }

# --- Сертификат -------------------------------------------------------------

function Get-CodeSigningCertificate {
    if ($SelfTest) {
        $subject = 'CN=ZERE Self-Test'
        $cert = Get-ChildItem Cert:\CurrentUser\My |
            Where-Object { $_.Subject -eq $subject -and $_.HasPrivateKey } |
            Sort-Object NotAfter -Descending |
            Select-Object -First 1
        if ($null -ne $cert -and $cert.NotAfter -gt (Get-Date).AddDays(1)) {
            return $cert
        }
        Write-Warn2 ('создан самоподписанный сертификат "' + $subject + '" (только для проверки конвейера)')
        return New-SelfSignedCertificate `
            -Type CodeSigningCert `
            -Subject $subject `
            -CertStoreLocation 'Cert:\CurrentUser\My' `
            -NotAfter (Get-Date).AddDays(30)
    }

    if ($Pfx -ne '') {
        if (-not (Test-Path -LiteralPath $Pfx)) {
            throw ('не найден .pfx: ' + $Pfx)
        }
        $secure = ConvertTo-SecureString -String $PfxPassword -AsPlainText -Force
        return Import-PfxCertificate -FilePath $Pfx -CertStoreLocation 'Cert:\CurrentUser\My' -Password $secure
    }

    if ($Thumbprint -ne '') {
        $clean = ($Thumbprint -replace '[^0-9A-Fa-f]', '').ToUpperInvariant()
        foreach ($store in @('Cert:\CurrentUser\My', 'Cert:\LocalMachine\My')) {
            $cert = Get-ChildItem $store |
                Where-Object { $_.Thumbprint -eq $clean -and $_.HasPrivateKey } |
                Select-Object -First 1
            if ($null -ne $cert) { return $cert }
        }
        throw ('сертификат с отпечатком ' + $clean + ' не найден (или у него нет закрытого ключа)')
    }

    throw ('не задан сертификат: укажите -Thumbprint, -Pfx или -SelfTest. ' +
           'Как получить сертификат — docs\SIGNING.md')
}

# --- Подпись ----------------------------------------------------------------

$certificate = Get-CodeSigningCertificate

Write-Step 'Подпись файлов'
Write-Host ('   сертификат: ' + $certificate.Subject) -ForegroundColor Gray
Write-Host ('   издатель:    ' + $certificate.Issuer) -ForegroundColor Gray
Write-Host ('   срок:        ' + $certificate.NotAfter.ToString('yyyy-MM-dd')) -ForegroundColor Gray
if ($TimestampServer -ne '') {
    Write-Host ('   метка времени: ' + $TimestampServer) -ForegroundColor Gray
}

$failed = @()
$signed = @()

foreach ($file in $Files) {
    $path = [System.IO.Path]::GetFullPath($file)
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Fail2 ('нет файла: ' + $path)
        $failed += $path
        continue
    }

    try {
        $result = Set-AuthenticodeSignature `
            -FilePath $path `
            -Certificate $certificate `
            -TimestampServer $TimestampServer `
            -HashAlgorithm SHA256

        $status = [string]$result.Status
        $check = Get-AuthenticodeSignature -FilePath $path
        $checkStatus = [string]$check.Status

        if ($checkStatus -eq 'Valid' -or ($SelfTest -and $AllowSelfSigned -and $checkStatus -ne 'NotSigned' -and $checkStatus -ne 'HashMismatch')) {
            if ($checkStatus -ne 'Valid') {
                Write-Warn2 ((Split-Path -Leaf $path) + ': подпись есть, но цепочка не доверенная (' + $checkStatus + ') — для распространения нужен сертификат от УЦ')
            } else {
                Write-Ok ((Split-Path -Leaf $path) + ': ' + $checkStatus + ', метка времени: ' + $(if ($check.TimeStamperCertificate) { 'есть' } else { 'нет' }))
            }
            $signed += $path
        } else {
            Write-Fail2 ((Split-Path -Leaf $path) + ': ' + $checkStatus + ' (' + $status + ')')
            if ($check.StatusMessage) { Write-Host ('      ' + $check.StatusMessage) -ForegroundColor DarkGray }
            $failed += $path
        }
    } catch {
        Write-Fail2 ((Split-Path -Leaf $path) + ': ' + $_.Exception.Message)
        $failed += $path
    }
}

Write-Host ''
if ($failed.Count -gt 0) {
    Write-Host ('ПОДПИСЬ НЕ ПОСТАВЛЕНА: ' + $failed.Count + ' из ' + $Files.Count) -ForegroundColor Red
    exit 1
}

Write-Host ('ПОДПИСАНО: ' + $signed.Count + ' файл(ов)') -ForegroundColor Green
exit 0
