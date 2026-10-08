"""Клиент плагина ZERE для Krita: команды рисования по TCP на localhost.

Транспорт простой: одна строка JSON на запрос, ответ — тоже строка
(`{"ok": true, ...}`). Зависимостей нет — только стандартный socket. Порт
хранится в kritarc (`[zere] port`): его публикует сам плагин, поэтому ZERE и
Krita не разойдутся, если 8768 оказался занят.

Отличие от рисования курсором: окно Krita не обязано быть активным, курсор не
двигается, а фигуры и текст ложатся в документ векторным слоем, мазки —
настоящей кистью (`Node.paintLine`). Если плагин не отвечает, вызывающий код
возвращается к прежнему способу — эмуляции мыши.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from zere.tools.drawing.krita_install import SETTINGS_GROUP, PORT_KEY, kritarc_path, read_setting

#: Плагин слушает только свой компьютер.
DEFAULT_HOST = "127.0.0.1"
#: Тот же порт по умолчанию, что и в плагине.
DEFAULT_PORT = 8768
#: Подключение к своему порту не может быть долгим, а вот рисование — может.
CONNECT_TIMEOUT = 1.5
READ_TIMEOUT = 30.0
ENCODING = "utf-8"

#: Переменная окружения для отказа от плагина (например, «ZERE_KRITA_PLUGIN=0»).
ENV_SWITCH = "ZERE_KRITA_PLUGIN"
_DISABLED_VALUES = ("0", "false", "no", "off", "выкл")


class KritaPluginError(RuntimeError):
    """Плагин недоступен или отказал: текст пригоден для ответа пользователю."""


def plugin_enabled() -> bool:
    """Разрешено ли рисовать через плагин (выключается переменной окружения)."""
    value = (os.environ.get(ENV_SWITCH) or "").strip().lower()
    return value not in _DISABLED_VALUES


def plugin_port(path: Optional[Path] = None) -> int:
    """Порт плагина из kritarc; без записи — значение по умолчанию."""
    try:
        text = Path(path or kritarc_path()).read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_PORT

    raw = read_setting(text, SETTINGS_GROUP, PORT_KEY)

    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_PORT

    return port if 1 <= port <= 65535 else DEFAULT_PORT


class KritaApiClient:
    """Запросы к плагину: соединение на каждый запрос — так проще и надёжнее."""

    def __init__(self, host: str = DEFAULT_HOST, port: Optional[int] = None,
                 connect_timeout: float = CONNECT_TIMEOUT,
                 read_timeout: float = READ_TIMEOUT) -> None:
        self.host = host
        self.port = int(port or plugin_port())
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)

    # ── Транспорт ─────────────────────────────────────────────────

    def request(self, payload: Dict[str, object]) -> Dict[str, object]:
        """Отправляет один запрос и возвращает ответ плагина."""
        line = json.dumps(payload, ensure_ascii=False).encode(ENCODING) + b"\n"

        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout
            ) as connection:
                connection.settimeout(self.read_timeout)
                connection.sendall(line)
                response = self._read_line(connection)
        except OSError as error:
            raise KritaPluginError(
                f"плагин ZERE для Krita не отвечает на {self.host}:{self.port} "
                f"({error.__class__.__name__}). Запустите Krita и проверьте "
                f"плагин: python -m zere.tools.drawing.krita_install --check"
            ) from error

        try:
            parsed = json.loads(response.decode(ENCODING))
        except (UnicodeDecodeError, ValueError) as error:
            raise KritaPluginError(f"плагин ответил не JSON: {error}") from error

        if not isinstance(parsed, dict):
            raise KritaPluginError("плагин ответил не объектом JSON")

        if not parsed.get("ok"):
            raise KritaPluginError(str(parsed.get("error") or "плагин отказал"))

        return parsed

    @staticmethod
    def _read_line(connection: socket.socket) -> bytes:
        """Читает ответ до перевода строки (ответ всегда короткий)."""
        chunks: List[bytes] = []

        while True:
            chunk = connection.recv(4096)

            if not chunk:
                break

            chunks.append(chunk)

            if b"\n" in chunk:
                break

        answer = b"".join(chunks).split(b"\n", 1)[0]

        if not answer:
            raise KritaPluginError("плагин закрыл соединение без ответа")

        return answer

    # ── Команды ───────────────────────────────────────────────────

    def ping(self) -> Dict[str, object]:
        return self.request({"op": "ping"})

    def info(self) -> Dict[str, object]:
        """Что открыто в Krita: `document` = None, если документов нет."""
        return self.request({"op": "info"})

    def ensure_document(self, width: int, height: int) -> Dict[str, object]:
        """Создаёт документ, если открытого нет; возвращает его размеры."""
        return self.request({"op": "document", "width": int(width), "height": int(height)})

    def draw_svg(self, svg: str, layer: Optional[str] = None) -> int:
        """Кладёт SVG в векторный слой; возвращает число созданных фигур."""
        payload: Dict[str, object] = {"op": "svg", "svg": svg}

        if layer:
            payload["layer"] = layer

        return int(self.request(payload).get("shapes") or 0)

    def paint(self, polylines: Sequence[Sequence[Sequence[float]]],
              layer: Optional[str] = None, pressure: float = 1.0) -> int:
        """Проводит ломаные кистью Krita; возвращает число отрезков.

        Нужно там, где векторный слой не подходит или не сработал: текст,
        растеризованный шрифтом, и откат для фигур.
        """
        payload: Dict[str, object] = {
            "op": "stroke",
            "polylines": [
                [[float(x), float(y)] for x, y in line] for line in polylines
            ],
            "pressure": float(pressure),
        }

        if layer:
            payload["layer"] = layer

        return int(self.request(payload).get("segments") or 0)

    def clear(self) -> str:
        return str(self.request({"op": "clear"}).get("detail") or "очистил холст")

    def stats(self, step: int = 4) -> Dict[str, object]:
        """Сколько нарисовано в документе: `opaque`, `dark`, `layers` и т. д.

        Ответ на вопрос «рисунок действительно появился»: считает пиксели
        объединённого изображения (векторные слои видны, мазки тоже).
        """
        return self.request({"op": "stats", "step": int(step)})
