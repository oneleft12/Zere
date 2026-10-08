"""Локальный сервер плагина: JSON-строки по TCP на 127.0.0.1.

Транспорт намеренно простой (одна строка — один запрос, ответ — одной строкой
JSON): ZERE общается с Krita без зависимостей и без прав администратора, а
проверить протокол можно обычным сокетом. Слушаем только localhost — снаружи
порт недоступен.

Порт берётся из kritarc (`[zere] port`), чтобы ZERE и плагин не разошлись,
если 8768 занят: свободный порт плагин записывает обратно в настройки.
"""

from __future__ import annotations

import json
from typing import Dict, Optional

from krita import Krita

from .drawing import handle

try:  # Krita 5 — PyQt5, Krita 6 — PyQt6
    from PyQt5.QtCore import QObject
    from PyQt5.QtNetwork import QHostAddress, QTcpServer
except ImportError:  # pragma: no cover - ветка для Krita 6
    from PyQt6.QtCore import QObject
    from PyQt6.QtNetwork import QHostAddress, QTcpServer

#: Первый порт, который пробует плагин (и значение по умолчанию для ZERE).
DEFAULT_PORT = 8768
#: Сколько занятых портов подряд пропускаем.
PORT_ATTEMPTS = 10
#: Группа и ключ настроек Krita, где плагин публикует рабочий порт.
SETTINGS_GROUP = "zere"
PORT_KEY = "port"

#: Предел строки запроса: защита от мусора в сокете (SVG бывает большим).
MAX_REQUEST_BYTES = 4 * 1024 * 1024
ENCODING = "utf-8"


def stored_port() -> int:
    """Порт из настроек Krita; при мусоре — значение по умолчанию."""
    raw = Krita.instance().readSetting(SETTINGS_GROUP, PORT_KEY, str(DEFAULT_PORT))

    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_PORT

    return port if 1 <= port <= 65535 else DEFAULT_PORT


def remember_port(port: int) -> None:
    """Публикует рабочий порт в kritarc: по нему его найдёт ZERE."""
    Krita.instance().writeSetting(SETTINGS_GROUP, PORT_KEY, str(port))


def answer(request: Dict[str, object]) -> Dict[str, object]:
    """Ответ на запрос: ошибки рисования не должны ломать соединение."""
    try:
        return handle(request)
    except Exception as error:  # noqa: BLE001 — плагин не должен падать
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def encode(response: Dict[str, object]) -> bytes:
    """Ответ одной строкой JSON (ensure_ascii=False — кириллица читаема)."""
    return (json.dumps(response, ensure_ascii=False) + "\n").encode(ENCODING)


class ZereServer(QObject):
    """Приёмник команд ZERE внутри Krita."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._server: Optional[QTcpServer] = None
        self._buffers: Dict[int, bytearray] = {}
        self.port: Optional[int] = None

    # ── Жизненный цикл ────────────────────────────────────────────

    def start(self) -> Optional[int]:
        """Поднимает сервер; возвращает порт или None, если не удалось."""
        if self._server is not None:
            return self.port

        server = QTcpServer(self)
        first = stored_port()

        for candidate in range(first, min(first + PORT_ATTEMPTS, 65536)):
            if server.listen(QHostAddress("127.0.0.1"), candidate):
                self.port = candidate
                break

        if self.port is None:
            return None

        if self.port != first:
            remember_port(self.port)

        server.newConnection.connect(self._on_connection)
        self._server = server
        return self.port

    def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
            self.port = None

    # ── Транспорт ─────────────────────────────────────────────────

    def _on_connection(self) -> None:
        if self._server is None:
            return

        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()

            if socket is None:
                continue

            self._buffers[id(socket)] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._on_ready(s))
            socket.disconnected.connect(lambda s=socket: self._forget(s))

    def _forget(self, socket) -> None:
        self._buffers.pop(id(socket), None)
        socket.deleteLater()

    def _on_ready(self, socket) -> None:
        buffer = self._buffers.setdefault(id(socket), bytearray())
        buffer.extend(bytes(socket.readAll()))

        if len(buffer) > MAX_REQUEST_BYTES:
            socket.write(encode({"ok": False, "error": "запрос слишком длинный"}))
            socket.disconnectFromHost()
            return

        while b"\n" in buffer:
            line, _, rest = buffer.partition(b"\n")
            buffer[:] = rest
            self._reply(socket, bytes(line))

    def _reply(self, socket, line: bytes) -> None:
        try:
            request = json.loads(line.decode(ENCODING))
        except (UnicodeDecodeError, ValueError) as error:
            socket.write(encode({"ok": False, "error": f"не JSON: {error}"}))
            return

        if not isinstance(request, dict):
            socket.write(encode({"ok": False, "error": "запрос должен быть объектом"}))
            return

        socket.write(encode(answer(request)))
        socket.flush()
