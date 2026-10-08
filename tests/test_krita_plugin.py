"""Плагин ZERE для Krita: SVG, клиент, установка и выбор способа рисования.

Krita в тестах не нужна: разметку SVG, протокол клиента, правку kritarc и
выбор «плагин или курсор» проверяем подставными объектами и настоящими
сокетами на 127.0.0.1. Файлы самого плагина разбираются как исходники —
он импортирует `krita`, которая есть только внутри Krita.
"""

from __future__ import annotations

import ast
import json
import socket
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.tools.drawing import drawing_geometry as geometry
from zere.tools.drawing import drawing_service, krita_install
from zere.tools.drawing.drawing_command_router import DrawingCommandRouter
from zere.tools.drawing.drawing_command_type import DrawingCommandType
from zere.tools.drawing.drawing_service import DrawingService
from zere.tools.drawing.drawing_svg import (
    DEFAULT_COLOR,
    escape_text,
    stroke_element,
    strokes_svg,
    text_svg,
)
from zere.tools.drawing.drawing_target import DrawingTarget
from zere.tools.drawing.krita_api import (
    DEFAULT_PORT,
    KritaApiClient,
    KritaPluginError,
    plugin_enabled,
    plugin_port,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "tools" / "krita_plugin"


# ── Подставной плагин (настоящий сокет, без Krita) ────────────────


class FakePlugin:
    """Одноразовый сервер плагина: принимает запрос, отдаёт заданный ответ."""

    def __init__(self, response) -> None:
        self.requests: list = []
        self._response = response
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            connection, _address = self._server.accept()
        except OSError:
            return

        with connection:
            data = b""

            while b"\n" not in data:
                chunk = connection.recv(4096)

                if not chunk:
                    break

                data += chunk

            line = data.split(b"\n", 1)[0]

            if line:
                self.requests.append(json.loads(line.decode("utf-8")))

            payload = self._response

            if not isinstance(payload, (bytes, str)):
                payload = json.dumps(payload, ensure_ascii=False)

            if isinstance(payload, str):
                payload = payload.encode("utf-8")

            connection.sendall(payload + b"\n")

    def close(self) -> None:
        try:
            self._server.close()
        except OSError:
            pass


def _free_port() -> int:
    """Свободный порт, который сразу освобождается: подключение упадёт."""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class FakeKritaClient:
    """Подставной клиент плагина: запоминает вызовы вместо рисования."""

    def __init__(self, document=None, shapes=1, segments=1, fail_info=None) -> None:
        self.calls: list = []
        self._document = document
        self._shapes = shapes
        self._segments = segments
        self._fail_info = fail_info

    def info(self):
        self.calls.append(("info",))
        if self._fail_info is not None:
            raise self._fail_info
        return {"ok": True, "document": self._document}

    def ensure_document(self, width: int, height: int):
        self.calls.append(("document", width, height))
        self._document = {"name": "ZERE", "width": width, "height": height}
        return {"ok": True, "created": True, "document": self._document}

    def draw_svg(self, svg: str, layer=None) -> int:
        self.calls.append(("svg", svg, layer))
        return self._shapes

    def paint(self, polylines, layer=None, pressure: float = 1.0) -> int:
        self.calls.append(("paint", polylines, layer))
        return self._segments

    def clear(self) -> str:
        self.calls.append(("clear",))
        return "убрал слои ZERE (1)"


# ── SVG фигур и текста ────────────────────────────────────────────


def test_svg_document_has_size_and_viewbox() -> None:
    svg = strokes_svg(geometry.square(), 400, 200)

    assert svg.startswith("<svg xmlns=\"http://www.w3.org/2000/svg\"")
    assert 'width="400"' in svg and 'height="200"' in svg
    assert 'viewBox="0 0 400 200"' in svg
    assert svg.endswith("</svg>")


def test_svg_closed_shape_becomes_polygon() -> None:
    """Замкнутая фигура — полигон: повтор первой точки в атрибуте не нужен."""
    svg = strokes_svg(geometry.rectangle(x0=0.0, y0=0.0, x1=1.0, y1=1.0), 101, 101)

    assert "<polygon" in svg and "<polyline" not in svg
    assert 'points="0.0,0.0 100.0,0.0 100.0,100.0 0.0,100.0"' in svg
    assert 'fill="none"' in svg
    assert f'stroke="{DEFAULT_COLOR}"' in svg


def test_svg_open_stroke_becomes_polyline() -> None:
    svg = strokes_svg(geometry.line(x0=0.0, y0=0.0, x1=1.0, y1=1.0), 101, 101)

    assert "<polyline" in svg and "<polygon" not in svg
    assert 'points="0.0,0.0 100.0,100.0"' in svg


def test_svg_single_point_becomes_dot() -> None:
    element = stroke_element([(0.5, 0.5)], 100, 100, stroke_width=4.0)

    assert element is not None and "<circle" in element
    assert 'cx="49.5"' in element and 'r="2.0"' in element


def test_svg_maps_shapes_to_document_size() -> None:
    """Координаты считаются от размера документа Krita, а не от окна."""
    small = strokes_svg(geometry.circle(), 200, 200)
    large = strokes_svg(geometry.circle(), 2000, 2000)

    assert 'points="' in small and 'points="' in large
    assert small != large, "размер документа не влияет на координаты"


def test_svg_is_empty_for_empty_input() -> None:
    assert strokes_svg([], 400, 300) == ""
    assert strokes_svg(geometry.square(), 0, 300) == ""
    assert text_svg("", 400, 300) == ""
    assert text_svg("привет", 0, 0) == ""


def test_svg_text_escapes_xml_and_fits_canvas() -> None:
    svg = text_svg("Привет & <мир>", 400, 300)

    assert "<text" in svg
    assert "&amp;" in svg and "&lt;мир&gt;" in svg
    assert "&" not in svg.replace("&amp;", "").replace("&lt;", "").replace("&gt;", "")
    assert 'text-anchor="middle"' in svg
    assert 'x="200.0"' in svg

    # Длинная строка ужимается, короткая — нет.
    long_svg = text_svg("я" * 200, 400, 300)
    short_svg = text_svg("я", 400, 300)

    def font_size(source: str) -> float:
        return float(source.split('font-size="', 1)[1].split('"', 1)[0])

    assert font_size(long_svg) < font_size(short_svg)
    assert font_size(long_svg) >= 8.0


def test_svg_text_lines_stacked() -> None:
    svg = text_svg("раз\nдва", 400, 300)

    assert svg.count("<text") == 2


def test_escape_text_orders_ampersand_first() -> None:
    assert escape_text("<&>") == "&lt;&amp;&gt;"
    assert escape_text('"кот"') == "&quot;кот&quot;"


# ── Клиент плагина ────────────────────────────────────────────────


def test_client_sends_command_and_reads_answer() -> None:
    plugin = FakePlugin({"ok": True, "shapes": 3})

    try:
        client = KritaApiClient(port=plugin.port)
        assert client.draw_svg("<svg/>") == 3
    finally:
        plugin.close()

    assert plugin.requests == [{"op": "svg", "svg": "<svg/>"}]


def test_client_paint_sends_polylines() -> None:
    plugin = FakePlugin({"ok": True, "segments": 7})

    try:
        client = KritaApiClient(port=plugin.port)
        assert client.paint([[(0, 0), (10, 10)]], layer="ZERE") == 7
    finally:
        plugin.close()

    request = plugin.requests[0]

    assert request["op"] == "stroke"
    assert request["polylines"] == [[[0.0, 0.0], [10.0, 10.0]]]
    assert request["layer"] == "ZERE"


def test_client_reports_absent_plugin() -> None:
    """Krita не запущена — понятный отказ, а не трассировка."""
    client = KritaApiClient(port=_free_port())

    try:
        client.ping()
    except KritaPluginError as error:
        assert "не отвечает" in str(error)
        assert "krita_install --check" in str(error)
    else:
        raise AssertionError("ожидалась ошибка плагина")


def test_client_reports_plugin_refusal() -> None:
    plugin = FakePlugin({"ok": False, "error": "нет документа"})

    try:
        client = KritaApiClient(port=plugin.port)

        try:
            client.info()
        except KritaPluginError as error:
            assert "нет документа" in str(error)
        else:
            raise AssertionError("ожидалась ошибка плагина")
    finally:
        plugin.close()


def test_client_reports_broken_answer() -> None:
    plugin = FakePlugin("это не json")

    try:
        client = KritaApiClient(port=plugin.port)

        try:
            client.ping()
        except KritaPluginError as error:
            assert "не JSON" in str(error)
        else:
            raise AssertionError("ожидалась ошибка разбора")
    finally:
        plugin.close()


def test_client_reads_port_from_kritarc() -> None:
    with tempfile.TemporaryDirectory() as folder:
        config = Path(folder) / "kritarc"
        config.write_text("[python]\nenable_zere=true\n\n[zere]\nport=8771\n", encoding="utf-8")

        assert plugin_port(config) == 8771

        config.write_text("[zere]\nport=мусор\n", encoding="utf-8")
        assert plugin_port(config) == DEFAULT_PORT

    assert plugin_port(Path("/нет/такого/файла")) == DEFAULT_PORT


def test_plugin_switch_disables_api() -> None:
    import os

    original = os.environ.get("ZERE_KRITA_PLUGIN")

    try:
        os.environ["ZERE_KRITA_PLUGIN"] = "0"
        assert plugin_enabled() is False

        os.environ["ZERE_KRITA_PLUGIN"] = "1"
        assert plugin_enabled() is True

        os.environ.pop("ZERE_KRITA_PLUGIN", None)
        assert plugin_enabled() is True
    finally:
        if original is None:
            os.environ.pop("ZERE_KRITA_PLUGIN", None)
        else:
            os.environ["ZERE_KRITA_PLUGIN"] = original


# ── kritarc и установка ───────────────────────────────────────────


def test_kritarc_read_and_write_settings() -> None:
    text = "first=1\n\n[python]\nenable_other=true\n\n[zere]\nport=8768\n"

    assert krita_install.read_setting(text, "zere", "port") == "8768"
    assert krita_install.read_setting(text, "python", "enable_other") == "true"
    assert krita_install.read_setting(text, "python", "enable_zere") is None
    assert krita_install.read_setting(text, "нет", "ключа") is None


def test_kritarc_write_creates_group_and_keeps_others() -> None:
    text = "[python]\nenable_other=true\n"
    updated = krita_install.enable_plugin(text)

    assert "[python]" in updated
    assert "enable_other=true" in updated
    assert "enable_zere=true" in updated
    assert krita_install.is_plugin_enabled(updated) is True

    # Повторная запись не плодит дубликаты, а меняет значение.
    twice = krita_install.write_setting(updated, "python", "enable_zere", "false")

    assert twice.count("enable_zere=") == 1
    assert krita_install.is_plugin_enabled(twice) is False


def test_kritarc_write_from_empty_text() -> None:
    updated = krita_install.write_setting("", "zere", "port", "9000")

    assert updated == "[zere]\nport=9000\n"
    assert krita_install.read_setting(updated, "zere", "port") == "9000"


def test_install_copies_plugin_and_enables_it() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        message = krita_install.install(
            source=PLUGIN_DIR,
            pykrita=root / "pykrita",
            kritarc=root / "kritarc",
            port=8770,
        )

        assert (root / "pykrita" / krita_install.DESKTOP_FILE).is_file()
        assert (root / "pykrita" / "zere" / "__init__.py").is_file()
        assert (root / "pykrita" / "zere" / "server.py").is_file()

        config = (root / "kritarc").read_text(encoding="utf-8")

        assert krita_install.is_plugin_enabled(config)
        assert krita_install.read_setting(config, "zere", "port") == "8770"
        assert "Перезапустите" in message


def test_install_refuses_broken_source() -> None:
    with tempfile.TemporaryDirectory() as folder:
        try:
            krita_install.install(source=Path(folder), pykrita=Path(folder) / "pykrita",
                                  kritarc=Path(folder) / "kritarc")
        except RuntimeError as error:
            assert "нет плагина" in str(error)
        else:
            raise AssertionError("установка из пустой папки должна отказывать")


# ── Файлы плагина ─────────────────────────────────────────────────


def test_desktop_descriptor_is_a_krita_python_plugin() -> None:
    text = (PLUGIN_DIR / "kritapykrita_zere.desktop").read_text(encoding="utf-8")

    assert "[Desktop Entry]" in text
    assert "ServiceTypes=Krita/PythonPlugin" in text
    assert "Type=Service" in text
    # Имя модуля в X-KDE-Library должно совпадать с пакетом рядом.
    assert "X-KDE-Library=zere" in text
    assert (PLUGIN_DIR / "zere" / "__init__.py").is_file()


def test_plugin_sources_parse_and_register_extension() -> None:
    init_source = (PLUGIN_DIR / "zere" / "__init__.py").read_text(encoding="utf-8")
    ast.parse(init_source)

    assert "addExtension" in init_source
    assert "def setup" in init_source, "плагин не стартует сервер при загрузке"

    server_source = (PLUGIN_DIR / "zere" / "server.py").read_text(encoding="utf-8")
    ast.parse(server_source)

    # Порт публикуется в настройках Krita, иначе ZERE его не найдёт.
    assert "writeSetting" in server_source and "readSetting" in server_source
    assert "127.0.0.1" in server_source, "плагин обязан слушать только localhost"


def test_plugin_handles_all_operations() -> None:
    """Набор команд плагина обязан совпадать с тем, что шлёт ZERE."""
    source = (PLUGIN_DIR / "zere" / "drawing.py").read_text(encoding="utf-8")
    ast.parse(source)

    for operation in ("ping", "info", "document", "svg", "stroke", "clear", "stats"):
        assert f'"{operation}"' in source, f"плагин не умеет «{operation}»"

    assert "addShapesFromSvg" in source, "фигуры рисуются не векторным слоем"
    assert "paintLine" in source, "мазки не идут через кисть Krita"

    client_source = (REPO_ROOT / "zere" / "tools" / "drawing" / "krita_api.py").read_text(
        encoding="utf-8"
    )

    for operation in ("ping", "info", "document", "svg", "stroke", "clear", "stats"):
        assert f'"{operation}"' in client_source, f"клиент не шлёт «{operation}»"


# ── Выбор способа рисования ───────────────────────────────────────


def test_service_prefers_plugin_for_krita() -> None:
    """При доступном плагине Krita рисуется без курсора."""
    client = FakeKritaClient(document={"name": "ZERE", "width": 800, "height": 600})
    service = DrawingService(target=DrawingTarget.KRITA, krita_api=client)

    original = DrawingService._run_cursor

    def forbidden(self, command):  # noqa: ANN001
        raise AssertionError("курсор не должен использоваться при живом плагине")

    DrawingService._run_cursor = forbidden

    try:
        answer = service.execute(DrawingCommandRouter().parse("нарисуй круг в крите"))
    finally:
        DrawingService._run_cursor = original

    assert "круг" in answer

    kinds = [call[0] for call in client.calls]

    assert kinds == ["info", "svg"], kinds

    svg = client.calls[1][1]

    assert svg.count("<polygon") == 1, "круг должен уйти полигоном"
    assert 'width="800"' in svg and 'height="600"' in svg


def test_service_creates_krita_document_when_none_open() -> None:
    client = FakeKritaClient(document=None)
    service = DrawingService(target=DrawingTarget.KRITA, krita_api=client)

    service.execute(DrawingCommandRouter().parse("нарисуй квадрат"))

    assert client.calls[0] == ("info",)
    assert client.calls[1] == ("document", *drawing_service.KRITA_NEW_DOCUMENT)
    assert client.calls[2][0] == "svg"


def test_service_falls_back_to_cursor_without_plugin() -> None:
    client = FakeKritaClient(fail_info=KritaPluginError("плагин не отвечает"))
    service = DrawingService(target=DrawingTarget.KRITA, krita_api=client)

    original = DrawingService._run_cursor
    DrawingService._run_cursor = lambda self, command: "нарисовал курсором"

    try:
        answer = service.execute(DrawingCommandRouter().parse("нарисуй круг"))
    finally:
        DrawingService._run_cursor = original

    assert answer == "нарисовал курсором"
    assert [call[0] for call in client.calls] == ["info"]


def test_service_does_not_use_plugin_for_paint() -> None:
    client = FakeKritaClient()
    service = DrawingService(target=DrawingTarget.PAINT, krita_api=client)

    original = DrawingService._run_cursor
    DrawingService._run_cursor = lambda self, command: "нарисовал курсором"

    try:
        assert service.execute(DrawingCommandRouter().parse("нарисуй круг")) == (
            "нарисовал курсором"
        )
    finally:
        DrawingService._run_cursor = original

    assert client.calls == []


def test_service_clear_and_text_through_plugin() -> None:
    client = FakeKritaClient(document={"name": "ZERE", "width": 800, "height": 600})
    service = DrawingService(target=DrawingTarget.KRITA, krita_api=client)

    assert "Очистил холст" in service.execute(
        DrawingCommandRouter().parse("очисти холст")
    )
    assert client.calls[-1] == ("clear",)

    # Текст: Krita собрала его из SVG — мазками не дублируем.
    answer = service.execute(DrawingCommandRouter().parse("напиши на холсте привет"))
    kinds = [call[0] for call in client.calls]

    assert kinds[-1] == "svg"
    assert "привет" in answer
    assert client.calls[-1][2] == drawing_service.KRITA_TEXT_LAYER


def test_service_text_falls_back_to_raster_brush() -> None:
    """Если Krita не собрала текст из SVG, строки идут мазками кистью."""
    client = FakeKritaClient(document={"name": "ZERE", "width": 800, "height": 600},
                            shapes=0)
    service = DrawingService(target=DrawingTarget.KRITA, krita_api=client)

    original = drawing_service.text_strokes
    drawing_service.text_strokes = lambda text: (
        [[(0.1, 0.2), (0.4, 0.2)], [(0.1, 0.3), (0.4, 0.3)]],
        10,
        5,
    )

    try:
        answer = service.execute(DrawingCommandRouter().parse("напиши на холсте привет"))
    finally:
        drawing_service.text_strokes = original

    assert "привет" in answer
    assert [call[0] for call in client.calls] == ["info", "svg", "paint"]
    assert len(client.calls[2][1]) == 2, "обе строки растра должны дойти до кисти"


def test_service_shape_falls_back_to_brush_when_svg_ignored() -> None:
    client = FakeKritaClient(document={"name": "ZERE", "width": 800, "height": 600},
                            shapes=0, segments=4)
    service = DrawingService(target=DrawingTarget.KRITA, krita_api=client)

    answer = service.execute(DrawingCommandRouter().parse("нарисуй звезду"))

    assert "звезду" in answer
    assert [call[0] for call in client.calls] == ["info", "svg", "paint"]


def test_service_run_dispatches_by_target_and_switch() -> None:
    """Структурная проверка: диспетчер знает про плагин и откат."""
    import inspect
    import os

    source = inspect.getsource(DrawingService._run)

    assert "plugin_enabled()" in source
    assert "DrawingTarget.KRITA" in source
    assert "_run_plugin(" in source
    assert "_run_cursor(" in source

    original = os.environ.get("ZERE_KRITA_PLUGIN")

    try:
        os.environ["ZERE_KRITA_PLUGIN"] = "0"
        client = FakeKritaClient(document={"name": "ZERE", "width": 800, "height": 600})
        service = DrawingService(target=DrawingTarget.KRITA, krita_api=client)

        original_cursor = DrawingService._run_cursor
        DrawingService._run_cursor = lambda self, command: "курсор"

        try:
            assert service.execute(DrawingCommandRouter().parse("нарисуй круг")) == "курсор"
        finally:
            DrawingService._run_cursor = original_cursor

        assert client.calls == [], "при выключенном плагине клиент не нужен"
    finally:
        if original is None:
            os.environ.pop("ZERE_KRITA_PLUGIN", None)
        else:
            os.environ["ZERE_KRITA_PLUGIN"] = original


# ── Раннер ────────────────────────────────────────────────────────


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"ПРОЙДЕНО: {len(tests)} тестов плагина Krita")


if __name__ == "__main__":
    main()
