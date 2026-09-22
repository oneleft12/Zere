"""Порт JARVIS.Core/Dependencies/DependencyChecker.cs (+ DependencyResult, CheckStatus)."""

from __future__ import annotations

import enum
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests

from jarvis import paths
from jarvis.ai.ollama_url_resolver import OllamaUrlResolver
from jarvis.core.configuration.jarvis_config import JarvisConfig

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


class DependencyChecker:
    def __init__(self, config: JarvisConfig) -> None:
        self._config = config
        self._http = requests.Session()
        self._results: List[DependencyResult] = []

        self._ollama_url = "http://localhost:11434"
        resolved = OllamaUrlResolver.resolve()
        if resolved:
            self._ollama_url = resolved

        # HttpClient: BaseAddress = _ollamaUrl, Timeout = 3 секунды
        self._timeout = 3

    # ------------------------------------------------------------------ API

    def run_all(self) -> List[DependencyResult]:
        self._results.clear()

        self._check_ollama()
        self._check_model()
        self._check_sqlite()
        self._check_whisper()
        self._check_piper()

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
            and ("Whisper" in r.name or "Piper" in r.name)
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
    def _run_streaming(command_line: str, shell_args: List[str]) -> int:
        """Запуск с перехватом вывода (stdout+stderr) и печатью строк с отступом."""
        process = subprocess.run(
            shell_args,
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
            exit_code = self._run_streaming(command, ["cmd.exe", "/c", command])

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
        elif "Piper" in dep.name:
            self._install_piper()
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
            # Fire-and-forget: ollama serve живёт в фоне всю сессию JARVIS
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

        # C#: AppContext.BaseDirectory/../../../../ → PROJECT_ROOT (jarvis.paths)
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

    def _install_piper(self) -> None:
        print("  Piper (TTS) не найден.")

        # C#: AppContext.BaseDirectory/../../../../ → PROJECT_ROOT (jarvis.paths)
        piper_dir = paths.piper_dir()
        piper_dir.mkdir(parents=True, exist_ok=True)

        # Check if piper.exe exists
        piper_exe = piper_dir / "piper.exe"
        piper_linux = piper_dir / "piper"

        if not piper_exe.exists() and not piper_linux.exists():
            print("  Piper не установлен.")

            # Try to find piper_windows_amd64.zip in common locations
            zip_path = self._find_piper_zip()

            if zip_path is not None:
                print(f"  Найден архив: {zip_path}")
                print("  Распаковываю...")

                if self._extract_piper_zip(zip_path, piper_dir):
                    print("  Piper установлен.")
                else:
                    print("  Ошибка распаковки. Установите вручную.")
                    self._offer_manual_piper_install(piper_dir)
            else:
                print("  Архив piper_windows_amd64.zip не найден.")
                print("  Источник: https://github.com/rhasspy/piper/releases\n")

                self._offer_manual_piper_install(piper_dir)

        # Check for voice models (Directory.GetFiles(piperDir, "*.onnx") — верхний уровень)
        onnx_files = list(piper_dir.glob("*.onnx"))
        if len(onnx_files) == 0:
            print("  Голосовые модели не найдены.")
            print("  Нужна модель ru_RU-irina-medium.onnx\n")

            if self._ask_confirmation("Скачать русскую голосовую модель?"):
                voice_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx"
                voice_target = piper_dir / "ru_RU-irina-medium.onnx"

                if self._command_exists("curl"):
                    self._execute_command_with_confirmation(
                        f'curl -L -o "{voice_target}" "{voice_url}"',
                        "Скачиваю голосовую модель...",
                    )
                elif self._command_exists("powershell"):
                    self._execute_command_with_confirmation(
                        f"powershell -Command \"Invoke-WebRequest -Uri '{voice_url}' -OutFile '{voice_target}'\"",
                        "Скачиваю голосовую модель через PowerShell...",
                    )

                # Also download the JSON config for the voice
                config_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json"
                config_target = piper_dir / "ru_RU-irina-medium.onnx.json"

                if self._command_exists("curl"):
                    self._execute_command_with_confirmation(
                        f'curl -L -o "{config_target}" "{config_url}"',
                        "Скачиваю конфигурацию голоса...",
                    )

                if voice_target.exists():
                    print("  Голосовая модель установлена.")
                else:
                    print("  Ошибка: модель не была скачана.")

    def _find_piper_zip(self) -> Optional[str]:
        # Search common locations for piper_windows_amd64.zip
        search_paths = [
            # Downloads folder
            Path.home() / "Downloads",
            # Desktop
            Path.home() / "Desktop",
            # Current directory
            Path.cwd(),
            # Project root
            Path(self._find_project_root()) if self._find_project_root() else Path(""),
        ]

        zip_names = [
            "piper_windows_amd64.zip",
            "piper-windows-amd64.zip",
            "piper_windows.zip",
        ]

        for directory in search_paths:
            directory_str = str(directory)
            if not directory_str or not directory.exists():
                continue

            for name in zip_names:
                path = directory / name
                if path.exists():
                    return str(path)

            # Also search for any piper*.zip
            try:
                piper_zips = list(directory.glob("piper*.zip"))
                if len(piper_zips) > 0:
                    return str(piper_zips[0])
            except OSError:
                # Ignore access errors
                pass

        return None

    def _extract_piper_zip(self, zip_path: str, target_dir: Path) -> bool:
        try:
            # Use PowerShell to extract (available on all Windows 10+)
            extract_dir = target_dir / "_temp_piper"
            extract_dir.mkdir(parents=True, exist_ok=True)

            print(f"  Распаковываю в {extract_dir}...")

            process = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Expand-Archive -Path '{zip_path}' -DestinationPath '{extract_dir}' -Force",
                ],
                capture_output=True,
                timeout=30,
                creationflags=_NO_WINDOW,
            )

            if process.returncode != 0:
                error = process.stderr.decode(encoding="utf-8", errors="replace")
                print(f"  Ошибка распаковки: {error}")
                return False

            # Find piper.exe in extracted files
            piper_exe = self._find_file_recursive(str(extract_dir), "piper.exe")

            if piper_exe is None:
                print("  piper.exe не найден в архиве.")
                return False

            # Move piper.exe to target directory
            target_exe = target_dir / "piper.exe"
            shutil.copy2(piper_exe, target_exe)

            # Also copy any .dll files from the same directory
            exe_dir = Path(piper_exe).parent
            if exe_dir is not None:
                for dll in exe_dir.glob("*.dll"):
                    target_dll = target_dir / dll.name
                    if not target_dll.exists():
                        shutil.copy2(dll, target_dll)

            # Cleanup temp directory
            try:
                shutil.rmtree(extract_dir)
            except OSError:
                pass

            print("  Piper установлен успешно.")
            return True
        except subprocess.TimeoutExpired:
            print("  Ошибка: процесс распаковки не завершился за 30 секунд.")
            return False
        except Exception as ex:
            print(f"  Ошибка: {ex}")
            return False

    @staticmethod
    def _find_file_recursive(dir_path: str, file_name: str) -> Optional[str]:
        try:
            file = Path(dir_path) / file_name
            if file.exists():
                return str(file)

            for sub_dir in Path(dir_path).iterdir():
                if sub_dir.is_dir():
                    result = DependencyChecker._find_file_recursive(str(sub_dir), file_name)
                    if result is not None:
                        return result
        except OSError:
            # Ignore access errors
            pass

        return None

    @staticmethod
    def _offer_manual_piper_install(piper_dir: Path) -> None:
        if DependencyChecker._ask_confirmation(
            "Открыть страницу загрузки Piper в браузере?"
        ):
            try:
                _open_url("https://github.com/rhasspy/piper/releases")
            except Exception:
                print("  Не удалось открыть браузер.")

        print("\n  Скачайте piper_windows_amd64.zip")
        print("  Положите его в папку Downloads или на Рабочий стол")
        print(f"  или распакуйте piper.exe в: {piper_dir}\n")
        print("  После установки нажмите Enter...")
        _pause()

    @staticmethod
    def _find_project_root() -> Optional[str]:
        directory = Path.cwd()

        while True:
            if (directory / "JARVIS.slnx").exists():
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
                        critical=True,
                    )
                )
            else:
                self._results.append(
                    DependencyResult(
                        name="Ollama",
                        status=CheckStatus.Missing,
                        critical=True,
                        message="Сервер отвечает, но вернул ошибку.",
                    )
                )
        except Exception:
            self._results.append(
                DependencyResult(
                    name="Ollama",
                    status=CheckStatus.Missing,
                    critical=True,
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
                        critical=True,
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
                        critical=True,
                    )
                )
            else:
                available = ", ".join(models[:5]) if len(models) > 0 else "нет моделей"

                self._results.append(
                    DependencyResult(
                        name=f"Модель ({self._config.Model})",
                        status=CheckStatus.Missing,
                        critical=True,
                        message=f"Не найдена. Доступные: {available}",
                        install_command=f"ollama pull {self._config.Model}",
                    )
                )
        except Exception:
            self._results.append(
                DependencyResult(
                    name=f"Модель ({self._config.Model})",
                    status=CheckStatus.Warning,
                    critical=True,
                    message="Не удалось проверить.",
                )
            )

    def _check_sqlite(self) -> None:
        try:
            # C#: LocalApplicationData/JARVIS/jarvis.db → путь БД из jarvis.paths
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

        # C#: AppContext.BaseDirectory/../../../../ → jarvis.paths
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

    def _check_piper(self) -> None:
        if not self._config.VoiceEnabled:
            self._results.append(
                DependencyResult(
                    name="Piper (TTS)",
                    status=CheckStatus.Ok,
                    critical=False,
                    message="Отключен в конфиге.",
                )
            )
            return

        # C#: AppContext.BaseDirectory/../../../../ → jarvis.paths
        piper_dir = paths.piper_dir()

        # Check for piper executable
        has_piper_exe = (piper_dir / "piper.exe").exists() or (piper_dir / "piper").exists()

        # Check for voice models
        has_onnx = piper_dir.exists() and len(list(piper_dir.glob("*.onnx"))) > 0

        if has_piper_exe and has_onnx:
            self._results.append(
                DependencyResult(
                    name="Piper (TTS)",
                    status=CheckStatus.Ok,
                    critical=False,
                )
            )
        elif not has_piper_exe:
            self._results.append(
                DependencyResult(
                    name="Piper (TTS)",
                    status=CheckStatus.Missing,
                    critical=False,
                    message=f"Исполняемый файл piper не найден в {piper_dir}",
                    install_url="https://github.com/rhasspy/piper/releases",
                )
            )
        else:
            self._results.append(
                DependencyResult(
                    name="Piper (TTS)",
                    status=CheckStatus.Missing,
                    critical=False,
                    message=f"Голосовые модели не найдены в {piper_dir}",
                    install_url="https://huggingface.co/rhasspy/piper-voices",
                )
            )

    def offer_voice_install(self) -> None:
        voice_missing = [
            r for r in self._results
            if r.status != CheckStatus.Ok
            and ("Whisper" in r.name or "Piper" in r.name)
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
