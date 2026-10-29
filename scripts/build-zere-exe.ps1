# Сборка zere.exe — лаунчера приложения ZERE.
#
# Компилятор берётся системный: csc.exe из .NET Framework 4.x есть в любой
# Windows 10/11, поэтому для сборки лаунчера не нужен ни dotnet SDK, ни
# NuGet, ни интернет. Исходник — zere\desktop\launcher\ZereLauncher.cs
# (C# 5, как и требует этот csc).
#
# Запуск:
#   powershell -ExecutionPolicy Bypass -File scripts\build-zere-exe.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\build-zere-exe.ps1 -Out bin\zere.exe

[CmdletBinding()]
param(
    [string]$Root = '',
    [string]$Out = ''
)

$ErrorActionPreference = 'Stop'

if ($Root -eq '') {
    $Root = Split-Path -Parent $PSScriptRoot
}
$Root = [System.IO.Path]::GetFullPath($Root)

if ($Out -eq '') {
    $Out = Join-Path $Root 'zere.exe'
}
$Out = [System.IO.Path]::GetFullPath($Out)

$source = Join-Path $Root 'zere\desktop\launcher\ZereLauncher.cs'
$icon = Join-Path $Root 'assets\zere.ico'

if (-not (Test-Path -LiteralPath $source)) {
    throw "Не найден исходник лаунчера: $source"
}

# csc ищет себя в Framework64 (64-битная Windows) или Framework (32-битная).
$csc = $null
foreach ($candidate in @(
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'),
        (Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'))) {
    if (Test-Path -LiteralPath $candidate) {
        $csc = $candidate
        break
    }
}
if ($null -eq $csc) {
    throw 'Не найден csc.exe из .NET Framework 4.x — лаунчер не собрать.'
}

$outDir = Split-Path -Parent $Out
if (-not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$arguments = @(
    '/nologo',
    '/target:winexe',
    '/platform:anycpu',
    '/optimize+',
    ('/out:' + $Out),
    '/r:System.dll',
    '/r:System.Windows.Forms.dll',
    '/r:System.Drawing.dll'
)

if (Test-Path -LiteralPath $icon) {
    $arguments += ('/win32icon:' + $icon)
} else {
    Write-Warning "Нет иконки $icon — zere.exe соберётся без неё (python scripts\make_icon.py)."
}

$arguments += $source

Write-Host ('csc: ' + $csc)
Write-Host ('-> ' + $Out)

& $csc @arguments
if ($LASTEXITCODE -ne 0) {
    throw ('csc завершился с кодом ' + $LASTEXITCODE)
}

if (-not (Test-Path -LiteralPath $Out)) {
    throw "csc не создал $Out"
}

$info = Get-Item -LiteralPath $Out
Write-Host ('Готово: ' + $info.FullName + ' (' + [math]::Round($info.Length / 1024, 1) + ' КБ)')
exit 0
