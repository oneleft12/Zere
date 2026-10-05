#!/usr/bin/env python3
"""JARVIS: HTTP-сервер TTS с клонированием голоса (xVibePocketTTS, CPU).

Запускается из корня JARVIS (C#-клиент делает это автоматически):

    tools/uv.exe run --project tools/xVibePocketTTS --with num2words \
        python tools/jarvis_tts_server.py --port 8471 --voice <имя|путь/к/референсу.wav>

Эндпоинты:
    GET  /health   -> {"status": "ready"|"loading", "sample_rate": int, "voice": str}
    POST /tts      body: {"text": "..."}
                   -> application/octet-stream: PCM s16le моно @ sample_rate,
                      потоково (первый байт — как только модель дала первый чанк).
                      Заголовок ответа X-Sample-Rate: 24000.

Клонирование: референс-WAV кодируется в состояние голоса ОДИН раз и кэшируется
в .safetensors рядом (--voice-cache), дальше состояния читаются мгновенно.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ── Глобальное состояние ────────────────────────────────────────────

TTS = None                      # RussianTTS (загружается в main)
VOICE_KEY = "male_deep"         # имя встроенного голоса или путь к .safetensors
SAMPLE_RATE = 24000
STATUS = {"state": "loading", "detail": "загрузка модели"}
SYNTH_LOCK = threading.Lock()   # один экземпляр RussianTTS обслуживает запросы по очереди


def log(msg: str) -> None:
    print(f"[jarvis-tts] {msg}", flush=True)


# ── Текст ───────────────────────────────────────────────────────────

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def expand_numbers(text: str) -> str:
    """Раскрывает цифры в слова (модель обучена на раскрытом тексте).

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
        except Exception:
            return m.group(0)

    return _NUMBER_RE.sub(repl, text)


def prepare(text: str) -> str:
    text = text.replace("\r", " ").replace("\n", " ").strip()
    text = expand_numbers(text)
    return text


# ── Голос ───────────────────────────────────────────────────────────

_STATE_CACHE: dict[str, object] = {}


def voice_state(key: str):
    """Состояние голоса в памяти: источник читается один раз, не на каждый запрос.

    Имена встроенных голосов резолвятся в hf:// (как делает RussianTTS._voice_state),
    пути к файлам передаются как есть.
    """
    if key not in _STATE_CACHE:
        from xvibe_pocket_tts.runtime import ASSET_REVISION, MODEL_REPO, VOICES

        source = (
            f"hf://{MODEL_REPO}/voices/{VOICES[key]}@{ASSET_REVISION}"
            if key in VOICES
            else key
        )
        _STATE_CACHE[key] = TTS.model.get_state_for_audio_prompt(source)
    return _STATE_CACHE[key]


def synth_pcm(text: str):
    """Генерирует PCM-чанки (float32 [-1..1]) с кэшированным состоянием голоса."""
    prepared = TTS.prepare_text(text)
    state = voice_state(VOICE_KEY)
    return TTS.model.generate_audio_stream(state, prepared, copy_state=True)


def resolve_voice(voice_arg: str | None, cache_dir: Path) -> str:
    """Возвращает ключ голоса: имя встроенного ИЛИ путь к кэшированному state.

    Референс-WAV кодируется один раз; повторные запуски читают кэш.
    """
    if not voice_arg:
        return "male_deep"

    path = Path(voice_arg)
    if not path.is_file():
        # Возможно, передано имя встроенного голоса
        return voice_arg

    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp = path.stat()
    key = hashlib.sha1(
        f"{path.resolve()}:{stamp.st_mtime}:{stamp.st_size}".encode()
    ).hexdigest()[:16]
    cache = cache_dir / f"{path.stem}_{key}.safetensors"

    if not cache.exists():
        log(f"кодирую референс голоса: {path} (однократно)...")
        from pocket_tts import export_model_state

        state = TTS.model.get_state_for_audio_prompt(str(path))
        export_model_state(state, str(cache))
        log(f"состояние голоса сохранено: {cache.name}")
    else:
        log(f"состояние голоса из кэша: {cache.name}")

    return str(cache)


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
                "voice": Path(VOICE_KEY).name if VOICE_KEY.endswith(".safetensors") else VOICE_KEY,
            })
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
                for chunk in synth_pcm(text):
                    pcm = (np.clip(chunk.numpy(), -1.0, 1.0) * 32767.0).astype("<i2")
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
    global TTS, VOICE_KEY, SAMPLE_RATE, STATUS

    parser = argparse.ArgumentParser(description="JARVIS TTS server (xVibePocketTTS)")
    parser.add_argument("--port", type=int, default=8471)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--voice", default="",
                        help="имя встроенного голоса (male_deep и др.) или путь к референс-WAV")
    parser.add_argument("--voice-cache", default="",
                        help="каталог кэша состояний голоса (по умолчанию: tools/voice_cache)")
    args = parser.parse_args()

    cache_dir = Path(args.voice_cache) if args.voice_cache else (
        Path(__file__).resolve().parent / "voice_cache")

    log("загрузка модели (при первом запуске — скачивание весов ~458 МБ)...")
    from xvibe_pocket_tts import RussianTTS

    TTS = RussianTTS()               # грузит веса с HF при первом запуске
    SAMPLE_RATE = TTS.sample_rate

    STATUS = {"state": "loading", "detail": "подготовка текстового конвейера"}
    TTS.prepare_text("Привет.")      # прогрев RUAccent (скачает модели/словари)

    STATUS = {"state": "loading", "detail": "подготовка голоса"}
    VOICE_KEY = resolve_voice(args.voice or None, cache_dir)

    STATUS = {"state": "ready", "detail": ""}
    log(f"готов: sample_rate={SAMPLE_RATE}, voice={VOICE_KEY}, port={args.port}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
