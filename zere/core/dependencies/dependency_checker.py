"""Порт ZERE.Core/Dependencies/DependencyChecker.cs (+ DependencyResult, CheckStatus)."""

from __future__ import annotations

import enum
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests

from zere import paths
from zere.ai.ollama_url_resolver import OllamaUrlResolver
from zere.core.configuration.zere_config import ZereConfig

# CreateNoWindow = true (Windows-only цель)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class CheckStatus(enum.Enum):
    Ok = 0
    Missing = 1
    Warning = 2


@dataclass
class DependencyResult:
    name: str = ""
    status: CheckStatus = CheckStatus.Ok
    critical: bool = False
    message: str = ""
    install_url: Optional[str] = None
    install_command: Optional[str] = None


def _read_line() -> Optional[str]:
    """Console.ReadLine()."""
    try:
        return input()
    except EOFError:
        return None


def _read_answer() -> Optional[str]:
    """Console.ReadLine()?.Trim().ToLower()."""
    line = _read_line()
    return line.strip().lower() if line is not None else None


def _is_yes(answer: Optional[str]) -> bool:
    return answer == "д" or answer == "да" or answer == "y" or answer == "yes"


def _pause() -> None:
    """Console.ReadLine() — ожидание Enter."""
    _read_line()


def _open_url(url: str) -> None:
    """Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true })."""
    if os.name == "nt":
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        subprocess.Popen([url], shell=True, creationflags=_NO_WINDOW)


def _chattts_availability() -> "tuple[bool, str]":
    """Есть ли ChatTTS с зависимостями — БЕЗ импорта (веса не грузятся).

    Зеркало ChatTTSManager.availability(), но без импорта голосового пакета:
    проверка зависимостей ядра не должна тянуть голосовой модуль.
    """
    missing = [
        name
        for name in ("ChatTTS", "torch", "soundfile")
        if importlib.util.find_spec(name) is None
    ]

    if missing:
        return False, "нет модулей: " + ", ".join(missing)

    return True, "ChatTTS доступен"


class DependencyChecker:
    def __init__(self, config: ZereConfig, *, cloud_available: bool = False) -> None:
        self._config = config
        self._http = requests.Session()
        self._results: List[DependencyResult] = []
        # Настроен облачный API-ключ (config/ai.json или окружение владельца):
        # тогда Ollama и локальная модель — не критические, ZERE стартует
        # и работает через облако (панель: «Подключено: облачная модель»).
        self._cloud_available = cloud_available

        self._ollama_url = "http://localhost:11434"
        resolved = OllamaUrlResolver.resolve()
        if resolved:
            self._ollama_url = resolved

        # HttpClient: BaseAddress = _ollamaUrl, Timeout = 3 секунды
        self._timeout = 3

    def _local_critical(self) -> bool:
        """Локальная модель критична, только если облачного ключа нет."""
        return not self._cloud_available

    # ------------------------------------------------------------------ API

    def run_all(self) -> List[DependencyResult]:
        self._results.clear()

        self._check_ollama()
        self._check_model()
        self._check_sqlite()
        self._check_whisper()
        self._check_chattts()

        return list(self._results)

    def all_critical_passed(self) -> bool:
        return all(
            r.status == CheckStatus.Ok
            for r in self._results
            if r.critical
        )

    def print_report(self) -> None:
        print("Проверка зависимостей:\n")

        for r in self._results:
            if r.status == CheckStatus.Ok:
                icon = "[OK]"
            elif r.status == CheckStatus.Missing:
                icon = "[!!]"
            elif r.status == CheckStatus.Warning:
                icon = "[~~]"
            else:
                icon = "[??]"

            line = f"  {icon} {r.name}"

            if r.status != CheckStatus.Ok and r.message:
                line += f" — {r.message}"

            print(line)

            if r.status != CheckStatus.Ok:
                if r.install_command:
                    print(f"    Команда: {r.install_command}")
                if r.install_url:
                    print(f"    Ссылка: {r.install_url}")

        print()

    def offer_install(self) -> None:
        missing = [
            r for r in self._results
            if r.status != CheckStatus.Ok and r.critical
        ]

        if len(missing) == 0:
            return

        print("Хотите установить недостающие зависимости? (д/н): ")

        answer = _read_answer()

        if not _is_yes(answer):
            return

        print()

        for dep in missing:
            print(f"  Установить {dep.name}? (д/н): ", end="")
            choice = _read_answer()

            if _is_yes(choice):
                print()
                self._install_dependency(dep)
                print()
            else:
                print(f"  Пропущено: {dep.name}\n")

        # Offer to install non-critical voice dependencies
        voice_missing = [
            r for r in self._results
            if r.status != CheckStatus.Ok
            and not r.critical
            and ("Whisper" in r.name or "ChatTTS" in r.name)
        ]

        if len(voice_missing) > 0:
            print("\nГолосовые компоненты не установлены:")
            for dep in voice_missing:
                print(f"  - {dep.name}")

            if self._ask_confirmation("\nУстановить голосовые компоненты?"):
                print()
                for dep in voice_missing:
                    print(f"  Установить {dep.name}? (д/н): ", end="")
                    choice = _read_answer()

                    if _is_yes(choice):
                        print()
                        self._install_dependency(dep)
                        print()
                    else:
                        print(f"  Пропущено: {dep.name}\n")

        print("Повторная проверка...\n")
        self.run_all()
        self.print_report()

    # ------------------------------------------------------------ служебные

    @staticmethod
    def _ask_confirmation(prompt: str) -> bool:
        print(f"  {prompt} (д/н): ", end="")
        answer = _read_answer()
        return _is_yes(answer)

    @staticmethod
    def _check_winget() -> bool:
        try:
            process = subprocess.run(
                ["winget", "--version"],
                capture_output=True,
                timeout=3,
                creationflags=_NO_WINDOW,
            )
            return process.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _command_exists(command: str) -> bool:
        try:
            process = subprocess.run(
                [command, "--version"],
                capture_output=True,
                timeout=3,
                creationflags=_NO_WINDOW,
            )
            return process.returncode == 0
        except (FileNotFoundError, OSError):
            # Command not found on system PATH / Process start failed
            return False
        except subprocess.TimeoutExpired:
            return False

    @staticmethod
    def _run_streaming(command: str) -> int:
        """Запуск команды через cmd.exe с перехватом вывода и печатью строк.

        Команда передаётся СТРОКОЙ и с `shell=True` — только так cmd.exe получает
        её дословно. Вариант `subprocess.run(["cmd.exe", "/c", command])` ломается
        на кавычках: Python экранирует внутренние кавычки обратными слэшами, а
        cmd.exe такого экранирования не понимает. Команда установки ChatTTS
        (`"<venv>\\python.exe" -m pip install ...`) из-за этого превращалась в
        `"\\"<venv>\\python.exe\\" -m pip ..."` и падала с «не является внутренней
        или внешней командой» — воспроизведено и закрыто тестом
        tests/test_chattts.py::test_command_runner_passes_command_verbatim.
        """
        process = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            creationflags=_NO_WINDOW,
        )

        for line in process.stdout.decode(encoding="utf-8", errors="replace").splitlines():
            if line:
                print(f"    {line}")
        for line in process.stderr.decode(encoding="utf-8", errors="replace").splitlines():
            if line:
                print(f"    {line}")

        return process.returncode

    def _execute_command_with_confirmation(self, command: str, description: str) -> None:
        print(f"  {description}")
        print(f"  Команда: {command}")

        if not self._ask_confirmation("Выполнить?"):
            print("  Пропущено.")
            return

        try:
            exit_code = self._run_streaming(command)

            if exit_code == 0:
                print("  Готово.")
            else:
                print(f"  Ошибка (код {exit_code}).")
        except Exception as ex:
            print(f"  Ошибка: {ex}")

    # ------------------------------------------------------------ установка

    def _install_dependency(self, dep: DependencyResult) -> None:
        if dep.name == "Ollama":
            self._install_ollama()
        elif dep.name.startswith("Модель"):
            self._install_model()
        elif dep.name.startswith("SQLite"):
            self._install_sqlite()
        elif "Whisper" in dep.name:
            self._install_whisper()
        elif "ChatTTS" in dep.name:
            self._install_chattts()
        else:
            print(f"  Нет способа автоматической установки: {dep.name}")

    def _install_ollama(self) -> None:
        print("  Проверяю, установлен ли Ollama...")

        if self._command_exists("ollama"):
            print("  Ollama найдена. Запускаю сервер...")
            self._start_ollama()
            return

        print("  Ollama не найдена.")

        if self._check_winget():
            print("  winget доступен. Предлагаю автоматическую установку.")
            self._execute_command_with_confirmation(
                "winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements",
                "Устанавливаю Ollama через winget...",
            )
        else:
            print("  winget недоступен.")
            print("  Скачайте Ollama вручную:")
            print("  https://ollama.com/download\n")

            if not self._ask_confirmation("Открыть страницу загрузки в браузере?"):
                print("  Установите Ollama вручную и нажмите Enter...")
                _pause()
            else:
                try:
                    _open_url("https://ollama.com/download")
                except Exception:
                    print("  Не удалось открыть браузер. Перейдите по ссылке вручную.")

                print("  После установки нажмите Enter...")
                _pause()

        print("  Запускаю Ollama...")
        self._start_ollama()

    def _start_ollama(self) -> None:
        try:
            # Fire-and-forget: ollama serve живёт в фоне всю сессию ZERE
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )

            time.sleep(3)

            try:
                response = self._http.get(
                    f"{self._ollama_url}/api/tags", timeout=self._timeout
                )
                if response.status_code < 400:
                    print("  Ollama запущена.")
                    return
            except requests.RequestException:
                # HTTP request failed — Ollama may not be running
                pass

            print("  Ollama запущена, но сервер может ещё стартовать.")
        except Exception as ex:
            print(f"  Не удалось запустить Ollama: {ex}")
            print("  Запустите вручную: ollama serve")

    def _install_model(self) -> None:
        if not self._command_exists("ollama"):
            print("  Ollama не установлена. Сначала установите Ollama.")
            return

        command = f"ollama pull {self._config.Model}"
        print(f"  Скачиваю модель {self._config.Model}...")
        print(f"  Команда: {command}")

        if not self._ask_confirmation("Выполнить?"):
            print("  Пропущено.")
            return

        print("  Это может занять несколько минут.\n")

        try:
            process = subprocess.run(
                ["ollama", "pull", self._config.Model],
                capture_output=True,
                creationflags=_NO_WINDOW,
            )

            for line in process.stdout.decode(encoding="utf-8", errors="replace").splitlines():
                if line:
                    print(f"    {line}")
            for line in process.stderr.decode(encoding="utf-8", errors="replace").splitlines():
                if line:
                    print(f"    {line}")

            if process.returncode == 0:
                print(f"\n  Модель {self._config.Model} установлена.")
            else:
                print(f"\n  Ошибка установки модели (код {process.returncode}).")
        except Exception as ex:
            print(f"  Ошибка: {ex}")

    def _install_sqlite(self) -> None:
        print("  Проверяю NuGet пакеты...")

        project_dir = self._find_project_root()

        if not project_dir:
            print("  Не удалось найти корень проекта.")
            print("  Выполните вручную: dotnet restore")
            return

        try:
            process = subprocess.run(
                ["dotnet", "restore"],
                cwd=project_dir,
                capture_output=True,
                creationflags=_NO_WINDOW,
            )

            if process.returncode == 0:
                print("  NuGet пакеты восстановлены.")
            else:
                print("  Ошибка восстановления. Выполните: dotnet restore")
        except Exception as ex:
            print(f"  Ошибка: {ex}")
            print("  Выполните вручную: dotnet restore")

    def _install_whisper(self) -> None:
        print("  Модель Whisper (ggml-base.bin) не найдена.")

        # C#: AppContext.BaseDirectory/../../../../ → PROJECT_ROOT (zere.paths)
        models_dir = paths.whisper_models_dir()
        models_dir.mkdir(parents=True, exist_ok=True)

        target_file = models_dir / "ggml-base.bin"

        if target_file.exists():
            print("  Модель уже скачана.")
            return

        url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
        print("  Скачиваю модель Whisper (~150 МБ)...")
        print(f"  Источник: {url}")
        print(f"  Куда: {target_file}\n")

        if not self._ask_confirmation("Скачать?"):
            print("  Пропущено.")
            return

        # Try curl first (available on most Windows 10+)
        if self._command_exists("curl"):
            self._execute_command_with_confirmation(
                f'curl -L -o "{target_file}" "{url}"',
                "Скачиваю через curl...",
            )
        # Fallback to PowerShell Invoke-WebRequest
        elif self._command_exists("powershell"):
            self._execute_command_with_confirmation(
                f"powershell -Command \"Invoke-WebRequest -Uri '{url}' -OutFile '{target_file}'\"",
                "Скачиваю через PowerShell...",
            )
        else:
            print("  Neither curl nor PowerShell found.")
            print("  Скачайте вручную:")
            print(f"  {url}")
            print(f"  Сохраните в: {target_file}")
            return

        if target_file.exists():
            print("  Модель Whisper установлена.")
        else:
            print("  Ошибка: файл не был скачан.")

    def _install_chattts(self) -> None:
        """Установка ChatTTS: только pip, бинарников и zip-архивов нет.

        ChatTTS публикуется на PyPI как sdist (сборка из исходников) и тянет
        torch/torchaudio/numba — это ~2–3 ГБ и несколько минут. Зависимости
        имеют колёса для Python 3.10–3.14 (проверено по PyPI: torch 2.14,
        torchaudio 2.11, numba 0.68, pybase16384 0.3.9), поэтому ставим в
        текущее окружение — тот же интерпретатор, которым запущен ZERE.
        Веса модели движок скачивает сам при первой загрузке.
        """
        print("  ChatTTS (TTS) не найден.")
        print("  Установка: pip install ChatTTS soundfile")
        print("  Это ~2–3 ГБ (torch) и несколько минут: ChatTTS собирается из исходников.")
        print(f"  Окружение: {sys.executable}\n")

        self._execute_command_with_confirmation(
            f'"{sys.executable}" -m pip install ChatTTS soundfile',
            "Устанавливаю ChatTTS...",
        )

        ok, reason = _chattts_availability()

        if ok:
            print("  ChatTTS установлен.")
            return

        print(f"  ChatTTS всё ещё недоступен: {reason}")
        print("  Если pip не смог собрать зависимости — поставьте движок отдельным")
        print("  окружением через uv (Python 3.12, системный Python не трогается):")
        print('    tools\\uv.exe run --python 3.12 --with ChatTTS --with soundfile python -c "import ChatTTS"')
        print("  Подробности: https://github.com/2Noise/ChatTTS\n")

    @staticmethod
    def _find_project_root() -> Optional[str]:
        directory = Path.cwd()

        while True:
            if (directory / "ZERE.slnx").exists():
                return str(directory)

            parent = directory.parent
            if parent == directory:
                return None
            directory = parent

    # -------------------------------------------------------------- проверки

    def _check_ollama(self) -> None:
        try:
            response = self._http.get(
                f"{self._ollama_url}/api/tags", timeout=self._timeout
            )

            if response.status_code < 400:
                self._results.append(
                    DependencyResult(
                        name="Ollama",
                        status=CheckStatus.Ok,
                        critical=self._local_critical(),
                    )
                )
            else:
                self._results.append(
                    DependencyResult(
                        name="Ollama",
                        status=CheckStatus.Missing,
                        critical=self._local_critical(),
                        message="Сервер отвечает, но вернул ошибку.",
                    )
                )
        except Exception:
            self._results.append(
                DependencyResult(
                    name="Ollama",
                    status=CheckStatus.Missing,
                    critical=self._local_critical(),
                    message=f"Сервер недоступен ({self._ollama_url})",
                    install_url="https://ollama.com/download",
                    install_command="winget install Ollama.Ollama"
                    if self._check_winget()
                    else None,
                )
            )

    def _check_model(self) -> None:
        try:
            response = self._http.get(
                f"{self._ollama_url}/api/tags", timeout=self._timeout
            )

            if response.status_code >= 400:
                self._results.append(
                    DependencyResult(
                        name=f"Модель ({self._config.Model})",
                        status=CheckStatus.Missing,
                        critical=self._local_critical(),
                        message="Ollama недоступна.",
                    )
                )
                return

            # JsonDocument.Parse(json) — при битом JSON исключение уйдёт в catch
            data = response.json()

            models = []
            for m in data["models"]:
                value = m["name"]
                models.append(value if isinstance(value, str) else "")

            found = any(
                m.lower().startswith(self._config.Model.lower()) for m in models
            )

            if found:
                self._results.append(
                    DependencyResult(
                        name=f"Модель ({self._config.Model})",
                        status=CheckStatus.Ok,
                        critical=self._local_critical(),
                    )
                )
            else:
                available = ", ".join(models[:5]) if len(models) > 0 else "нет моделей"

                self._results.append(
                    DependencyResult(
                        name=f"Модель ({self._config.Model})",
                        status=CheckStatus.Missing,
                        critical=self._local_critical(),
                        message=f"Не найдена. Доступные: {available}",
                        install_command=f"ollama pull {self._config.Model}",
                    )
                )
        except Exception:
            self._results.append(
                DependencyResult(
                    name=f"Модель ({self._config.Model})",
                    status=CheckStatus.Warning,
                    critical=self._local_critical(),
                    message="Не удалось проверить.",
                )
            )

    def _check_sqlite(self) -> None:
        try:
            # C#: LocalApplicationData/ZERE/zere.db → путь БД из zere.paths
            db_path = paths.db_path()
            db_path.parent.mkdir(parents=True, exist_ok=True)

            import sqlite3  # лениво: соответствует DllNotFoundException в C#

            connection = sqlite3.connect(str(db_path))
            try:
                connection.execute("SELECT 1")
            finally:
                connection.close()

            self._results.append(
                DependencyResult(
                    name="SQLite",
                    status=CheckStatus.Ok,
                    critical=True,
                )
            )
        except ImportError:
            # DllNotFoundException: Native SQLite библиотека не найдена
            self._results.append(
                DependencyResult(
                    name="SQLite",
                    status=CheckStatus.Missing,
                    critical=True,
                    message="Native SQLite библиотека не найдена. Нужно восстановить пакеты.",
                )
            )
        except Exception as ex:
            self._results.append(
                DependencyResult(
                    name="SQLite",
                    status=CheckStatus.Missing,
                    critical=True,
                    message=str(ex),
                )
            )

    def _check_whisper(self) -> None:
        if not self._config.VoiceEnabled:
            self._results.append(
                DependencyResult(
                    name="Whisper (голос)",
                    status=CheckStatus.Ok,
                    critical=False,
                    message="Отключен в конфиге.",
                )
            )
            return

        # C#: AppContext.BaseDirectory/../../../../ → zere.paths
        model_path = paths.whisper_models_dir() / "ggml-base.bin"

        if model_path.exists():
            self._results.append(
                DependencyResult(
                    name="Whisper (модель)",
                    status=CheckStatus.Ok,
                    critical=False,
                )
            )
        else:
            self._results.append(
                DependencyResult(
                    name="Whisper (модель)",
                    status=CheckStatus.Missing,
                    critical=False,
                    message=f"Файл не найден: {model_path}",
                    install_url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
                )
            )

    def _check_chattts(self) -> None:
        """ChatTTS (TTS) — замена Piper: бинарников нет, только pip-пакет.

        critical=False: без TTS ZERE работает в текстовом режиме. Проверка
        дешёвая — `importlib.find_spec` без импорта, веса не грузятся.
        """
        if not self._config.VoiceEnabled:
            self._results.append(
                DependencyResult(
                    name="ChatTTS (TTS)",
                    status=CheckStatus.Ok,
                    critical=False,
                    message="Отключен в конфиге.",
                )
            )
            return

        ok, reason = _chattts_availability()

        if ok:
            self._results.append(
                DependencyResult(
                    name="ChatTTS (TTS)",
                    status=CheckStatus.Ok,
                    critical=False,
                    message="Голос ChatTTS доступен (модель грузится при первом синтезе).",
                )
            )
            return

        self._results.append(
            DependencyResult(
                name="ChatTTS (TTS)",
                status=CheckStatus.Missing,
                critical=False,
                message=f"{reason} (нужно: pip install ChatTTS soundfile — ~2–3 ГБ)",
                install_url="https://github.com/2Noise/ChatTTS",
            )
        )

    def offer_voice_install(self) -> None:
        voice_missing = [
            r for r in self._results
            if r.status != CheckStatus.Ok
            and ("Whisper" in r.name or "ChatTTS" in r.name)
        ]

        if len(voice_missing) == 0:
            return

        print("Голосовые компоненты не установлены:")
        for dep in voice_missing:
            print(f"  - {dep.name} — {dep.message}")

        print("\nУстановить голосовые компоненты? (д/н): ", end="")
        answer = _read_answer()

        if not _is_yes(answer):
            return

        print()

        for dep in voice_missing:
            print(f"  Установить {dep.name}? (д/н): ", end="")
            choice = _read_answer()

            if _is_yes(choice):
                print()
                self._install_dependency(dep)
                print()
            else:
                print(f"  Пропущено: {dep.name}\n")

        print("Повторная проверка...\n")
        self.run_all()
        self.print_report()

    def close(self) -> None:
        """IDisposable.Dispose()."""
        self._http.close()
