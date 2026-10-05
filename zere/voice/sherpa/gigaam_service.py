"""Распознавание речи GigaAM-v3 punct — основной STT ZERE.

Порт ZERE.Voice/Sherpa/GigaAmService.cs. Модель: GigaAM-v3 punct RNNT
(SaluteDevices/Sber, MIT), рантайм sherpa-onnx (Apache-2.0, Next-gen Kaldi).

Отчёт docs/STT_ENGINE_RESEARCH.md (§5): GigaAM выбран основным STT по итогам
замеров на этой машине — RTF 0.14–0.17 против 1.1–1.4 у faster-whisper
medium при значительно лучшем качестве русского текста (эталон разработчика:
WER 8.3 против 21.0 у Whisper-large-v3).

Модель (~163 МБ) лежит в ZERE.Voice/Models/ (общая папка с ggml-файлами
Whisper, в git не входит); при отсутствии качается один раз при preload
с проверкой SHA-256 — зеркало скачивания в install.ps1.
"""

from __future__ import annotations

import array
import hashlib
import os
import tarfile
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

from zere import paths
from zere.core.logging.log_service import log_error
from zere.voice.audio.audio_preprocessor import AudioPreprocessor

# Имя папки модели в ZERE.Voice/Models (совпадает с именем архива).
MODEL_DIR_NAME = "sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{MODEL_DIR_NAME}.tar.bz2"
)

# Контрольные суммы архива — те же, что в installer/install.ps1 (§ артефакты).
MODEL_SHA256 = "f9620a0099019c6afcee26525ef9ed3297fa50dd5691c1902af0c948fc1a470b"
MODEL_SIZE_BYTES = 170197019

# Таймаут распознавания одной команды, сек — паритет WhisperService
# (этап 1, анализ F6); для GigaAM фактическое распознавание в ~8 раз быстрее.
_TRANSCRIBE_TIMEOUT_S = 30

# Предупреждение о недоступном рантайме печатаем один раз на сессию.
_WARNED_MISSING_RUNTIME = False


def _try_import_sherpa():
    """sherpa_onnx или None, если пакет не установлен (голос не должен падать)."""
    try:
        import sherpa_onnx

        return sherpa_onnx
    except Exception:  # noqa: BLE001 — пакет не установлен/не собрался
        return None


def _read_wav_samples(path: str | Path) -> tuple[int, list[float]]:
    """WAV → (частота дискретизации, float-сэмплы 16-bit → [-1..1], mono).

    sherpa_onnx.accept_waveform принимает список float; каналы склеиваются
    в mono усреднением. Формат 16-bit PCM16 гарантируют рекордер и
    AudioPreprocessor (как и в C#-версии, файл читаем после предобработки).
    """
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"ожидался 16-bit WAV, получено {w.getsampwidth() * 8} бит")
        sample_rate = w.getframerate()
        channels = w.getnchannels()
        raw = w.readframes(w.getnframes())

    frames_data = array.array("h")
    frames_data.frombytes(raw)

    if channels > 1:
        frames = len(frames_data) // channels
        samples = [
            sum(frames_data[f * channels + c] for c in range(channels))
            / (channels * 32768.0)
            for f in range(frames)
        ]
    else:
        samples = [x / 32768.0 for x in frames_data]

    return sample_rate, samples


def _download_model(models_dir: Path) -> bool:
    """Разовое скачивание модели: HTTP + SHA-256 + распаковка tar.bz2.

    Windows поставляет tar.exe (10+), на Linux — GNU/bsdtar из PATH;
    архив распаковывается в общую папку моделей ZERE.Voice/Models.
    """
    print(f"[GigaAm] Модель не найдена — скачиваю GigaAM-v3 (~163 МБ): {MODEL_URL}")
    archive_path = Path(tempfile.gettempdir()) / f"{MODEL_DIR_NAME}.tar.bz2"

    try:
        models_dir.mkdir(parents=True, exist_ok=True)

        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or -1)
            received = 0
            last_percent = -1

            with open(archive_path, "wb") as out:
                while True:
                    chunk = response.read(1 << 17)
                    if not chunk:
                        break
                    out.write(chunk)
                    received += len(chunk)

                    if total > 0:
                        percent = received * 100 // total
                        if percent >= last_percent + 20:
                            last_percent = percent
                            print(f"[GigaAm] скачивание: {percent}%")

        # Размер и SHA-256 — как в install.ps1: битая выгрузка не распаковывается.
        size = archive_path.stat().st_size
        if size != MODEL_SIZE_BYTES:
            print(f"[GigaAm] Неверный размер архива ({size} ≠ {MODEL_SIZE_BYTES}) — отмена.")
            return False

        digest = hashlib.sha256()
        with open(archive_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)

        if digest.hexdigest() != MODEL_SHA256:
            print("[GigaAm] SHA-256 архива не совпал — отмена.")
            return False

        with tarfile.open(archive_path, "r:bz2") as tar:
            tar.extractall(models_dir, filter="data")

        print("[GigaAm] Модель установлена и проверена (SHA-256 совпал).")
        return True
    except Exception as ex:  # noqa: BLE001 — сеть не должна ронять голос
        log_error("GigaamService", f"Скачивание модели: {ex}")
        print(f"[GigaAm] Не удалось скачать модель: {ex}")
        return False
    finally:
        try:
            archive_path.unlink()
        except OSError:
            pass  # файл мог уже удалиться


class GigaamService:
    """Сервис STT: GigaAM-v3 + sherpa-onnx (порт GigaAmService.cs).

    API зеркалирует WhisperService: is_installed/preload/transcribe —
    роутинг между движками делает VoiceManager (sttEngine из config.json).
    """

    def __init__(self) -> None:
        # Та же общая папка моделей, что у Whisper (zere.paths.whisper_models_dir).
        self._models_dir = paths.whisper_models_dir()
        self._model_dir = self._models_dir / MODEL_DIR_NAME
        self._recognizer = None  # sherpa_onnx.OfflineRecognizer | None
        self._init_lock = threading.Lock()
        self._ensure_lock = threading.Lock()
        self._ensure_attempted = False
        self.current_model = "gigaam-v3"

    def is_installed(self) -> bool:
        """Модель и рантайм sherpa-onnx на месте.

        Проверка пакета нужна, чтобы без sherpa-onnx (не поставлен через
        pip) роутинг честно ушёл на Whisper, а распознавание не возвращало
        бы молча пустую строку.
        """
        global _WARNED_MISSING_RUNTIME

        if _try_import_sherpa() is None:
            if not _WARNED_MISSING_RUNTIME:
                _WARNED_MISSING_RUNTIME = True
                print("[GigaAm] Пакет sherpa-onnx не установлен — используем Whisper.")
            return False

        return (
            (self._model_dir / "encoder.int8.onnx").exists()
            and (self._model_dir / "decoder.onnx").exists()
            and (self._model_dir / "joiner.onnx").exists()
            and (self._model_dir / "tokens.txt").exists()
        )

    def _get_recognizer(self):
        """Ленивая инициализация распознавателя (аналог Lazy<...>.Value)."""
        if self._recognizer is not None:
            return self._recognizer

        with self._init_lock:
            if self._recognizer is not None:
                return self._recognizer

            sherpa = _try_import_sherpa()
            if sherpa is None:
                raise RuntimeError("пакет sherpa-onnx не установлен")

            num_threads = max(1, min(4, os.cpu_count() or 1))

            # model_type='nemo_transducer' обязателен: без него init падает
            # с «vocab_size does not exist in the metadata» (проверено).
            self._recognizer = sherpa.OfflineRecognizer.from_transducer(
                tokens=str(self._model_dir / "tokens.txt"),
                encoder=str(self._model_dir / "encoder.int8.onnx"),
                decoder=str(self._model_dir / "decoder.onnx"),
                joiner=str(self._model_dir / "joiner.onnx"),
                num_threads=num_threads,
                sample_rate=16000,
                feature_dim=80,
                decoding_method="greedy_search",
                model_type="nemo_transducer",
            )
            return self._recognizer

    def _ensure_model(self) -> None:
        """Разовое скачивание модели при её отсутствии (один раз за сессию)."""
        if self._ensure_attempted or self.is_installed():
            return

        with self._ensure_lock:
            if self._ensure_attempted or self.is_installed():
                return

            self._ensure_attempted = True
            _download_model(self._models_dir)

    def preload(self) -> bool:
        """Предзагрузка при старте (ROADMAP 1.3): скачивание модели при
        отсутствии + инициализация распознавателя. Сбои не критичны.
        """
        if _try_import_sherpa() is None:
            print("[GigaAm] Пакет sherpa-onnx не установлен (pip install sherpa-onnx).")
            return False

        try:
            self._ensure_model()

            if not self.is_installed():
                print(
                    "[GigaAm] Модель не найдена — распознавание GigaAM недоступно "
                    "(скачайте её установщиком или вручную)."
                )
                return False

            self._get_recognizer()
            return True
        except Exception as ex:  # noqa: BLE001 — предзагрузка не должна ронять старт
            log_error("GigaamService", f"Предзагрузка модели: {ex}")
            print(f"[GigaAm] Не удалось предзагрузить модель: {ex}")
            return False

    @staticmethod
    def _clean_artifacts(text: str) -> str:
        """Чистка результата: схлопывание пробелов, отбрасывание пустых и
        «пунктуационных» строк (паритет фильтра WhisperService).
        """
        text = " ".join(text.split())
        if not text or len(text) < 2 or all(c in " .,!?-…«»" for c in text):
            return ""
        return text

    def transcribe(
        self,
        wav_file: str,
        timeout_s: int | None = None,
        fast: bool = False,
    ) -> str:
        """Распознаёт WAV-файл в строку (порт TranscribeAsync).

        timeout_s — управляемый предел (иначе _TRANSCRIBE_TIMEOUT_S);
        fast — режим wake-слова: принят ради паритета API с WhisperService,
        для GigaAM декодирование и так greedy и быстрее Whisper в ~8 раз.

        При любой ошибке (нет модели, краш загрузки, таймаут) возвращает "",
        чтобы голосовой слой ушёл в fallback на текстовый ввод.
        """
        if not self.is_installed():
            print("[GigaAm] Модель GigaAM не найдена.")
            return ""

        if timeout_s is None:
            timeout_s = _TRANSCRIBE_TIMEOUT_S

        started = time.monotonic()

        # Предобработка аудио (ресемплинг → noise gate → AGC → нормализация)
        processed_file = AudioPreprocessor.process_for_whisper(wav_file)

        # Результат/ошибка из рабочего потока (таймаут → отвечаем управляемо)
        result: list[str] = []
        error_parts: list[BaseException] = []

        def worker() -> None:
            try:
                recognizer = self._get_recognizer()
                sample_rate, samples = _read_wav_samples(processed_file)

                if not samples:
                    result.append("")
                    return

                stream = recognizer.create_stream()
                stream.accept_waveform(sample_rate, samples)
                recognizer.decode_stream(stream)
                result.append(stream.result.text or "")
            except BaseException as exc:  # noqa: BLE001
                error_parts.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout_s)

        try:
            if thread.is_alive():
                # Поток не остановить — он дойдёт до конца в фоне (daemon),
                # но пользователь получает управляемый ответ.
                log_error(
                    "GigaamService",
                    f"Таймаут распознавания ({timeout_s} с): {wav_file}",
                )
                print(f"[GigaAm] Распознавание не уложилось в {timeout_s} с.")
                return ""

            if error_parts:
                ex = error_parts[0]
                log_error("GigaamService", f"Распознавание: {ex}")
                print(f"[GigaAm] Ошибка распознавания: {ex}")
                return ""

            text = self._clean_artifacts(result[0]) if result else ""

            # Этап 0 (метрики): длительность STT по каждой команде.
            total_ms = int((time.monotonic() - started) * 1000)
            print(f"[Perf] STT={total_ms} мс (модель: {self.current_model})")

            return text
        finally:
            # Удаляем обработанный файл
            if processed_file != wav_file:
                try:
                    os.remove(processed_file)
                except OSError:
                    pass
