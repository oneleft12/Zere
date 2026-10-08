#!/usr/bin/env python3
"""ZERE: HTTP-сервер TTS на Silero v5 (русский голос).

C#-редакция не умеет импортировать Python-библиотеки напрямую, поэтому
SileroTtsService поднимает этот сайдкар — тот же приём, что у ChatTTS и
PocketTTS (один контракт: /health + потоковый /tts с PCM s16le).

Запуск из корня ZERE (C#-клиент делает это сам):

    tools/uv.exe run --python 3.12 --with torch --with soundfile \\
        python tools/zere_silero_server.py --port 8473 --voice baya

Модель `v5_5_ru.pt` (~145 МБ) скачивается при первом синтезе в
`ZERE.Voice/Silero/`; `torch` в окружении сайдкара уже есть у ChatTTS-стека,
поэтому дополнительно тянется только модель.

Эндпоинты:
    GET  /health   -> {"status": "loading"|"ready"|"error", "detail": str,
                       "sample_rate": 24000, "voice": str, "voices": [...]}
    GET  /voices   -> {"voices": [...]}
    POST /tts      body: {"text": "...", "voice": "baya", "silence": 0.2}
                   -> application/octet-stream: PCM s16le моно @ sample_rate.
                      Заголовок ответа X-Sample-Rate: 24000.

Модель грузится ЛЕНИВО (при старте — в фоне, чтобы /health успел сказать
«loading»); файл модели скачивается при первой загрузке и кэшируется.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# Корень репозитория в sys.path: сервер переиспользует SileroManager из
# zere/voice/silero (одна реализация синтеза для обеих редакций).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from zere.voice.silero.silero_manager import (  # noqa: E402
    BUILTIN_VOICES,
    DEFAULT_VOICE,
    SAMPLE_RATE,
    SileroManager,
)

DEFAULT_PORT = 8473

# ── Глобальное состояние ────────────────────────────────────────────

MANAGER = SileroManager(DEFAULT_VOICE)
VOICE_KEY = DEFAULT_VOICE
STATUS = {"state": "loading", "detail": "загрузка модели"}
SYNTH_LOCK = threading.Lock()  # один экземпляр модели обслуживает запросы по очереди
# Размер порции PCM при отдаче: ~0.2 с звука — достаточно для раннего старта
# воспроизведения и не рвёт поток на сотни мелких записей.
CHUNK_SAMPLES = 4800


def log(msg: str) -> None:
    print(f"[zere-silero] {msg}", flush=True)


# ── Текст ───────────────────────────────────────────────────────────


def prepare(text: str) -> str:
    """Готовит текст к синтезу.

    В отличие от ChatTTS, цифры раскрывать не нужно: Silero v5_ru сам читает
    числа по-русски (и ставит ударения) — это его штатная возможность.
    """
    return text.replace("\r", " ").replace("\n", " ").strip()


# ── PCM ─────────────────────────────────────────────────────────────


def _to_pcm16(samples: Any) -> bytes:
    """float32 [-1..1] → PCM s16le (тот же формат, что у ChatTTS-сайдкара).

    Без numpy: функция работает и в окружении без него (контрактные тесты
    гоняются без тяжёлых зависимостей).
    """
    out = bytearray()

    for value in samples:
        sample = float(value)

        if sample > 1.0:
            sample = 1.0
        elif sample < -1.0:
            sample = -1.0

        out += int(sample * 32767.0).to_bytes(2, "little", signed=True)

    return bytes(out)


# ── Модель ──────────────────────────────────────────────────────────


def load_model_background() -> None:
    """Прогрев в фоне: /health отвечает «loading», пока модель грузится."""
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


def _health_payload() -> dict:
    """Состояние движка для C#-холдера сайдкара (JSON-сериализуемо)."""
    return {
        "status": STATUS["state"],
        "detail": STATUS.get("detail", ""),
        "sample_rate": SAMPLE_RATE,
        "voice": MANAGER.current_voice or VOICE_KEY,
        "voices": MANAGER.available_voices(),
    }


def apply_request_params(request: dict) -> None:
    """Голос и пауза конкретного запроса (модель не перезагружается)."""
    MANAGER.set_voice(str(request.get("voice") or VOICE_KEY))

    raw_silence = request.get("silence")

    try:
        silence = 0.2 if raw_silence is None else float(raw_silence)
    except (TypeError, ValueError):
        silence = 0.2

    # Темп у Silero v5 не настраивается: length_scale принимается ради общего
    # контракта с ChatTTS-сайдкаром и игнорируется менеджером.
    MANAGER.set_inference_params(1.0, silence)


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
            self._json(200, _health_payload())
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
                self.wfile.write(_to_pcm16(chunk))
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

    parser = argparse.ArgumentParser(description="ZERE TTS server (Silero, русский)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--voice",
        default=DEFAULT_VOICE,
        help=f"голос Silero ({', '.join(BUILTIN_VOICES)})",
    )
    args = parser.parse_args()

    VOICE_KEY = args.voice or DEFAULT_VOICE
    MANAGER.set_voice(VOICE_KEY)

    log(f"голоса: {', '.join(BUILTIN_VOICES)}")

    # Ленивая загрузка: модель (и файл ~145 МБ) поднимается в фоне, сервер сразу
    # отвечает /health («loading») — клиент ждёт ready и не ловит таймаут.
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
