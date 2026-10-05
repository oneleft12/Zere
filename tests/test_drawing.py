"""Рисование в Krita и Paint: разбор команд, геометрия, текст, обработчик.

Тесты идут без Windows: разбор, геометрия и перевод координат — чистые функции,
Win32-вызовы создаются лениво. Проверки, требующие Pillow (растр шрифта),
пропускаются, если Pillow не установлен.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zere.core.handlers.drawing_handler import DrawingHandler
from zere.tools.drawing import drawing_geometry as geometry
from zere.tools.drawing.drawing_command_router import DrawingCommandRouter
from zere.tools.drawing.drawing_command_type import DrawingCommandType
from zere.tools.drawing.drawing_service import DrawingService
from zere.tools.drawing.drawing_target import (
    DEFAULT_TARGET,
    DrawingTarget,
    display_name,
    spec_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Подменные объекты ─────────────────────────────────────────────


class _FakeService:
    """Заглушка DrawingService: запоминает команду, ничего не рисует."""

    def __init__(self) -> None:
        self.commands: list[object] = []

    def execute(self, command: object) -> str:
        self.commands.append(command)
        return "готово"


# ── Разбор команд ─────────────────────────────────────────────────


def test_router_switches_target() -> None:
    router = DrawingCommandRouter()

    for phrase, expected in (
        ("рисуй в крите", DrawingTarget.KRITA),
        ("рисуй в пейнте", DrawingTarget.PAINT),
        ("рисуй в krita", DrawingTarget.KRITA),
        ("переключись на пейнт", DrawingTarget.PAINT),
        ("рисуй в криту", DrawingTarget.KRITA),
        ("рисуй в паинте", DrawingTarget.PAINT),
    ):
        command = router.parse(phrase)
        assert command.type is DrawingCommandType.SET_TARGET, phrase
        assert command.target is expected, phrase


def test_router_parses_shapes() -> None:
    router = DrawingCommandRouter()

    for phrase, expected in (
        ("нарисуй круг", DrawingCommandType.DRAW_CIRCLE),
        ("нарисуй окружность", DrawingCommandType.DRAW_CIRCLE),
        ("нарисуй овал", DrawingCommandType.DRAW_ELLIPSE),
        ("нарисуй эллипс", DrawingCommandType.DRAW_ELLIPSE),
        ("нарисуй квадрат", DrawingCommandType.DRAW_SQUARE),
        ("нарисуй прямоугольник", DrawingCommandType.DRAW_RECTANGLE),
        ("нарисуй треугольник", DrawingCommandType.DRAW_TRIANGLE),
        ("нарисуй звезду", DrawingCommandType.DRAW_STAR),
        ("нарисуй звёздочку", DrawingCommandType.DRAW_STAR),
        ("нарисуй линию", DrawingCommandType.DRAW_LINE),
        ("начерти линию", DrawingCommandType.DRAW_LINE),
        ("нарисуй круг в пейнте", DrawingCommandType.DRAW_CIRCLE),
    ):
        command = router.parse(phrase)
        assert command.type is expected, f"{phrase} → {command.type}"


def test_router_shape_with_explicit_target() -> None:
    """Цель в одной фразе с фигурой: рисуем в названном приложении."""
    command = DrawingCommandRouter().parse("нарисуй квадрат в крите")

    assert command.type is DrawingCommandType.DRAW_SQUARE
    assert command.target is DrawingTarget.KRITA


def test_router_parses_text_with_anchor() -> None:
    router = DrawingCommandRouter()

    for phrase, expected in (
        ("нарисуй текст привет", "привет"),
        ("напиши на холсте ZERE", "ZERE"),
        ("напиши текст Привет, мир!", "Привет, мир!"),
        ("нарисуй надпись «Мяу»", "Мяу"),
    ):
        command = router.parse(phrase)
        assert command.type is DrawingCommandType.WRITE_TEXT, phrase
        assert command.value == expected, f"{phrase} → {command.value!r}"


def test_router_text_requires_explicit_anchor() -> None:
    """«напиши письмо другу» — это к LLM, а не рисование (иначе перехват)."""
    router = DrawingCommandRouter()

    assert router.parse("напиши письмо другу").type is DrawingCommandType.NONE
    assert router.parse("напиши стихотворение про осень").type is DrawingCommandType.NONE
    # А с названной целью — рисование.
    command = router.parse("напиши в пейнте привет")
    assert command.type is DrawingCommandType.WRITE_TEXT
    assert command.value == "привет"
    assert command.target is DrawingTarget.PAINT


def test_router_parses_clear_canvas() -> None:
    router = DrawingCommandRouter()

    for phrase in ("очисти холст", "сотри холст", "очисти холст в пейнте"):
        assert router.parse(phrase).type is DrawingCommandType.CLEAR_CANVAS, phrase


def test_router_ignores_questions_and_other_commands() -> None:
    """Вопросы и посторонние команды не должны становиться рисованием."""
    router = DrawingCommandRouter()

    for phrase in (
        "как нарисовать круг в крите",
        "расскажи про krita",
        "что такое круг",
        "привет",
        "как дела",
        "нарисуй кота",  # рисунок по описанию — следующий этап
        "открой криту",
        "сколько приложений",
    ):
        assert router.parse(phrase).type is DrawingCommandType.NONE, phrase


def test_router_ignores_negations() -> None:
    router = DrawingCommandRouter()

    for phrase in ("не рисуй круг", "нет, не надо", "не надо рисовать"):
        assert router.parse(phrase).type is DrawingCommandType.NONE, phrase

    assert router.is_negated("не рисуй круг") is True
    assert router.is_negated("нарисуй круг") is False


# ── Геометрия ─────────────────────────────────────────────────────


def _all_points(strokes: list) -> list:
    return [point for stroke in strokes for point in stroke]


def test_shapes_fit_inside_canvas() -> None:
    """Все фигуры укладываются в нормализованные 0..1."""
    for name, strokes in (
        ("круг", geometry.circle()),
        ("овал", geometry.ellipse()),
        ("прямоугольник", geometry.rectangle()),
        ("квадрат", geometry.square()),
        ("треугольник", geometry.triangle()),
        ("линия", geometry.line()),
        ("звезда", geometry.star()),
    ):
        points = _all_points(strokes)
        assert points, name

        for x, y in points:
            assert 0.0 <= x <= 1.0, f"{name}: x={x}"
            assert 0.0 <= y <= 1.0, f"{name}: y={y}"


def test_closed_shapes_return_to_start() -> None:
    """Замкнутые фигуры кончаются там же, где начались."""
    for name, strokes in (
        ("круг", geometry.circle()),
        ("овал", geometry.ellipse()),
        ("прямоугольник", geometry.rectangle()),
        ("квадрат", geometry.square()),
        ("треугольник", geometry.triangle()),
        ("звезда", geometry.star()),
    ):
        assert strokes[0][0] == strokes[0][-1], name

    # Линия — не замкнута.
    assert geometry.line()[0][0] != geometry.line()[0][-1]


def test_circle_is_round_and_square_is_square() -> None:
    points = _all_points(geometry.circle(cx=0.5, cy=0.5, radius=0.35))
    xs = [x for x, _ in points]
    ys = [y for _, y in points]

    # Радиус одинаков по обеим осям.
    assert abs((max(xs) - min(xs)) - (max(ys) - min(ys))) < 0.01
    assert abs(min(xs) - 0.15) < 0.01 and abs(max(xs) - 0.85) < 0.01

    square_points = _all_points(geometry.square(cx=0.5, cy=0.5, side=0.6))
    square_xs = [x for x, _ in square_points]
    square_ys = [y for _, y in square_points]
    assert abs((max(square_xs) - min(square_xs)) - (max(square_ys) - min(square_ys))) < 0.001


def test_star_has_expected_vertex_count() -> None:
    """5-конечная звезда: 10 вершин + замыкающая точка."""
    assert len(geometry.star(points_count=5)[0]) == 11
    assert len(geometry.star(points_count=6)[0]) == 13


# ── Канвас ────────────────────────────────────────────────────────


def test_canvas_cuts_insets_from_client_area() -> None:
    canvas = geometry.DrawingCanvas.from_client(
        100, 50, 800, 600, insets=(56, 12, 288, 12)
    )

    assert canvas.width == 800 - 56 - 288
    assert canvas.height == 600 - 12 - 12
    # Холст центрируется внутри клиентской области.
    assert canvas.left == 100 + (800 - canvas.width) // 2
    assert canvas.top == 50 + (600 - canvas.height) // 2


def test_canvas_never_exceeds_small_client_area() -> None:
    """Крошечное окно: холст не выходит за клиентскую область."""
    canvas = geometry.DrawingCanvas.from_client(
        10, 20, 60, 40, insets=(56, 12, 288, 12), min_size=120
    )

    assert canvas.width <= 60
    assert canvas.height <= 40
    assert canvas.left >= 10
    assert canvas.top >= 20


def test_canvas_maps_normalized_points_to_screen() -> None:
    canvas = geometry.DrawingCanvas(left=100, top=200, width=400, height=300)

    assert canvas.to_screen(0.0, 0.0) == (100, 200)
    assert canvas.to_screen(1.0, 1.0) == (499, 499)
    assert canvas.to_screen(0.5, 0.5) == (300, 350)


def test_canvas_clamps_out_of_range_points() -> None:
    """Выход за 0..1 не уводит курсор за пределы холста."""
    canvas = geometry.DrawingCanvas(left=0, top=0, width=101, height=101)

    assert canvas.to_screen(-5.0, -5.0) == (0, 0)
    assert canvas.to_screen(5.0, 5.0) == (100, 100)


# ── Растр в штрихи (текст) ────────────────────────────────────────


def test_bitmap_becomes_horizontal_strokes() -> None:
    rows = [
        [False, True, True, False, False],
        [False, True, False, True, False],
        [False, True, True, True, False],
    ]
    strokes = geometry.polyline_from_bitmap(rows)

    # Три строки дают четыре полосы: 1 + 2 + 1.
    assert len(strokes) == 4
    # Первая строка: одна полоса из двух пикселей.
    assert strokes[0] == [(0.2, 0.5 / 3), (0.6, 0.5 / 3)]
    # Вторая строка: две отдельные полосы.
    assert strokes[1] == [(0.2, 1.5 / 3), (0.4, 1.5 / 3)]
    assert strokes[2] == [(0.6, 1.5 / 3), (0.8, 1.5 / 3)]


def test_bitmap_edge_cases_do_not_crash() -> None:
    assert geometry.polyline_from_bitmap([]) == []
    assert geometry.polyline_from_bitmap([[]]) == []
    assert geometry.polyline_from_bitmap([[False, False]]) == []


def test_fit_strokes_keeps_aspect_and_centers() -> None:
    """Растр 10×5 (широкий) в квадратном холсте — по центру, пропорции целы."""
    strokes = [[(0.0, 0.0), (1.0, 1.0)]]
    fitted = geometry.fit_strokes(strokes, 10, 5, 400, 400, max_fraction=0.8)

    (x0, y0), (x1, y1) = fitted[0]
    width = x1 - x0
    height = y1 - y0

    # Клетки квадратные: ширина ровно вдвое больше высоты.
    assert abs(width - 2 * height) < 1e-9
    assert abs(width - 0.8) < 1e-9
    # Центрирование: отступы слева и справа равны.
    assert abs(x0 - (1 - 0.8) / 2) < 1e-9
    assert abs(y0 - (1 - 0.4) / 2) < 1e-9


def test_fit_strokes_handles_tall_source_and_bad_input() -> None:
    """Высокий растр ограничивается по высоте, пустой вход — пустой выход."""
    fitted = geometry.fit_strokes([[(0.0, 0.0), (1.0, 1.0)]], 5, 20, 400, 400)
    (x0, y0), (x1, y1) = fitted[0]

    assert abs((y1 - y0) - 0.9) < 1e-9
    assert (x1 - x0) < (y1 - y0)

    assert geometry.fit_strokes([], 10, 10, 400, 400) == []
    assert geometry.fit_strokes([[(0.0, 0.0)]], 0, 0, 400, 400) == []
    assert geometry.fit_strokes([[(0.0, 0.0)]], 10, 10, 0, 0) == []


def test_text_rendering_produces_strokes() -> None:
    """Растр кириллицы → штрихи. Требует Pillow, иначе SKIP."""
    try:
        import PIL  # noqa: F401
    except ImportError as ex:
        print(f"SKIP Pillow недоступен ({ex})")
        return

    from zere.tools.drawing.drawing_font import render_text_bitmap, text_strokes

    rows = render_text_bitmap("Привет")
    assert rows and rows[0], "растр текста пуст"

    dark = sum(1 for row in rows for value in row if value)
    assert dark > 0, "в растре не нашлось тёмных пикселей"
    # Ширина растра — в разумных границах (текст не «схлопнулся»).
    assert 8 <= len(rows[0]) <= 160

    strokes, columns, source_rows = text_strokes("Привет")
    assert strokes, "текст не превратился в штрихи"
    assert columns == len(rows[0])
    assert source_rows == len(rows)

    for stroke in strokes:
        assert len(stroke) == 2, "штрих текста — отрезок из двух точек"


# ── Обработчик и сервис ───────────────────────────────────────────


def test_handler_claims_drawing_commands() -> None:
    service = _FakeService()
    handler = DrawingHandler(service)  # type: ignore[arg-type]

    for phrase in ("нарисуй круг", "рисуй в крите", "напиши на холсте тест",
                   "очисти холст"):
        assert handler.can_handle(phrase) is True, phrase

    assert handler.handle("нарисуй круг") == "готово"
    assert service.commands[-1].type is DrawingCommandType.DRAW_CIRCLE


def test_handler_does_not_steal_llm_requests() -> None:
    """Иначе «напиши письмо другу» и обычные вопросы уходили бы в рисование."""
    handler = DrawingHandler(_FakeService())  # type: ignore[arg-type]

    for phrase in (
        "напиши письмо другу",
        "как нарисовать круг в крите",
        "что такое круг",
        "привет",
        "расскажи про krita",
        "не рисуй круг",
        "открой криту",
    ):
        assert handler.can_handle(phrase) is False, phrase


def test_service_reports_target_without_drawing() -> None:
    """Смена цели и нераспознанная команда не трогают Win32."""
    service = DrawingService()

    assert service.target is DEFAULT_TARGET

    response = service.execute(
        DrawingCommandRouter().parse("рисуй в крите")
    )
    assert "Krita" in response
    assert service.target is DrawingTarget.KRITA

    assert service.execute(DrawingCommandRouter().parse("привет")) == (
        "Команда рисования не распознана."
    )


def test_service_refuses_on_non_windows() -> None:
    """Вне Windows рисование не падает, а объясняет отказ."""
    if sys.platform == "win32":
        print("SKIP проверка отказа вне Windows (мы в Windows)")
        return

    service = DrawingService()
    response = service.execute(DrawingCommandRouter().parse("нарисуй круг"))

    assert "Windows" in response, response


def test_interpolation_covers_segment() -> None:
    """Интерполяция доходит до конца отрезка и не теряет шаги."""
    points = DrawingService._interpolate((0, 0), (20, 0))

    assert points[-1] == (20, 0)
    assert points[0] == (5, 0)
    # Шаг ~STEP_PIXELS: на 20 px — четыре точки.
    assert len(points) == 4

    # Нулевой отрезок: одна точка, а не пустой список.
    assert DrawingService._interpolate((7, 7), (7, 7)) == [(7, 7)]


def test_target_specs_cover_store_paint_and_titles() -> None:
    """Paint в Windows 11 — Store-приложение: процесс PaintApp.exe, не mspaint.

    Без этого окно не находилось бы и ZERE запускал бы Paint заново
    на каждую команду. Заголовок — запасной признак поиска окна.
    """
    paint = spec_for(DrawingTarget.PAINT)

    assert "mspaint" in paint.process_names
    assert "paintapp" in paint.process_names
    assert "paint" in paint.title_hints

    krita = spec_for(DrawingTarget.KRITA)

    assert "krita" in krita.process_names
    assert "krita" in krita.title_hints

    for spec in (paint, krita):
        assert spec.title_hints, "нужен запасной поиск по заголовку окна"
        assert spec.launch_command
        assert len(spec.insets) == 4
        # Холст обязан остаться осмысленным: отступы не съедают окно целиком.
        assert spec.insets[0] + spec.insets[2] < 400


def test_window_title_matching_is_precise() -> None:
    """Заголовок принимается по сегментам, а не подстрокой.

    Иначе окно браузера с вкладкой «Paint tutorial» сошло бы за Paint,
    и ZERE рисовал бы в браузере.
    """
    from zere.tools.drawing.drawing_service import _title_matches

    assert _title_matches("Untitled - Paint", ("paint",)) is True
    assert _title_matches("Безымянный — Paint", ("paint",)) is True
    assert _title_matches("Безымянный — Krita", ("krita",)) is True
    assert _title_matches("my_drawing.kra - Krita", ("krita",)) is True

    assert _title_matches("Paint tutorial - Firefox", ("paint",)) is False
    assert _title_matches("Untitled - Firefox", ("paint",)) is False
    assert _title_matches("", ("paint",)) is False
    assert _title_matches("Безымянный — Krita", ("paint",)) is False


def test_plan_moves_caps_points_and_covers_ends() -> None:
    """Потолок перемещений на штрих и доходимость до конца ломаной.

    Без потолка длинная окружность при паузе 10 мс рисовалась бы секундами.
    """
    from zere.tools.drawing import drawing_service

    canvas = geometry.DrawingCanvas(left=0, top=0, width=800, height=600)
    circle_points = [canvas.to_screen(x, y) for (x, y) in geometry.circle()[0]]

    moves = drawing_service.DrawingService._plan_moves(circle_points)

    assert moves, "круг не дал ни одного перемещения"
    assert moves[-1] == circle_points[-1], "штрих не дошёл до конца"

    # Длинный отрезок упирается в потолок, а не распухает до сотен точек.
    long_line = [(0, 0), (4000, 0)]
    assert len(drawing_service.DrawingService._plan_moves(long_line)) <= (
        drawing_service.MAX_POINTS_PER_STROKE + 1
    )

    assert drawing_service.DrawingService._plan_moves([(5, 5)]) == []
    assert drawing_service.DrawingService._plan_moves([]) == []


def test_canvas_guard_rejects_degenerate_area() -> None:
    """Вырожденный холст — отказ, а не молчаливая точка вместо фигуры."""
    from zere.tools.drawing.drawing_service import is_canvas_usable

    assert is_canvas_usable(geometry.DrawingCanvas(0, 0, 800, 600)) is True
    assert is_canvas_usable(geometry.DrawingCanvas(0, 0, 80, 80)) is True

    for width, height in ((0, 0), (1, 1), (79, 600), (800, 79)):
        assert is_canvas_usable(
            geometry.DrawingCanvas(0, 0, width, height)
        ) is False, f"{width}x{height} должен быть отвергнут"


def test_moves_are_injected_not_just_repositioned() -> None:
    """Регрессия «рисует только точку».

    Одного SetCursorPos мало: движение должно уходить в очередь ввода окна
    событием MOUSEEVENTF_MOVE|MOUSEEVENTF_ABSOLUTE — иначе приложение видит
    нажатие и отпускание в одной точке.
    """
    import inspect

    from zere.tools.drawing import drawing_service

    source = inspect.getsource(drawing_service._move_to)

    assert "SetCursorPos" in source
    assert "MOUSEEVENTF_MOVE" in source, "_move_to не отправляет событие MOVE"
    assert "MOUSEEVENTF_ABSOLUTE" in source, "_move_to не использует абсолютные координаты"
    assert "_mouse_event(flags" in source or "_mouse_event(" in source

    # Нормировка на виртуальный рабочий стол: иначе мультимонитор уезжает.
    assert "SM_CXVIRTUALSCREEN" in inspect.getsource(drawing_service._absolute_coords)

    # Пауза между движениями: при 2 мс Windows склеивает WM_MOUSEMOVE.
    assert drawing_service.MOVE_DELAY >= 0.005, (
        "слишком маленькая пауза — Windows склеит WM_MOUSEMOVE в одно событие"
    )


def test_dpi_awareness_enabled_before_measuring_window() -> None:
    """Координаты на масштабированных дисплеях должны быть физическими.

    Иначе GetClientRect отдаёт виртуализированные пиксели, холст схлопывается
    и фигура превращается в точку.
    """
    import inspect

    from zere.tools.drawing import drawing_service

    run_source = inspect.getsource(drawing_service.DrawingService._run)
    awareness_source = inspect.getsource(drawing_service._enable_dpi_awareness)

    assert "_enable_dpi_awareness()" in run_source, "DPI не включается перед рисованием"
    assert "SetThreadDpiAwarenessContext" in awareness_source
    assert "SetProcessDPIAware" in awareness_source, "нет отката для старых Windows"

    # Awareness обязан включаться до измерений окна.
    assert run_source.index("_enable_dpi_awareness()") < run_source.index("_client_rect")
    assert run_source.index("_enable_dpi_awareness()") < run_source.index("_find_or_launch")


def test_run_reports_drawing_diagnostics() -> None:
    """Строка [Drawing] нужна, чтобы отличить сбой от успеха без отладчика."""
    import inspect

    from zere.tools.drawing import drawing_service

    source = inspect.getsource(drawing_service.DrawingService._run)

    for token in ("[Drawing]", "холст=", "штрихов=", "перемещений="):
        assert token in source, f"в диагностике нет {token}"

    assert "moves == 0" in source, "нет проверки «ни одного перемещения»"


def test_win32_input_struct_matches_windows_layout() -> None:
    """Размер INPUT обязан совпадать с Windows, иначе SendInput не сработает.

    Проверяется на любой ОС: ширины полей заданы явно (c_uint32/c_int32),
    а выравнивание делает ctypes.
    """
    import ctypes as ctypes_module

    from zere.tools.drawing import drawing_service

    pointer_size = ctypes_module.sizeof(ctypes_module.c_void_p)

    if pointer_size == 8:
        assert ctypes_module.sizeof(drawing_service._INPUT) == 40
    else:
        assert ctypes_module.sizeof(drawing_service._INPUT) == 28

    # dwExtraInfo — последнее поле и указатель: его ширина и определяет layout.
    assert drawing_service._MOUSEINPUT.dwExtraInfo.size == pointer_size


def test_hwnd_returning_calls_have_explicit_restype() -> None:
    """Регрессия: без restype ctypes обрезает 64-битные HWND до int.

    Тогда GetForegroundWindow никогда не совпадёт с найденным окном и
    рисование откажет с «не удалось переключиться».
    """
    import inspect

    from zere.tools.drawing import drawing_service

    source = inspect.getsource(drawing_service._get_user32)

    for call in (
        "SendInput",
        "SetCursorPos",
        "GetForegroundWindow",
        "SetForegroundWindow",
        "BringWindowToTop",
        "ShowWindow",
        "GetWindow",
        "GetWindowTextLengthW",
        "GetWindowTextW",
        "GetWindowThreadProcessId",
        "GetClientRect",
        "ClientToScreen",
    ):
        assert f"{call}.restype" in source, f"{call}: не задан restype"

    # Именно HWND-функции обязаны объявлять restype: иначе int (32 бита).
    for call in ("GetForegroundWindow", "GetWindow"):
        assert f"{call}.restype" in source, call

    # Колбэк EnumWindows типизируется там, где известен его тип.
    assert "EnumWindows.argtypes" in inspect.getsource(drawing_service._enum_windows)


def test_pipeline_places_drawing_before_ai() -> None:
    """Структурная проверка: DrawingHandler в конвейере и раньше AIHandler.

    Импортировать services.py нельзя на Linux (psutil/winreg), поэтому
    проверяем AST-ом — как scripts/check_port.py.
    """
    source = (REPO_ROOT / "zere" / "core" / "services.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    pipeline_calls: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_create_handler_pipeline":
            continue

        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                if sub.func.attr == "get" and sub.args:
                    argument = sub.args[0]
                    if isinstance(argument, ast.Name):
                        pipeline_calls.append(argument.id)

    assert "DrawingHandler" in pipeline_calls, "DrawingHandler не в конвейере"
    assert "AIHandler" in pipeline_calls, "AIHandler не в конвейере"
    assert pipeline_calls.index("DrawingHandler") < pipeline_calls.index("AIHandler"), (
        "DrawingHandler должен идти раньше AIHandler"
    )

    assert "DrawingHandler" in source


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
    print(f"ПРОЙДЕНО: {len(tests)} тестов рисования")


if __name__ == "__main__":
    main()
