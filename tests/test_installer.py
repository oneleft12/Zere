"""Тесты установщика ZERE (installer/).

Проверяют то, что ломается чаще всего и что невозможно поймать прогоном
на одной машине:

- UTF-8 BOM у .ps1 (иначе Windows PowerShell 5.1 читает файл как ANSI
  и кириллица в комментариях/строках ломает парсинг);
- CRLF и чистый ASCII у .bat (кодировка cmd);
- контрольные SHA-256/размеры скачиваемых артефактов в install.ps1;
- связность файлов: install.ps1 <-> ZereLauncher.bat <-> Zere.iss
  <-> build-setup.ps1 <-> uninstall.ps1;
- синтаксис .ps1 через парсер PowerShell (только если PowerShell доступен,
  на Linux — пропускается);
- деинсталлятор не удаляет исходный код.

Запуск:
- `python3 tests/test_installer.py` — без зависимостей;
- `pytest tests/ -q` — в CI (функции test_* без аргументов).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer"

BOM = b"\xef\xbb\xbf"

# Контрольные суммы из install.ps1 (источники: HuggingFace x-linked-etag,
# SHA-256 вычислен при скачивании с GitHub release).
EXPECTED_ARTIFACTS = {
    "GigaAm": (
        "f9620a0099019c6afcee26525ef9ed3297fa50dd5691c1902af0c948fc1a470b",
        170197019,
    ),
    "Whisper": (
        "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
        147951465,
    ),
    # Silero (TTS-движок) отдельным артефактом не скачивается: torch ставит uv
    # при первом синтезе. Установщик качает сам менеджер Python — uv.
    "Uv": (
        "75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90",
        18043715,
    ),
}

PS1_FILES = ("install.ps1", "uninstall.ps1", "build-setup.ps1", "build-installer.ps1", "sign.ps1")
BAT_FILES = ("ZereLauncher.bat", "Install-Zere.bat", "Uninstall-Zere.bat")


def _read(name: str) -> str:
    return (INSTALLER / name).read_text(encoding="utf-8-sig")


def test_installer_files_exist() -> None:
    expected = set(PS1_FILES) | set(BAT_FILES) | {"Zere.iss", "ZereSetup.cs"}
    missing = sorted(n for n in expected if not (INSTALLER / n).is_file())
    assert not missing, f"нет файлов установщика: {missing}"


def test_ps1_has_utf8_bom() -> None:
    """Windows PowerShell 5.1 читает UTF-8 без BOM как ANSI → битый парсинг."""
    for name in PS1_FILES:
        data = (INSTALLER / name).read_bytes()
        assert data.startswith(BOM), f"{name}: нет UTF-8 BOM"


def test_bat_is_ascii_crlf() -> None:
    """cmd надёжно исполняет только CRLF, лаунчер обязан быть чистым ASCII."""
    for name in BAT_FILES:
        data = (INSTALLER / name).read_bytes()
        assert data.startswith(b"@echo off"), f"{name}: нет @echo off"
        try:
            data.decode("ascii")
        except UnicodeDecodeError as exc:
            raise AssertionError(f"{name}: не ASCII ({exc})") from None
        assert b"\n" not in data.replace(b"\r\n", b""), (
            f"{name}: есть переносы строк без CR (нужен CRLF)"
        )


def test_artifact_hashes_and_sizes() -> None:
    """Контрольные SHA-256 и размеры в install.ps1 не разошлись с эталоном."""
    text = _read("install.ps1")
    for key, (sha, size) in EXPECTED_ARTIFACTS.items():
        assert re.search(
            rf"{key}\s*=\s*@\{{[^}}]*Sha256\s*=\s*'{sha}'", text, re.S
        ), f"{key}: Sha256 не совпадает с эталоном"
        assert re.search(
            rf"{key}\s*=\s*@\{{[^}}]*Size\s*=\s*{size}\b", text, re.S
        ), f"{key}: Size != {size}"


def test_install_references_launcher_template() -> None:
    text = _read("install.ps1")
    assert "ZereLauncher.bat" in text, "install.ps1 не копирует лаунчер"
    assert "-CheckOnly" in text, "install.ps1 нет режима -CheckOnly"
    for pname in (
        "Prefix", "Edition", "Model", "SkipOllama", "SkipVoice",
        "SkipShortcuts", "CheckOnly", "Yes", "NoLaunch",
    ):
        assert f"${pname}" in text, f"install.ps1 нет параметра ${pname}"


def test_launcher_handles_smart_app_control() -> None:
    """Неподписанный zere.exe блокируется Smart App Control (Windows 11).

    В этом режиме лаунчер и ярлык запускают подписанный pythonw.exe с
    `main.py --desktop` — окно то же, консоли нет. Иначе пользователь видел бы
    «Компонент заблокирован политикой Device Guard» вместо приложения.
    """
    ps1 = _read("install.ps1")
    assert "function Test-SmartAppControl" in ps1, "нет определения SAC"
    assert "VerifiedAndReputablePolicyState" in ps1, "SAC определяется не по реестру"
    assert "main.py --desktop" in ps1, "ярлык не умеет запускать pythonw с --desktop"

    bat = (INSTALLER / "ZereLauncher.bat").read_bytes().decode("ascii")
    assert "VerifiedAndReputablePolicyState" in bat, "лаунчер не проверяет SAC"
    assert "pythonw.exe" in bat, "лаунчер не умеет запускать приложение через pythonw"
    # Приложение — первый путь: zere.exe запускается всегда, когда он есть.
    # Откат на pythonw включается, только если exe не стартовал при включённом
    # SAC (иначе второй запуск поверх диалога ошибки самого exe).
    assert 'if exist "zere.exe"' in bat, "лаунчер не запускает zere.exe"
    assert 'if errorlevel 1 if "%SAC%"=="1" goto :fallback' in bat, (
        "откат на pythonw должен срабатывать только при блокировке zere.exe"
    )


def test_launcher_prefers_app() -> None:
    """Лаунчер начинает с zere.exe, затем .venv, затем .NET."""
    data = (INSTALLER / "ZereLauncher.bat").read_bytes().decode("ascii")
    app_pos = data.find("zere.exe")
    venv_pos = data.find(".venv\\Scripts\\python.exe")
    dotnet_pos = data.find("publish\\app\\ZERE.App.exe")
    assert 0 < app_pos < venv_pos < dotnet_pos, "порядок запуска нарушен"


def test_uninstall_never_touches_sources() -> None:
    """Деинсталлятор удаляет только артефакты, но не исходный код и данные."""
    text = _read("uninstall.ps1")
    # Только пути в вызовах удаления (не все Join-Path: есть и проверки вида
    # `Test-Path (Join-Path $Prefix 'main.py')` — это охрана, а не удаление).
    removal_lines = [
        line for line in text.splitlines()
        if "Remove-Item" in line and "Join-Path $Prefix" in line
    ]
    quoted = re.findall(r"Join-Path \$Prefix '([^']+)'", " ".join(removal_lines))
    first_segments = {re.split(r"[\\/]", q)[0] for q in quoted}
    # Каталоги-исходники: удалять нельзя вообще (config\panel.token под
    # -PurgeData — можно, а вот весь каталог config — нет)
    banned_dirs = {"zere", "panel", "docs", "tests", "installer"}
    # Отдельные файлы-исходники: запрещено удалять
    banned_files = {"main.py", "requirements.txt", "AGENTS.md", "README.md", "ZERE.slnx"}
    hit_dirs = {s for s in first_segments if s.lower() in banned_dirs}
    if any(q.lower() == "config" for q in quoted):
        hit_dirs.add("config")
    hit_files = set(quoted) & banned_files
    assert not hit_dirs and not hit_files, (
        f"uninstall.ps1 удаляет исходники: {sorted(hit_dirs | hit_files)}"
    )
    assert "$RemoveAssets" in text and "$PurgeData" in text
    # Чистка данных — только внутри блока if ($PurgeData)
    assert re.search(
        r"if \(\$PurgeData\) \{[^}]*?Join-Path \$Prefix 'zere\.db'",
        text,
        re.S,
    ), "zere.db удаляется без привязки к флагу -PurgeData"


def test_inno_script_wiring() -> None:
    iss = _read("Zere.iss")
    assert "install.ps1" in iss, "Zere.iss не запускает install.ps1"
    assert "uninstall.ps1" in iss, "Zere.iss не запускает uninstall.ps1"
    assert "PrivilegesRequired=lowest" in iss, "установка должна быть per-user"
    assert "ZereInstaller" in iss, "нет имени дистрибутива (ZereInstaller.exe)"
    build = _read("build-setup.ps1")
    assert "Zere.iss" in build, "build-setup.ps1 не компилирует Zere.iss"
    assert "git archive" in build or "ls-files" in build, (
        "build-setup.ps1 не формирует stage из git"
    )
    assert "ISCC" in build, "build-setup.ps1 не ищет ISCC.exe"


def test_csharp_installer_runs_app_not_browser() -> None:
    """ZereSetup.exe ставит ZERE и запускает приложение zere.exe.

    Свой установщик на csc нужен из-за Smart App Control: он блокирует
    свежесобранный неподписанный Setup.exe от Inno Setup, а файлы системного
    компилятора пропускает — так же запускается zere.exe.
    """
    cs = _read("ZereSetup.cs")
    assert 'PayloadResource = "payload.zip"' in cs, "нет встроенного архива дистрибутива"
    assert "-Edition python -Yes -NoLaunch" in cs, "install.ps1 запускается не с Python-редакцией"
    assert "ZereUninstall.exe" in cs, "нет деинсталлятора рядом с программой"
    assert "Uninstall\\ZERE" in cs, "нет записи в «Установка и удаление программ»"
    assert 'Path.Combine(prefix, "zere.exe")' in cs, "установщик не запускает zere.exe"
    assert "webbrowser" not in cs, (
        "установщик не должен открывать браузерную панель — только окно zere.exe"
    )
    assert "Smart App" in cs and "WDAC" in cs, "нет пояснения, зачем свой установщик"


def test_installer_can_skip_ollama() -> None:
    """Галочка «Установить без Ollama»: ZERE работает без локальной модели.

    Ставить Ollama и 5 ГБ модели нужно не всем: с облачным ключом ZERE
    отвечает без локали. Галочка мастера и ключ /SKIPOLLAMA для тихой
    установки должны доходить до install.ps1 как -SkipOllama.
    """
    cs = _read("ZereSetup.cs")
    assert 'Text = "Установить без Ollama"' in cs, "нет галочки «Установить без Ollama»"
    assert '"/SKIPOLLAMA"' in cs, "нет ключа тихой установки /SKIPOLLAMA"
    assert 'arguments.Append(" -SkipOllama")' in cs, "галочка не передаёт -SkipOllama"
    assert "облачный ключ" in cs, "нет пояснения, чем заменить Ollama"

    ps1 = _read("install.ps1")
    assert "[switch]$SkipOllama" in ps1, "install.ps1 не принимает -SkipOllama"
    assert "пропущено (-SkipOllama)" in ps1, "установщик не помечает Ollama пропущенной"


def test_build_installer_can_default_to_no_ollama() -> None:
    """-NoOllama: сборка «только облачный ключ».

    Ollama вместе с моделью — это winget и ~5 ГБ; на ПК, где ZERE отвечает
    через API-ключ, это лишняя работа. Флаг сборки предустанавливает галочку
    в мастере и действует на тихую установку, а /WITHOLLAMA возвращает
    Ollama для конкретного запуска.
    """
    build = _read("build-installer.ps1")
    assert "[switch]$NoOllama" in build, "build-installer.ps1 не принимает -NoOllama"
    assert "/define:ZERE_NO_OLLAMA_DEFAULT" in build, "флаг сборки не доходит до csc"
    assert "variant" in build, "вариант сборки не попал в config/build-info.json"

    cs = _read("ZereSetup.cs")
    assert "#if ZERE_NO_OLLAMA_DEFAULT" in cs, "нет умолчания «без Ollama»"
    assert "options.SkipOllama = true;" in cs, "умолчание не включает SkipOllama"
    assert '"/WITHOLLAMA"' in cs, "нет обратного ключа /WITHOLLAMA"
    assert "/SKIPOLLAMA" in cs and "/WITHOLLAMA" in cs, "ключи тихой установки не описаны"


def test_app_starts_without_ollama_message() -> None:
    """«Все зависимости в порядке» не печатается, когда ИИ не настроен.

    Без Ollama и без облачного ключа ZERE всё равно запускается (режим
    приложения), но безусловный print говорил «всё в порядке» сразу после
    «Ollama недоступна» — противоречие в журнале запуска.
    """
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert re.search(
        r"if checker\.all_critical_passed\(\):\s*\n\s*print\(\"Все зависимости в порядке",
        text,
    ), "печать «всё в порядке» не привязана к проверке зависимостей"
    assert "ИИ не настроен" in text, "нет честного сообщения для запуска без Ollama"


def test_signing_pipeline() -> None:
    """Подпись — часть сборки: без неё Smart App Control блокирует exe.

    Подписываются оба файла: zere.exe ДО упаковки в payload (его запускают
    ярлыки) и ZereSetup.exe после компиляции. Подпись только установщика не
    спасает — приложение всё равно заблокируют.
    """
    build = _read("build-installer.ps1")
    assert "$CertThumbprint" in build, "нет параметра отпечатка сертификата"
    assert "$PfxPath" in build and "$SelfTestSign" in build, "нет .pfx и режима проверки"
    assert "sign.ps1" in build, "сборка не вызывает sign.ps1"

    # zere.exe подписывается до создания payload.zip, установщик — после csc.
    payload_pos = build.find("упаковка payload.zip")
    sign_app_pos = build.find("$signTargets = @(Join-Path $stageDir 'zere.exe')")
    compile_pos = build.find("csc -> ")
    sign_setup_pos = build.find("$signParams = @{ Files = @($setupPath) }")
    assert 0 < sign_app_pos < payload_pos, "zere.exe подписывается после упаковки payload"
    assert 0 < compile_pos < sign_setup_pos, "ZereSetup.exe подписывается до компиляции"

    sign = _read("sign.ps1")
    assert "Set-AuthenticodeSignature" in sign, "подпись идёт не через Authenticode"
    assert "TimestampServer" in sign, "нет метки времени — подпись умрёт с сертификатом"
    assert "New-SelfSignedCertificate" in sign, "нет режима проверки конвейера"

    workflow = ROOT / ".github" / "workflows" / "build-installer.yml"
    assert workflow.is_file(), "нет CI-сборки установщика"
    text = workflow.read_text(encoding="utf-8")
    assert "build-installer.ps1" in text, "CI не собирает установщик"
    assert "SIGNING_PFX_BASE64" in text, "CI не умеет подписывать"
    assert "Get-AuthenticodeSignature" in text, "CI не проверяет подпись"

    assert (ROOT / "docs" / "SIGNING.md").is_file(), "нет инструкции по сертификату"


def test_cs_installer_source_is_utf8_bom() -> None:
    """Кириллица в мастере: csc читает UTF-8 без BOM как ANSI."""
    data = (INSTALLER / "ZereSetup.cs").read_bytes()
    assert data.startswith(BOM), "ZereSetup.cs без UTF-8 BOM — русский текст станет кракозябрами"


def test_build_installer_wiring() -> None:
    """build-installer.ps1 собирает один exe: git-архив + payload + csc."""
    build = _read("build-installer.ps1")
    assert "csc.exe" in build, "не используется системный компилятор"
    assert "git archive" in build, "stage не формируется из git"
    assert "/resource:" in build and "payload.zip" in build, "архив не встраивается"
    assert "ZereSetup.exe" in build, "не задано имя установщика"
    assert "/codepage:65001" in build, "кодировка исходника не задана — кириллица сломается"


def test_version_sources_agree() -> None:
    """Версия задана в шести местах — они обязаны совпадать.

    Иначе установщик показывает одну версию, конфиг пишет другую, а сборка
    берёт третью: «обновил, но не отличить от старого».
    """
    config = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    # Источник истины для сборки — config/config.json.
    version = config["version"]

    assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"версия не semver: {version}"

    build = _read("build-setup.ps1")
    match = re.search(r"^\$version = '([^']+)'", build, re.M)
    assert match, "в build-setup.ps1 не найден $version"
    assert match.group(1) == version, "build-setup.ps1: $version != config.json"

    default_config = _read("install.ps1")
    match = re.search(r'\$DefaultConfigJson = @\'\s*\{\s*"version": "([^"]+)"', default_config)
    assert match, "в install.ps1 не найден DefaultConfigJson с версией"
    assert match.group(1) == version, "install.ps1: DefaultConfigJson != config.json"

    iss = _read("Zere.iss")
    match = re.search(r'#define MyAppVersion "([^"]+)"', iss)
    assert match, "в Zere.iss не найден MyAppVersion"
    assert match.group(1) == version, "Zere.iss: MyAppVersion != config.json"

    match = re.search(
        r'#define FileVersion "([\d.]+)"', iss
    )
    assert match, "в Zere.iss не найден FileVersion"
    assert match.group(1).startswith(version), "Zere.iss: FileVersion != config.json"

    python_config = (
        ROOT / "zere" / "core" / "configuration" / "zere_config.py"
    ).read_text(encoding="utf-8")
    match = re.search(r'version: str = "([^"]+)"', python_config)
    assert match, "в zere_config.py не найдена версия по умолчанию"
    assert match.group(1) == version, "zere_config.py: версия != config.json"

    csharp_config = (
        ROOT / "ZERE.Core" / "Configuration" / "ZereConfig.cs"
    ).read_text(encoding="utf-8")
    match = re.search(r'Version \{ get; set; \} = "([^"]+)"', csharp_config)
    assert match, "в ZereConfig.cs не найдена версия по умолчанию"
    assert match.group(1) == version, "ZereConfig.cs: версия != config.json"


def test_iss_gets_version_from_build() -> None:
    """Версию в .iss задаёт сборка: иначе она замирает и расходится с конфигом."""
    iss = _read("Zere.iss")
    assert "#ifndef MyAppVersion" in iss, (
        "MyAppVersion в Zere.iss не переопределяется через /DMyAppVersion"
    )

    build = _read("build-setup.ps1")
    assert '"/DMyAppVersion="' in build, (
        "build-setup.ps1 не передаёт версию в ISCC (/DMyAppVersion)"
    )


def test_build_version_has_build_number() -> None:
    """Четвёртое поле версии — номер сборки: две сборки одной версии различимы."""
    build = _read("build-setup.ps1")
    assert "git rev-list --count HEAD" in build, (
        "build-setup.ps1 не берёт номер сборки из git"
    )
    assert "$buildNumber" in build, "build-setup.ps1 не подставляет номер сборки"
    # Поле версии обязано собираться из трёх частей + номера сборки.
    assert "(($parts[0..2]) + $buildNumber) -join '.'" in build, (
        "FileVersion не собирается как major.minor.patch.build"
    )


def test_build_setup_ships_both_editions() -> None:
    """Дистрибутив по умолчанию несёт обе редакции, а не только Python."""
    build = _read("build-setup.ps1")
    match = re.search(r"\[string\]\$Edition = '(\w+)'", build)
    assert match, "в build-setup.ps1 не найден параметр -Edition"
    assert match.group(1) == "both", (
        f"по умолчанию собирается редакция {match.group(1)}, "
        "C#-редакция в дистрибутив не попадёт"
    )

    iss = _read("Zere.iss")
    assert "#ifndef Edition" in iss, "в Zere.iss нет переопределяемого Edition"
    match = re.search(r'#define Edition "(\w+)"', iss)
    assert match, "в Zere.iss не найден запасной Edition"
    assert match.group(1) == "both", "ручной ISCC соберёт не обе редакции"


def _windows_path(path: Path) -> str:
    """Путь так, как его видит Windows PowerShell.

    Под WSL каталог репозитория — /mnt/c/..., и Windows такого пути не знает:
    без перевода тест «проверял синтаксис» на несуществующем файле.
    """
    if os.name == "nt":
        return str(path)
    wslpath = shutil.which("wslpath")
    if wslpath:
        try:
            result = subprocess.run(
                [wslpath, "-w", str(path)], capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return path.as_posix().replace("/", chr(92))


def test_ps1_parse_powershell() -> None:
    """Синтаксис .ps1 через парсер PowerShell (пропускается вне Windows)."""
    ps = next(
        (
            p
            for p in (
                shutil.which("powershell.exe"),
                shutil.which("powershell"),
                shutil.which("pwsh"),
                shutil.which("pwsh.exe"),
            )
            if p
        ),
        None,
    )
    if not ps:
        print("SKIP  PowerShell недоступен — парсинг .ps1 пропущен")
        return
    for name in PS1_FILES:
        cmd = (
            "$e=$null;$t=$null;"
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{_windows_path(INSTALLER / name)}',"
            "[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count){$e|ForEach-Object{('{0}: {1}' -f $_.Extent.StartLineNumber,$_.Message)};"
            "exit 1}else{exit 0}"
        )
        proc = subprocess.run(
            [ps, "-NoProfile", "-Command", cmd],
            capture_output=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            f"{name}: ошибки парсинга:\n"
            + (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
        )


# ---------------------------------------------------------------------------
# Зависимости: регрессия на «установщик сказал, что всё создал, а ZERE падает
# с "No module named ..."». Проверяются три вещи: requirements.txt покрывает
# то, что импортирует рантайм; установщик проверяет весь список пакетов, а не
# два; шаг установки зависимостей не пропускается на частично готовом
# окружении. Плюс Setup.exe обязан сообщать о сбое, а не «Установка завершена».
# ---------------------------------------------------------------------------

# импорт в коде -> имя пакета в requirements.txt (имена расходятся)
IMPORT_TO_PACKAGE = {
    "PIL": "pillow",
    "faster_whisper": "faster-whisper",
    "sherpa_onnx": "sherpa-onnx",
    # пакет называется pywebview, а импортируется как webview
    "webview": "pywebview",
}

# Осознанно не объявляются в requirements.txt
IMPORT_EXEMPT = {
    "torch": "ставится отдельным окружением uv для Silero (~2 ГБ)",
}


def _requirements_packages() -> list[str]:
    """Имена пакетов из requirements.txt (без версий, маркеров и комментариев)."""
    names: list[str] = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=!~;\[ ]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def _runtime_imports() -> dict[str, str]:
    """Сторонние импорты рантайма (main.py + zere/): модуль -> файл."""
    std = set(sys.stdlib_module_names)
    local = {"zere", "tools", "scripts", "main"}
    found: dict[str, str] = {}
    files = sorted((ROOT / "zere").rglob("*.py"))
    files.append(ROOT / "main.py")
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:  # pragma: no cover — рабочий код парсится
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in std or name in local:
                    continue
                found.setdefault(name, str(path.relative_to(ROOT)))
    return found


def test_requirements_cover_runtime_imports() -> None:
    """Каждый импорт рантайма объявлен в requirements.txt.

    numpy не был объявлен: он приезжал «попутно» с onnxruntime/sherpa-onnx/
    soundfile, и там, где pip не дошёл до них, ZERE падал на `import numpy as np`
    в zere/voice/audio/.
    """
    declared = {n.lower().replace("_", "-") for n in _requirements_packages()}
    missing = []
    for module, where in sorted(_runtime_imports().items()):
        if module in IMPORT_EXEMPT:
            continue
        package = IMPORT_TO_PACKAGE.get(module, module)
        if package.lower().replace("_", "-") not in declared:
            missing.append(f"{module} ({where}) -> нет пакета {package}")
    assert not missing, "импорты рантайма без объявленной зависимости: " + "; ".join(missing)


def test_installer_verifies_every_requirement() -> None:
    """Таблица модулей установщика покрывает весь requirements.txt.

    Иначе добавили пакет в requirements.txt — и установщик его «не видит»:
    отметит зависимости установленными, а пакета нет.
    """
    text = _read("install.ps1")
    table = {
        m.group(1).lower().replace("_", "-")
        for m in re.finditer(
            r"@\{\s*Package\s*=\s*'([^']+)';\s*Module\s*=\s*'([^']+)'\s*\}", text
        )
    }
    assert table, "в install.ps1 нет таблицы проверяемых модулей"
    missing = [p for p in _requirements_packages() if p.lower().replace("_", "-") not in table]
    assert not missing, f"install.ps1 не проверяет пакеты: {missing}"
    assert "numpy" in table, "install.ps1 не проверяет numpy — старт ZERE снова может упасть"


def test_installer_reinstalls_deps_on_partial_env() -> None:
    """Частично установленное окружение не считается готовым.

    Раньше «зависимости установлены» означало «pip show faster-whisper и
    sherpa-onnx прошли»: если pip падал в середине списка, эти два пакета уже
    стояли, шаг установки пропускался целиком — и ZERE падал с
    «No module named ...», хотя установщик отчитался об успехе.
    """
    text = _read("install.ps1")
    assert "function Get-MissingModules" in text, "нет проверки всего списка модулей"
    assert re.search(r"\$depsOk\s*=\s*\(\$depState\.Ok", text), (
        "нет вердикта по всему списку зависимостей"
    )
    assert re.search(
        r"\$needVenv\s*=\s*\(-not \$venvState\.Venv\)\s*-or\s*\(-not \$depsOk\)", text
    ), "needVenv не учитывает недостающие зависимости — шаг будет пропущен"
    assert "pip install -r $reqPath" in text, "pip не запускается по requirements.txt"
    smoke = text.split("function Invoke-SmokeTest", 1)[1].split("\nfunction ", 1)[0]
    assert "Get-MissingModules" in smoke, "smoke-тест не проверяет зависимости"


def test_installer_writes_log() -> None:
    """Полный лог установки: без него «какие файлы не найдены» не разобрать."""
    text = _read("install.ps1")
    assert "Start-InstallLog" in text and "install-log.txt" in text, "нет лога установки"
    assert "[System.IO.File]::AppendAllText" in text, "лог не пишется построчно"
    assert "installer/install-log.txt" in (ROOT / ".gitignore").read_text(encoding="utf-8"), (
        "лог установки не добавлен в .gitignore"
    )


def test_default_config_covers_project_config() -> None:
    """Конфиг по умолчанию в установщике не отстаёт от config/config.json.

    Установщик сам создаёт config/config.json на новой машине, поэтому ключ,
    добавленный в проект и забытый здесь (audioProcessing), до новых установок
    не доезжает.
    """
    project = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    text = _read("install.ps1")
    match = re.search(r"\$DefaultConfigJson = @'\s*(\{.*?\})\s*'@", text, re.S)
    assert match, "в install.ps1 не найден $DefaultConfigJson"
    default = json.loads(match.group(1))
    only_default = sorted(set(default) - set(project))
    only_project = sorted(set(project) - set(default))
    assert not only_default and not only_project, (
        f"набор ключей разошёлся: только в установщике {only_default}, "
        f"только в config.json {only_project}"
    )


def test_iss_has_utf8_bom() -> None:
    """Кириллица в MsgBox из [Code] требует BOM: без него Inno читает файл как ANSI."""
    data = (INSTALLER / "Zere.iss").read_bytes()
    assert data.startswith(BOM), "Zere.iss без UTF-8 BOM — кириллица в мастере станет кракозябрами"


def test_setup_reports_install_failure() -> None:
    """Setup.exe обязан проверить код возврата install.ps1 и сказать о сбое.

    Через [Run] мастер показывал «Установка завершена», даже когда pip не
    поставил зависимости: пользователь узнавал об этом только при запуске ZERE.
    """
    iss = _read("Zere.iss")
    assert "CurStepChanged" in iss and "ssPostInstall" in iss, (
        "в Zere.iss нет [Code] с запуском настройки на шаге postinstall"
    )
    assert "ewWaitUntilTerminated" in iss, "install.ps1 не ожидается до конца"
    assert re.search(r"ResultCode\s*<>\s*0", iss), "код возврата install.ps1 не проверяется"
    assert "install-log.txt" in iss, "мастер не подсказывает, где искать лог"
    assert 'ExpandConstant(\'{app}\\installer\\install.ps1\')' in iss, (
        "install.ps1 запускается не из каталога установки"
    )


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов установщика")


if __name__ == "__main__":
    sys.exit(main())
