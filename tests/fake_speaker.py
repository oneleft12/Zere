"""Фейковый C#-хелпер озвучки для тестов (без звуковых устройств!).

Повторяет протокол JARVIS.Speaker `host` (см. jarvis/voice/audio/csharp_speaker.py):
`ready` на старте, затем строка JSON на команду. Звук **не** воспроизводит —
только пишет принятые команды в журнал (--log) и имитирует задержку звучания
(--delay), поэтому тесты не трогают наушники пользователя.

Запуск: python tests/fake_speaker.py host --log <файл.jsonl> [--delay 0.1]
                                             [--exit-after-ready] [--die-on-speak]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

PROTOCOL_VERSION = "1"


def _reply(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", default="host")  # протокол: host
    parser.add_argument("--log", default="")
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--exit-after-ready", action="store_true")
    parser.add_argument("--die-on-speak", action="store_true")
    args = parser.parse_args()

    log_handle = open(args.log, "a", encoding="utf-8") if args.log else None

    _reply({"event": "ready", "version": PROTOCOL_VERSION})

    if args.exit_after_ready:
        return 0

    for line in sys.stdin:
        line = line.strip()

        if not line:
            continue

        request = json.loads(line)

        if log_handle is not None:
            log_handle.write(json.dumps(request, ensure_ascii=False) + "\n")
            log_handle.flush()

        command = request.get("cmd")

        if command == "speak":
            if args.die_on_speak:
                return 3  # имитация краха хелпера посреди фразы

            time.sleep(args.delay)
            _reply({
                "event": "done",
                "file": request.get("wav", ""),
                "processMs": 1,
                "playMs": int(args.delay * 1000),
                "played": True,
            })
        elif command == "stop":
            _reply({"event": "stopped"})
        elif command == "ping":
            _reply({"event": "pong", "version": PROTOCOL_VERSION})
        elif command == "quit":
            _reply({"event": "bye"})
            return 0
        else:
            _reply({"event": "error", "message": f"неизвестная команда: {command}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
