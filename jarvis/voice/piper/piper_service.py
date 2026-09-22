"""Синтез речи TTS (порт JARVIS.Voice/Piper/PiperService.cs).

Запуск внешнего piper через subprocess с поиском исполняемого файла
(логика FindPiperExecutable повторена дословно).
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from jarvis import paths

# CreateNoWindow в C# (Windows-only; на других платформах — 0)
_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class PiperService:
    """Сервис TTS: процесс piper + голосовые модели .onnx (порт PiperService.cs)."""

    def __init__(self) -> None:
        # В C# путь строился от AppContext.BaseDirectory до корня решения,
        # затем JARVIS.Voice/Piper. В Python — jarvis.paths.piper_dir().
        self._piper_dir: Path = paths.piper_dir()
        self._espeak_data_path: Path = self._piper_dir / "espeak-ng-data"
        self._current_voice = "ru_RU-irina-medium"
        self._piper_exe: str | None = None
        self._cached_model_path: str | None = None

        self.is_loaded: bool = False  # IsLoaded { get; private set; }

    @property
    def current_voice(self) -> str:
        return self._current_voice

    def initialize(self, voice_name: str | None = None) -> bool:
        """Находит piper и модель голоса (порт Initialize)."""
        if voice_name is not None:
            self._current_voice = voice_name

        self._piper_exe = self._find_piper_executable()

        if self._piper_exe is None:
            print("[Piper] Исполняемый файл piper не найден.")
            self.is_loaded = False
            return False

        model_path = self._find_model_path()

        if model_path is None:
            print(f"[Piper] Модель '{self._current_voice}' не найдена в {self._piper_dir}")
            self.is_loaded = False
            return False

        self._cached_model_path = model_path

        # Clean up old output files older than 1 hour
        self._cleanup_old_outputs()

        self.is_loaded = True

        if self._espeak_data_path.is_dir():
            print(f"[Piper] espeak-ng-data: {self._espeak_data_path}")
        else:
            print(f"[Piper] ⚠ espeak-ng-data не найден: {self._espeak_data_path}")

        print(f"[Piper] Загружен. Голос: {self._current_voice}")
        return True

    def speak(self, text: str) -> str:
        """Синтезирует речь в WAV-файл и возвращает путь к нему (порт SpeakAsync)."""
        # Убираем эмодзи, смайлики и «ролевые» пометки — TTS не должен их читать
        text = self.strip_emotions(text)

        if not text or text.isspace():
            return ""

        if not self.is_loaded or self._piper_exe is None:
            print(f"[Piper] {text}")
            return ""

        output_file = str(
            self._piper_dir / f"output_{datetime.now():%Y%m%d_%H%M%S}.wav"
        )

        try:
            # Кинематографичный баритон:
            # --length_scale 1.15 — медленная, уверенная подача
            # --noise_scale 0.35 — минимум шума синтеза (было 0.45, шипело)
            # --noise_w 0.65 — стабильная интонация, без металличности
            # --sentence_silence 0.4 — тишина после предложения (не обрезает окончания)
            args = [
                self._piper_exe,
                "--model", str(self._cached_model_path),
                "--output_file", output_file,
                "--length_scale", "1.15",
                "--noise_scale", "0.35",
                "--noise_w", "0.65",
                "--sentence_silence", "0.4",
            ]

            # Указываем путь к данным espeak-ng, чтобы piper мог найти phoneme данные
            env = dict(os.environ)
            if self._espeak_data_path.is_dir():
                env["ESPEAKDATA_PATH"] = str(self._espeak_data_path)
                env["ESPEAK_DATA_PATH"] = str(self._espeak_data_path)

            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                creationflags=_CREATIONFLAGS,
            )

            if process is None:
                # Process.Start в C# мог вернуть null
                print("[Piper] Не удалось запустить процесс.")
                return ""

            # Пишем текст в stdin, читаем stdout/stderr и ждём завершения
            # (аналог WriteAsync + WaitForExitAsync + ReadToEndAsync)
            _stdout, error = process.communicate(
                input=text.encode("utf-8"),
                timeout=300,
            )

            if process.returncode != 0:
                print(f"[Piper] Ошибка: {error.decode('utf-8', errors='replace')}")
                return ""

            return output_file
        except Exception as ex:  # noqa: BLE001 — дословно как в C#
            print(f"[Piper] Ошибка: {ex}")
            return ""

    @staticmethod
    def strip_emotions(text: str) -> str:
        """Убирает из текста всё, что TTS не должен произносить:
        эмодзи, текстовые смайлики, «ролевые» пометки (*улыбается*, (томно)),
        markdown-символы и Markdown-эмодзи вроде :smile:.
        """
        if not text:
            return text

        # Ролевые пометки в скобках: (улыбается), (смеётся), (задумчиво)
        text = re.sub(r"\([^)]*[а-яёА-ЯЁ]{3,}[^)]*\)", " ", text)

        # Ролевые пометки в *звёздочках*: *улыбается*, *качает головой*
        text = re.sub(r"\*[^*]*[а-яёА-ЯЁ]{3,}[^*]*\*", " ", text)

        # Markdown-эмодзи :smile:, :heart:
        text = re.sub(r":[a-z_0-9]+:", " ", text)

        # Текстовые смайлики: :) ;) :D :( :P <3 =) и т.п.
        text = re.sub(r"[:;=8][\-^']?[)(DPp/\\|]", " ", text)
        text = re.sub(r"[)(DPp/\\|][\-^']?[:;=8]", " ", text)
        text = re.sub(r"<3", " ", text)

        # Юникод-эмодзи и символы. В C# это суррогатные пары
        # [\uD800-\uDBFF][\uDC00-\uDFFF]; Python работает по кодовым точкам,
        # поэтому суррогатный диапазон здесь — эквивалентный астральный
        # [\U00010000-\U0010FFFF].
        text = re.sub(
            r"[\U00010000-\U0010FFFF]|[️‍]"
            r"|[☀-➿]|[←-⇿]|[⬀-⯿]|[✀-➿]",
            "",
            text,
        )

        # Убираем markdown-разметку: **bold**, *italic*, `code`, ## заголовки
        text = re.sub(r"[*_`#]{1,3}([^*_`#]+)[*_`#]{1,3}", r"\1", text)
        text = re.sub(r"[*_`#~>|-]{2,}", " ", text)

        # Схлопываем пробелы
        text = re.sub(r"\s{2,}", " ", text).strip()

        return text

    def _find_piper_executable(self) -> str | None:
        """Порт FindPiperExecutable: piper-файл в папке → piper.exe → piper в PATH."""
        piper_file = self._piper_dir / "piper"
        if piper_file.is_file():
            return str(piper_file)

        piper_exe = self._piper_dir / "piper.exe"
        if piper_exe.is_file():
            return str(piper_exe)

        try:
            # piper --version, ожидание до 3 секунд (WaitForExit(3000))
            completed = subprocess.run(
                ["piper", "--version"],
                capture_output=True,
                timeout=3,
                creationflags=_CREATIONFLAGS,
            )
            if completed.returncode == 0:
                return "piper"
        except Exception:
            pass

        return None

    def _find_model_path(self) -> str | None:
        """Порт FindModelPath: {voice}.onnx, иначе первый *.onnx в папке."""
        model_file = f"{self._current_voice}.onnx"
        model_path = self._piper_dir / model_file

        if model_path.is_file():
            return str(model_path)

        onnx_files = sorted(self._piper_dir.glob("*.onnx"))
        if onnx_files:
            return str(onnx_files[0])

        return None

    def get_available_voices(self) -> list[str]:
        """Список голосов (имена *.onnx без расширения) — порт GetAvailableVoices."""
        if not self._piper_dir.is_dir():
            return []

        return [p.stem for p in sorted(self._piper_dir.glob("*.onnx"))]

    def set_voice(self, voice_name: str) -> None:
        """Смена голоса (порт SetVoice): сбрасывает кэш модели, переинициализирует."""
        self._current_voice = voice_name
        self._cached_model_path = None

        if self.is_loaded:
            self.initialize(voice_name)

    def _cleanup_old_outputs(self) -> None:
        """Удаляет output_*.wav старше часа (порт CleanupOldOutputs)."""
        try:
            cutoff = datetime.now().timestamp() - 3600  # DateTime.Now.AddHours(-1)

            for file_path in self._piper_dir.glob("output_*.wav"):
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                except OSError:
                    # Ignore individual file deletion failures during cleanup
                    pass
        except Exception:
            # Ignore cleanup failures — not critical
            pass
