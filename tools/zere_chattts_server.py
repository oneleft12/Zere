#!/usr/bin/env python3
"""ZERE: HTTP-сервер TTS на ChatTTS (2Noise/ChatTTS).

C#-редакция не умеет импортировать Python-библиотеки напрямую, поэтому
ChatTtsService поднимает этот сайдкар — тот же приём, что и у PocketTTS.

Запуск из корня ZERE (C#-клиент делает это сам):

    tools/uv.exe run --python 3.12 --with ChatTTS --with soundfile \\
        --with num2words python tools/zere_chattts_server.py \\
        --port 8472 --voice zere-standard

`--python 3.12` — проверенная версия стека ChatTTS (torch/torchaudio/numba):
uv скачивает её сам и не трогает системный Python — поэтому установка ZERE
не зависит от его версии.

Эндпоинты:
    GET  /health   -> {"status": "loading"|"ready"|"error", "detail": str,
                       "sample_rate": 24000, "voice": str, "voices": [...]}
    POST /tts      body: {"text": "...", "voice": "zere-warm",
                          "speed": 4, "silence": 0.2}
                   -> application/octet-stream: PCM s16le моно @ sample_rate.
                      Заголовок ответа X-Sample-Rate: 24000.

Модель грузится ЛЕНИВО (при старте — в фоне, чтобы /health успел сказать
«loading»); веса скачиваются при первой загрузке и кэшируются.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Корень репозитория в sys.path: сервер переиспользует ChatTTSManager из
# zere/voice/chattts (одна реализация инициализации для обеих редакций).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from zere.voice.chattts.chattts_manager import (  # noqa: E402
    BUILTIN_VOICES,
    DEFAULT_VOICE,
    SAMPLE_RATE,
    ChatTTSManager,
)

# ── Глобальное состояние ────────────────────────────────────────────

MANAGER = ChatTTSManager(DEFAULT_VOICE)
VOICE_KEY = DEFAULT_VOICE
STATUS = {"state": "loading", "detail": "загрузка модели"}
SYNTH_LOCK = threading.Lock()  # один экземпляр модели обслуживает запросы по очереди
# Размер порции PCM при отдаче: ~0.2 с звука — достаточно для раннего старта
# воспроизведения и не рвёт поток на сотни мелких записей.
CHUNK_SAMPLES = 4800


def log(msg: str) -> None:
    print(f"[zere-chattts] {msg}", flush=True)


# ── Текст ───────────────────────────────────────────────────────────

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def expand_numbers(text: str) -> str:
    """Раскрывает цифры в слова (ChatTTS обучен на тексте, а не на цифрах).

    num2words ставится опционально (`uv run --with num2words`); если его нет —
    текст уходит как есть.
    """
    try:
        from num2words import num2words
    except ImportError:
        return text

    def repl(m: re.Match) -> str:
        raw = m.group(0).replace(",", ".")
        try:
            value = float(raw) if "." in raw else int(raw)
            return num2words(value, lang="ru")
        except Exception:  # noqa: BLE001
            return m.group(0)

    return _NUMBER_RE.sub(repl, text)


def prepare(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ").strip()
    return expand_numbers(text)


# ── Модель ──────────────────────────────────────────────────────────


def load_model_background() -> None:
    """Прогрев в фоне: /health отвечает «loading», пока веса грузятся."""
    global STATUS

    try:
        MANAGER.load_model()
    except Exception as ex:  # noqa: BLE001 — статус важнее исключения
        STATUS = {"state": "error", "detail": str(ex)}
        log(f"модель не загрузилась: {ex}")
        return

    if STATUS["state"] != "error":
        STATUS = {"state": "ready", "detail": ""}
        log(f"готов: sample_rate={SAMPLE_RATE}, voice={VOICE_KEY}")


def apply_request_params(request: dict) -> None:
    """Профиль/темп/пауза конкретного запроса (перезагрузка модели не нужна).

    `speed` — это length_scale из VoiceConfig (1.0 = норма, больше = медленнее):
    ровно та же семантика, что была у Piper. В токен `[speed_N]` его переводит
    ChatTTSManager.set_inference_params — одна реализация маппинга на обе
    редакции (C# и Python), чтобы темп не разъезжался.
    """
    voice = str(request.get("voice") or VOICE_KEY)
    MANAGER.set_voice(voice)

    raw_speed = request.get("speed")
    raw_silence = request.get("silence")

    try:
        length_scale = 1.0 if raw_speed is None else float(raw_speed)
    except (TypeError, ValueError):
        length_scale = 1.0

    try:
        silence = 0.2 if raw_silence is None else float(raw_silence)
    except (TypeError, ValueError):
        silence = 0.2

    MANAGER.set_inference_params(length_scale, silence)


# ── HTTP ────────────────────────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # тишина в логах (у нас свои)
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {
                "status": STATUS["state"],
                "detail": STATUS.get("detail", ""),
                "sample_rate": SAMPLE_RATE,
                "voice": MANAGER.current_voice or VOICE_KEY,
                "voices": MANAGER.available_voices(),
            })
        elif self.path == "/voices":
            self._json(200, {"voices": MANAGER.available_voices()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/tts":
            self._json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            text = prepare(str(request.get("text", "")))
            if not text:
                self._json(400, {"error": "пустой текст"})
                return
        except Exception as ex:  # noqa: BLE001
            self._json(400, {"error": str(ex)})
            return

        import numpy as np

        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("X-Sample-Rate", str(SAMPLE_RATE))
            # HTTP/1.1 без Content-Length => тело до закрытия соединения
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

            with SYNTH_LOCK:
                apply_request_params(request)
                samples = MANAGER.waveform(text)

            for start in range(0, len(samples), CHUNK_SAMPLES):
                chunk = samples[start:start + CHUNK_SAMPLES]
                pcm = (np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2")
                self.wfile.write(pcm.tobytes())
                self.wfile.flush()
        except BrokenPipeError:
            return  # клиент отменил синтез — не ошибка
        except Exception as ex:  # noqa: BLE001
            # Заголовки уже ушли — просто логируем и закрываем соединение,
            # чтобы не подмешивать текст ошибки в PCM-поток.
            log(f"ошибка синтеза: {ex}")


# ── main ────────────────────────────────────────────────────────────


def main() -> int:
    global VOICE_KEY

    parser = argparse.ArgumentParser(description="ZERE TTS server (ChatTTS)")
    parser.add_argument("--port", type=int, default=8472)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--voice",
        default=DEFAULT_VOICE,
        help="профиль голоса ZERE (zere-standard и др.)",
    )
    args = parser.parse_args()

    VOICE_KEY = args.voice or DEFAULT_VOICE
    MANAGER.set_voice(VOICE_KEY)

    log(f"профили голоса: {', '.join(BUILTIN_VOICES)}")

    # Ленивая загрузка: модель грузится в фоне, сервер сразу отвечает /health
    # («loading») — клиент ждёт ready и не получает таймаут на первом запросе.
    threading.Thread(target=load_model_background, daemon=True).start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"слушаю http://{args.host}:{args.port} (модель грузится в фоне)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
