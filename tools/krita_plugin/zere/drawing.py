"""Рисование в активном документе Krita — тем, что даёт родной API.

Ключевое отличие от эмуляции мыши: документ получает точные векторные фигуры
(`Document.createVectorLayer` + `VectorLayer.addShapesFromSvg`) и настоящие мазки
кистью (`Node.paintLine` — с динамикой выбранного пресета). Окно может быть
свёрнуто, курсор не двигается, координаты не зависят от раскладки доков.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from krita import Krita

try:  # Krita 5 — PyQt5, Krita 6 — PyQt6
    from PyQt5.QtCore import QPoint
except ImportError:  # pragma: no cover - ветка для Krita 6
    from PyQt6.QtCore import QPoint

#: Префикс имён слоёв ZERE: по нему их находит очистка холста.
LAYER_PREFIX = "ZERE"

#: Размер нового документа, если в Krita не открыто ни одного.
NEW_DOCUMENT_SIZE = (1600, 1200)


class DrawingError(RuntimeError):
    """Команда не выполнена: понятная причина для ответа ZERE."""


def active_document():
    """Активный документ Krita или None."""
    return Krita.instance().activeDocument()


def ensure_document(width: int = NEW_DOCUMENT_SIZE[0],
                    height: int = NEW_DOCUMENT_SIZE[1]):
    """Активный документ; если его нет — создаёт новый и показывает окно.

    Возвращает (документ, создан_ли).
    """
    document = active_document()

    if document is not None:
        return document, False

    app = Krita.instance()
    document = app.createDocument(width, height, "ZERE", "RGBA", "U8", "", 72.0)

    if document is None:
        raise DrawingError("Krita не смогла создать документ")

    window = app.activeWindow()

    if window is not None:
        window.addView(document)

    return document, True


def document_info() -> Dict[str, object]:
    """Что открыто сейчас: имя и размер документа (или None)."""
    document = active_document()

    if document is None:
        return {"document": None}

    return {
        "document": {
            "name": document.name(),
            "width": int(document.width()),
            "height": int(document.height()),
        }
    }


def _root_layer(document, name: str, layer_type: str):
    """Новый слой ZERE поверх остальных.

    Векторный слой создаётся именно `createVectorLayer`: обычный `Node` из
    `createNode` — базовый класс без `addShapesFromSvg`, и SVG в него не ляжет.
    """
    if layer_type == "vectorlayer":
        layer = document.createVectorLayer(name)
    else:
        layer = document.createNode(name, layer_type)

    if layer is None:
        raise DrawingError(f"Krita не смогла создать слой «{name}»")

    layer.setName(name)
    root = document.rootNode()

    if root is None or not root.addChildNode(layer, None):
        raise DrawingError(f"Не удалось добавить слой «{name}» в документ")

    return layer


def draw_svg(svg: str, layer_name: str = f"{LAYER_PREFIX} фигуры") -> int:
    """Кладёт SVG в новый векторный слой; возвращает число фигур.

    Ноль фигур — признак того, что импортёр Krita не понял разметку:
    вызывающий (ZERE) тогда повторяет рисунок мазками.
    """
    if not svg or "<svg" not in svg:
        raise DrawingError("пустой SVG")

    document, _created = ensure_document()
    layer = _root_layer(document, layer_name, "vectorlayer")

    shapes = layer.addShapesFromSvg(svg)
    document.refreshProjection()

    return len(shapes or [])


def stroke(polylines: Sequence[Sequence[Sequence[float]]],
           layer_name: str = f"{LAYER_PREFIX} кисть",
           pressure: float = 1.0) -> int:
    """Проводит ломаные настоящей кистью Krita; возвращает число отрезков.

    Ломаных может быть много: так рисуется текст (каждая строка растра — свой
    штрих) и фигуры, если импортёр SVG их не понял.
    """
    lines = [
        [(float(point[0]), float(point[1])) for point in line]
        for line in polylines
        if len(line) >= 2
    ]

    if not lines:
        raise DrawingError("для мазка нужно минимум две точки")

    document, _created = ensure_document()
    layer = _root_layer(document, layer_name, "paintlayer")
    document.setActiveNode(layer)

    segments = 0

    for line in lines:
        for start, end in zip(line, line[1:]):
            layer.paintLine(
                QPoint(int(round(start[0])), int(round(start[1]))),
                QPoint(int(round(end[0])), int(round(end[1]))),
                pressure,
                pressure,
            )
            segments += 1

    document.refreshProjection()

    return segments


def zere_layers(document) -> List[object]:
    """Слои, созданные ZERE (по префиксу имени)."""
    root = document.rootNode()

    if root is None:
        return []

    return [
        node
        for node in root.childNodes()
        if (node.name() or "").startswith(LAYER_PREFIX)
    ]


def clear() -> str:
    """Очищает холст: снимает слои ZERE, иначе — действие Krita «Clear».

    Сначала убираем то, что нарисовал ZERE: чужую работу пользователя
    «очисти холст» затирать не должна.
    """
    document, created = ensure_document()

    if created:
        return "документ только создан — очищать нечего"

    layers = zere_layers(document)

    if layers:
        for layer in layers:
            layer.remove()

        document.refreshProjection()
        return f"убрал слои ZERE ({len(layers)})"

    app = Krita.instance()
    triggered = []

    for action_name in ("select_all", "clear", "deselect"):
        action = app.action(action_name)

        if action is not None:
            action.trigger()
            triggered.append(action_name)

    document.refreshProjection()

    if not triggered:
        raise DrawingError("в Krita не нашлись действия выделения и очистки")

    return "выделил и стёр активный слой"


def ink_stats(step: int = 4) -> Dict[str, object]:
    """Сколько нарисовано в документе: непрозрачные и тёмные пиксели.

    Читаем объединённое изображение документа (`Document.projection`) — так
    видно и векторные слои, и мазки. Нужно, чтобы ZERE мог честно сказать,
    появился рисунок или нет (как счётчик перемещений при рисовании курсором).
    Пиксели берём через шаг: полный перебор гигапиксельного холста заморозил бы
    интерфейс Krita.
    """
    document = active_document()

    if document is None:
        raise DrawingError("в Krita нет открытого документа")

    width = int(document.width())
    height = int(document.height())
    image = document.projection(0, 0, width, height)

    if image is None:
        raise DrawingError("Krita не отдала изображение документа")

    stride = max(1, int(step))
    sampled = 0
    opaque = 0
    dark = 0

    for y in range(0, height, stride):
        for x in range(0, width, stride):
            color = image.pixelColor(x, y)
            sampled += 1

            if color.alpha() > 0:
                opaque += 1

                if color.red() + color.green() + color.blue() < 300:
                    dark += 1

    return {
        "width": width,
        "height": height,
        "step": stride,
        "sampled": sampled,
        "opaque": opaque,
        "dark": dark,
        "layers": len(zere_layers(document)),
    }


def handle(request: Dict[str, object]) -> Dict[str, object]:
    """Выполняет одну команду ZERE и возвращает ответ.

    Здесь же разбор запроса: сервер (`server.py`) отвечает только за
    транспорт, поэтому протокол можно проверять отдельно от сокета.
    """
    operation = str(request.get("op") or "")

    if operation == "ping":
        return {"ok": True, "plugin": "zere", "version": 1}

    if operation == "info":
        return {"ok": True, **document_info()}

    if operation == "document":
        width = int(request.get("width") or NEW_DOCUMENT_SIZE[0])
        height = int(request.get("height") or NEW_DOCUMENT_SIZE[1])
        _document, created = ensure_document(width, height)
        return {"ok": True, "created": created, **document_info()}

    if operation == "svg":
        shapes = draw_svg(str(request.get("svg") or ""),
                          str(request.get("layer") or f"{LAYER_PREFIX} фигуры"))
        return {"ok": True, "shapes": shapes}

    if operation == "stroke":
        polylines = request.get("polylines") or []

        if not polylines and request.get("points"):
            # Одна ломаная — частный случай: так удобнее вызывать и проверять.
            polylines = [request["points"]]

        segments = stroke(
            polylines,
            str(request.get("layer") or f"{LAYER_PREFIX} кисть"),
            float(request.get("pressure") or 1.0),
        )
        return {"ok": True, "segments": segments}

    if operation == "clear":
        return {"ok": True, "detail": clear()}

    if operation == "stats":
        return {"ok": True, **ink_stats(int(request.get("step") or 4))}

    raise DrawingError(f"неизвестная команда «{operation}»")
