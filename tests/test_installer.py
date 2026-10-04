"""Тесты установщика JARVIS (installer/).

Проверяют то, что ломается чаще всего и что невозможно поймать прогоном
на одной машине:

- UTF-8 BOM у .ps1 (иначе Windows PowerShell 5.1 читает файл как ANSI
  и кириллица в комментариях/строках ломает парсинг);
- CRLF и чистый ASCII у .bat (кодировка cmd);
- контрольные SHA-256/размеры скачиваемых артефактов в install.ps1;
- связность файлов: install.ps1 <-> JarvisLauncher.bat <-> Jarvis.iss
  <-> build-setup.ps1 <-> uninstall.ps1;
- синтаксис .ps1 через парсер PowerShell (только если PowerShell доступен,
  на Linux — пропускается);
- деинсталлятор не удаляет исходный код.

Запуск:
- `python3 tests/test_installer.py` — без зависимостей;
- `pytest tests/ -q` — в CI (функции test_* без аргументов).
"""

from __future__ import annotations

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
    "Piper": (
        "f3c58906402b24f3a96d92145f58acba6d86c9b5db896d207f78dc80811efcea",
        22477236,
    ),
    "PiperVoice": (
        "72a5f88e0b20928064eb45d88e1daa21f8af62d18613580d32cbb4aed48dcf7f",
        63201294,
    ),
    "PiperVoiceJs": (
        "706a4fb17bc304abd07809b552deae615e64dcbffbfbd09854ba37ca59e88117",
        4882,
    ),
}

PS1_FILES = ("install.ps1", "uninstall.ps1", "build-setup.ps1")
BAT_FILES = ("JarvisLauncher.bat", "Install-Jarvis.bat", "Uninstall-Jarvis.bat")


def _read(name: str) -> str:
    return (INSTALLER / name).read_text(encoding="utf-8-sig")


def test_installer_files_exist() -> None:
    expected = set(PS1_FILES) | set(BAT_FILES) | {"Jarvis.iss"}
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
    assert "JarvisLauncher.bat" in text, "install.ps1 не копирует лаунчер"
    assert "-CheckOnly" in text, "install.ps1 нет режима -CheckOnly"
    for pname in (
        "Prefix", "Edition", "Model", "SkipOllama", "SkipVoice",
        "SkipShortcuts", "CheckOnly", "Yes", "NoLaunch",
    ):
        assert f"${pname}" in text, f"install.ps1 нет параметра ${pname}"


def test_launcher_prefers_venv() -> None:
    """Лаунчер должен запускать .venv, затем .NET, затем системный python."""
    data = (INSTALLER / "JarvisLauncher.bat").read_bytes().decode("ascii")
    venv_pos = data.find(".venv\\Scripts\\python.exe")
    dotnet_pos = data.find("publish\\app\\JARVIS.App.exe")
    assert 0 < venv_pos < dotnet_pos, "порядок запуска редакций нарушен"


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
    banned_dirs = {"jarvis", "panel", "docs", "tests", "installer"}
    # Отдельные файлы-исходники: запрещено удалять
    banned_files = {"main.py", "requirements.txt", "AGENTS.md", "README.md", "JARVIS.slnx"}
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
        r"if \(\$PurgeData\) \{[^}]*?Join-Path \$Prefix 'jarvis\.db'",
        text,
        re.S,
    ), "jarvis.db удаляется без привязки к флагу -PurgeData"


def test_inno_script_wiring() -> None:
    iss = _read("Jarvis.iss")
    assert "install.ps1" in iss, "Jarvis.iss не запускает install.ps1"
    assert "uninstall.ps1" in iss, "Jarvis.iss не запускает uninstall.ps1"
    assert "PrivilegesRequired=lowest" in iss, "установка должна быть per-user"
    assert "JarvisInstaller" in iss, "нет имени дистрибутива (JarvisInstaller.exe)"
    build = _read("build-setup.ps1")
    assert "Jarvis.iss" in build, "build-setup.ps1 не компилирует Jarvis.iss"
    assert "git archive" in build or "ls-files" in build, (
        "build-setup.ps1 не формирует stage из git"
    )
    assert "ISCC" in build, "build-setup.ps1 не ищет ISCC.exe"


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
            f"'{(INSTALLER / name).as_posix().replace('/', chr(92))}',"
            "[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count){$e|%%{('{0}: {1}' -f $_.Extent.StartLineNumber,$_.Message)};"
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
