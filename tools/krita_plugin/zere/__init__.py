"""Плагин ZERE для Krita: рисование по командам ассистента.

Плагин живёт внутри Krita и поднимает локальный сервер на 127.0.0.1: ZERE
присылает JSON-строки, а плагин рисует фигуры, текст и мазки родным API Krita
(`VectorLayer.addShapesFromSvg`, `Node.paintLine`). Курсор и фокус окна не
используются вовсе — Krita может быть свёрнута, а результат точный.

Установка: `python -m zere.tools.drawing.krita_install` (копирует плагин в
пользовательскую папку pykrita и включает его в kritarc). Исходники — в
`tools/krita_plugin/` репозитория ZERE.
"""

from krita import Extension, Krita

from .server import ZereServer


class ZereExtension(Extension):
    """Расширение Krita без пунктов меню: работает по запросу ZERE."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = ZereServer()

    def setup(self) -> None:
        self.server.start()

    def createActions(self, window) -> None:
        """Своих действий в меню нет: команды приходят от ZERE."""


Krita.instance().addExtension(ZereExtension(Krita.instance()))
