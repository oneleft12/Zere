"""Реестр интентов ZERE — единственный список того, что умеет роутер Jev.

Идея (docs/JEV_ROUTER.md): Jev не выполняет команды, он только выбирает
интент из этого списка и возвращает калиброванную уверенность. Действует
код: интент → каноническая фраза → существующий обработчик пайплайна.

Почему каноническая фраза, а не прямой вызов обработчика: обработчики
(`zere/core/handlers/*`) уже умеют разбирать свои команды и подтверждать
необратимые действия. Роутер переводит свободную формулировку в ту фразу,
которую обработчик гарантированно понимает, — тогда поведение и все
защиты (системные процессы, «да/нет») остаются прежними.

Инварианты, которые проверяет `tests/test_jev_router.py`:
- id интентов уникальны;
- `handler_file` существует, а `local_trigger` встречается в исходнике
  обработчика — если обработчик переписали и фразу убрали, тест падает;
- канонические фразы без слотов совпадают с `local_trigger`.

Слоты. Jev возвращает только типизированные значения (choice / score /
noul) — свободный текст он не извлекает. Поэтому:
- `KIND_ENUM` — выбор из известного множества (приложения, процессы,
  фигуры): Jev выбирает вариант, код проверяет, что вариант из списка
  (защита от подстановки чужого значения);
- `KIND_SCORE` — позиция на шкале (громкость 0–100);
- `KIND_TEXT` — свободный текст (имя файла, текст для холста, факт для
  памяти): извлекается локально (`extract_payload`), а если извлечь не
  удалось — роутер переспрашивает, но не выдумывает аргумент.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── Виды слотов ─────────────────────────────────────────────────────
KIND_ENUM = "enum"
KIND_SCORE = "score"
KIND_TEXT = "text"

# ── Источники кандидатов для enum-слотов ────────────────────────────
SOURCE_STATIC = "static"
SOURCE_APPS = "apps"
SOURCE_PROCESSES = "processes"

# ── Подтверждение необратимого действия ─────────────────────────────
CONFIRM_NONE = "none"
#: Спрашивает сам обработчик («да/нет», SafeActionManager).
CONFIRM_HANDLER = "handler"
#: Должен спросить роутер до отправки команды в пайплайн.
CONFIRM_ROUTER = "router"

#: Формы фигур, которые понимает DrawingCommandRouter (Python-редакция).
SHAPES: tuple[str, ...] = (
    "круг",
    "квадрат",
    "прямоугольник",
    "треугольник",
    "овал",
    "звезда",
    "линия",
)

#: Цели рисования (DrawingTarget: krita.exe / mspaint.exe).
DRAW_TARGETS: tuple[str, ...] = ("крите", "пейнте")

#: Шаг шкалы громкости: score-вопрос даёт позицию, код переводит в проценты.
VOLUME_STEPS: tuple[int, ...] = tuple(range(0, 101, 10))

#: Слова-заполнители, которые убираются при локальном извлечении текста.
FILLER_WORDS: tuple[str, ...] = (
    "пожалуйста",
    "под названием",
    "с названием",
    "по имени",
    "именем",
    "который называется",
    "которая называется",
    "мне нужно",
    "я хочу",
    "хочу",
    "нужно",
    "давай",
    "на рабочем столе",
    "что",
    "чтобы",
    "это",
    "мне",
    "на",
    "в",
)


@dataclass(frozen=True)
class Slot:
    """Аргумент интента: имя, вид и как его получить."""

    #: Имя подстановки в `Intent.canonical` и id вопроса для Jev.
    name: str
    kind: str
    #: Инструкция для Jev (человеческий вопрос).
    question: str
    #: Пояснение значения — уходит в criteria как описание варианта.
    description: str = ""
    #: Для KIND_ENUM: откуда брать кандидатов.
    source: str = SOURCE_STATIC
    #: Для KIND_ENUM с SOURCE_STATIC: готовый список.
    options: tuple[str, ...] = ()
    #: Для KIND_TEXT: фразы-триггеры, которые убираются перед извлечением.
    triggers: tuple[str, ...] = ()
    #: Обязателен ли слот: без него команду не построить.
    required: bool = True


@dataclass(frozen=True)
class Intent:
    """Интент: что делать и какой фразой это делается."""

    id: str
    domain: str
    #: Описание для Jev — уходит в criteria выбора интента.
    title: str
    #: Примеры формулировок (тоже в criteria — Jev учится на них).
    examples: tuple[str, ...]
    #: Каноническая фраза для пайплайна; слоты — в фигурных скобках.
    canonical: str
    #: Обработчик пайплайна, который примет каноническую фразу.
    handler: str
    #: Файл обработчика (проверяется тестом на существование).
    handler_file: str
    #: Точная фраза из `can_handle` обработчика (проверяется тестом).
    local_trigger: str
    slots: tuple[Slot, ...] = ()
    confirm: str = CONFIRM_NONE
    #: Спросить, если слот не извлёкся / уверенность ниже порога.
    clarify_question: str = ""
    #: Только Python-редакция (в C#-редакции рисования нет).
    python_only: bool = False

    @property
    def critical(self) -> bool:
        """Необратимое действие: нужен повышенный порог уверенности."""
        return self.confirm != CONFIRM_NONE


def _text_slot(
    name: str,
    question: str,
    triggers: tuple[str, ...],
    *,
    description: str = "свободный текст из фразы пользователя",
) -> Slot:
    return Slot(
        name=name,
        kind=KIND_TEXT,
        question=question,
        description=description,
        triggers=triggers,
    )


def _enum_slot(
    name: str,
    question: str,
    source: str,
    *,
    options: tuple[str, ...] = (),
    description: str = "",
    triggers: tuple[str, ...] = (),
    required: bool = True,
) -> Slot:
    return Slot(
        name=name,
        kind=KIND_ENUM,
        question=question,
        description=description,
        source=source,
        options=options,
        # Триггеры нужны для деградации: если списка кандидатов нет
        # (не Windows, нет индекса), аргумент снимается локально.
        triggers=triggers,
        required=required,
    )


#: Вопрос к Jev о запрете/отмене: «не выключай компьютер» — не команда.
NEGATION_QUESTION = (
    "Пользователь запрещает, отменяет действие или сообщает, что оно не нужно? "
    "Ответ «да» — только если действие НЕ надо выполнять."
)


INTENTS: tuple[Intent, ...] = (
    # ── Память ──────────────────────────────────────────────────────
    Intent(
        id="memory_save",
        domain="memory",
        title="Запомнить факт о пользователе",
        examples=("запомни, что меня зовут Дан", "сохрани в память проект ZERE"),
        canonical="запомни {payload}",
        handler="MemoryHandler",
        handler_file="zere/core/handlers/memory_handler.py",
        local_trigger="запомни",
        slots=(
            _text_slot(
                "payload",
                "Что именно нужно запомнить?",
                ("запомни", "сохрани", "не забудь", "запиши", "обнови память"),
            ),
        ),
        clarify_question="Что запомнить?",
    ),
    Intent(
        id="memory_update",
        domain="memory",
        title="Изменить ранее сохранённый факт",
        examples=("обнови память проект = AI VOCALPLUS", "измени память имя"),
        canonical="обнови память {payload}",
        handler="MemoryHandler",
        handler_file="zere/core/handlers/memory_handler.py",
        local_trigger="обнови память",
        slots=(
            _text_slot(
                "payload",
                "Какой факт изменить и на что?",
                ("обнови память", "измени память"),
            ),
        ),
        clarify_question="Какой факт изменить и на что?",
    ),
    Intent(
        id="memory_forget",
        domain="memory",
        title="Забыть один факт",
        examples=("забудь имя", "удали из памяти проект"),
        canonical="забудь {payload}",
        handler="MemoryHandler",
        handler_file="zere/core/handlers/memory_handler.py",
        local_trigger="забудь",
        slots=(
            _text_slot(
                "payload",
                "Что забыть (ключ записи)?",
                ("забудь", "забыть", "удали из памяти", "очисти запись"),
            ),
        ),
        confirm=CONFIRM_ROUTER,
        clarify_question="Что забыть?",
    ),
    Intent(
        id="memory_show",
        domain="memory",
        title="Показать всё, что ZERE помнит",
        examples=("покажи память", "что ты помнишь", "все воспоминания"),
        canonical="покажи память",
        handler="MemoryHandler",
        handler_file="zere/core/handlers/memory_handler.py",
        local_trigger="покажи память",
    ),
    Intent(
        id="memory_clear",
        domain="memory",
        title="Полностью очистить память",
        examples=("очисти память", "удали все воспоминания"),
        canonical="очисти память",
        handler="MemoryHandler",
        handler_file="zere/core/handlers/memory_handler.py",
        local_trigger="очисти память",
        confirm=CONFIRM_ROUTER,
    ),
    # ── История диалогов ────────────────────────────────────────────
    Intent(
        id="history_show",
        domain="history",
        title="Показать историю разговоров",
        examples=("покажи историю", "что мы обсуждали", "наши диалоги"),
        canonical="покажи историю",
        handler="ConversationHandler",
        handler_file="zere/core/handlers/conversation_handler.py",
        local_trigger="покажи историю",
    ),
    Intent(
        id="history_clear",
        domain="history",
        title="Очистить историю разговоров",
        examples=("очисти историю", "сбрось диалоги"),
        canonical="очисти историю",
        handler="ConversationHandler",
        handler_file="zere/core/handlers/conversation_handler.py",
        local_trigger="очисти историю",
        confirm=CONFIRM_ROUTER,
    ),
    # ── Приложения ──────────────────────────────────────────────────
    Intent(
        id="app_open",
        domain="apps",
        title="Открыть приложение",
        examples=("открой дискорд", "запусти хром", "включи спотифай"),
        canonical="открой {app}",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="открой ",
        slots=(
            _enum_slot(
                "app",
                "Какое приложение открыть?",
                SOURCE_APPS,
                description="приложение из индекса установленных",
                triggers=("открой", "запусти", "включи", "открыть"),
            ),
        ),
        clarify_question="Какое приложение открыть?",
    ),
    Intent(
        id="app_find",
        domain="apps",
        title="Найти приложение в индексе",
        examples=("найди хром", "есть ли у меня стим"),
        canonical="найди {app}",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="найди ",
        slots=(
            _enum_slot(
                "app",
                "Какое приложение искать?",
                SOURCE_APPS,
                description="приложение из индекса установленных",
                triggers=("найди", "поищи", "есть ли"),
            ),
        ),
        clarify_question="Какое приложение искать?",
    ),
    Intent(
        id="app_index_rebuild",
        domain="apps",
        title="Переиндексировать установленные приложения",
        examples=("обнови индекс", "переиндексируй приложения"),
        canonical="обнови индекс",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="обнови индекс",
    ),
    Intent(
        id="app_count",
        domain="apps",
        title="Сколько приложений в индексе",
        examples=("сколько приложений", "сколько программ в индексе"),
        canonical="сколько приложений",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="сколько приложений",
    ),
    # ── Процессы ────────────────────────────────────────────────────
    Intent(
        id="process_list",
        domain="processes",
        title="Список процессов (самые тяжёлые)",
        examples=("процессы", "что запущено", "список задач"),
        canonical="процессы",
        handler="ProcessHandler",
        handler_file="zere/core/handlers/process_handler.py",
        local_trigger="процессы",
    ),
    Intent(
        id="process_find",
        domain="processes",
        title="Найти процесс по имени",
        examples=("найди процесс хром", "есть ли процесс стим"),
        canonical="найди процесс {process}",
        handler="ProcessHandler",
        handler_file="zere/core/handlers/process_handler.py",
        local_trigger="найди процесс",
        slots=(
            _enum_slot(
                "process",
                "Какой процесс искать?",
                SOURCE_PROCESSES,
                description="имя запущенного процесса",
                triggers=("найди процесс", "найти процесс", "поищи процесс", "есть ли процесс", "процесс"),
            ),
        ),
        clarify_question="Какой процесс искать?",
    ),
    Intent(
        id="process_kill",
        domain="processes",
        title="Завершить процесс",
        examples=("закрой процесс дискорд", "убей процесс нотпад", "заверши хром"),
        canonical="закрой процесс {process}",
        handler="ProcessHandler",
        handler_file="zere/core/handlers/process_handler.py",
        local_trigger="закрой процесс",
        slots=(
            _enum_slot(
                "process",
                "Какой процесс завершить?",
                SOURCE_PROCESSES,
                description="имя запущенного процесса",
                triggers=(
                    "закрой процесс",
                    "убей процесс",
                    "заверши процесс",
                    "останови процесс",
                    "закрой",
                    "убей",
                    "заверши",
                ),
            ),
        ),
        confirm=CONFIRM_HANDLER,
        clarify_question="Какой процесс завершить?",
    ),
    # ── Файлы на рабочем столе ──────────────────────────────────────
    Intent(
        id="file_create_folder",
        domain="files",
        title="Создать папку на рабочем столе",
        examples=("создай папку проекты", "сделай папку отчёты"),
        canonical="создай папку {payload}",
        handler="FileHandler",
        handler_file="zere/core/handlers/file_handler.py",
        local_trigger="создай папку",
        slots=(
            _text_slot(
                "payload",
                "Как назвать папку?",
                ("создай папку", "создай директорию", "новая папка", "сделай папку"),
            ),
        ),
        clarify_question="Как назвать папку?",
    ),
    Intent(
        id="file_create",
        domain="files",
        title="Создать файл на рабочем столе",
        examples=("создай файл заметки.txt", "сделай документ отчёт"),
        canonical="создай файл {payload}",
        handler="FileHandler",
        handler_file="zere/core/handlers/file_handler.py",
        local_trigger="создай файл",
        slots=(
            _text_slot(
                "payload",
                "Как назвать файл?",
                ("создай файл", "новый файл", "создай документ", "сделай файл"),
            ),
        ),
        clarify_question="Как назвать файл?",
    ),
    Intent(
        id="file_find",
        domain="files",
        title="Найти файл на рабочем столе",
        examples=("найди файл отчёт", "где файл заметки"),
        canonical="найди файл {payload}",
        handler="FileHandler",
        handler_file="zere/core/handlers/file_handler.py",
        local_trigger="найди файл",
        slots=(
            _text_slot(
                "payload",
                "Какой файл найти?",
                ("найди файл", "найти файл", "поищи файл", "где файл"),
            ),
        ),
        clarify_question="Какой файл найти?",
    ),
    Intent(
        id="file_delete",
        domain="files",
        title="Удалить файл с рабочего стола",
        examples=("удали файл заметки.txt", "убери файл отчёт"),
        canonical="удали файл {payload}",
        handler="FileHandler",
        handler_file="zere/core/handlers/file_handler.py",
        local_trigger="удали файл",
        slots=(
            _text_slot(
                "payload",
                "Какой файл удалить?",
                ("удали файл", "убери файл", "удалить файл", "сотри файл"),
            ),
        ),
        confirm=CONFIRM_HANDLER,
        clarify_question="Какой файл удалить?",
    ),
    # ── Громкость ───────────────────────────────────────────────────
    Intent(
        id="volume_set",
        domain="volume",
        title="Установить уровень громкости",
        examples=("громкость 50", "поставь громкость на 30", "сделай звук на 80"),
        canonical="громкость {level}",
        handler="VolumeHandler",
        handler_file="zere/core/handlers/volume_handler.py",
        local_trigger="громкость",
        slots=(
            Slot(
                name="level",
                kind=KIND_SCORE,
                question="Какой уровень громкости просит пользователь (0–100)?",
                description="уровень громкости в процентах",
            ),
        ),
        clarify_question="Какой уровень громкости поставить (0–100)?",
    ),
    Intent(
        id="volume_up",
        domain="volume",
        title="Сделать громче",
        examples=("сделай громче", "погромче", "прибавь звук"),
        canonical="сделай громче",
        handler="VolumeHandler",
        handler_file="zere/core/handlers/volume_handler.py",
        local_trigger="сделай громче",
    ),
    Intent(
        id="volume_down",
        domain="volume",
        title="Сделать тише",
        examples=("сделай тише", "потише", "убавь звук"),
        canonical="сделай тише",
        handler="VolumeHandler",
        handler_file="zere/core/handlers/volume_handler.py",
        local_trigger="сделай тише",
    ),
    Intent(
        id="volume_mute",
        domain="volume",
        title="Выключить звук (mute)",
        examples=("выключи звук", "замолчи звук", "mute"),
        canonical="выключи звук",
        handler="VolumeHandler",
        handler_file="zere/core/handlers/volume_handler.py",
        local_trigger="выключи звук",
    ),
    Intent(
        id="volume_unmute",
        domain="volume",
        title="Вернуть звук",
        examples=("включи звук", "верни звук", "unmute"),
        canonical="включи звук",
        handler="VolumeHandler",
        handler_file="zere/core/handlers/volume_handler.py",
        local_trigger="включи звук",
    ),
    # ── Игры ────────────────────────────────────────────────────────
    Intent(
        id="games_running",
        domain="games",
        title="Какие игры запущены сейчас",
        examples=("игры", "во что я играю"),
        canonical="игры",
        handler="GameHandler",
        handler_file="zere/core/handlers/game_handler.py",
        local_trigger="игры",
    ),
    Intent(
        id="games_stats",
        domain="games",
        title="Игровая статистика за сегодня",
        examples=("игровая статистика", "сколько я играл сегодня"),
        canonical="игровая статистика",
        handler="GameHandler",
        handler_file="zere/core/handlers/game_handler.py",
        local_trigger="игровая статистика",
    ),
    Intent(
        id="games_reset",
        domain="games",
        title="Сбросить игровую статистику",
        examples=("сбросить игровую статистику", "обнули статистику игр"),
        canonical="сбросить игровую статистику",
        handler="GameHandler",
        handler_file="zere/core/handlers/game_handler.py",
        local_trigger="сбросить игровую статистику",
        confirm=CONFIRM_ROUTER,
    ),
    # ── Питание ─────────────────────────────────────────────────────
    Intent(
        id="power_shutdown",
        domain="power",
        title="Выключить компьютер",
        examples=("выключи компьютер", "выруби комп", "shutdown"),
        canonical="выключи компьютер",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="выключи компьютер",
        confirm=CONFIRM_HANDLER,
    ),
    Intent(
        id="power_restart",
        domain="power",
        title="Перезагрузить компьютер",
        examples=("перезагрузи компьютер", "ребутни комп", "restart"),
        canonical="перезагрузи компьютер",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="перезагрузи компьютер",
        confirm=CONFIRM_HANDLER,
    ),
    Intent(
        id="power_sleep",
        domain="power",
        title="Перевести компьютер в сон",
        examples=("режим сна", "усыпи компьютер"),
        canonical="режим сна",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="режим сна",
        confirm=CONFIRM_HANDLER,
    ),
    # ── Подтверждение ожидающего действия ───────────────────────────
    Intent(
        id="confirm_yes",
        domain="confirm",
        title="Подтвердить ожидающее необратимое действие",
        examples=("да", "подтверди", "выполняй"),
        canonical="да",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="подтверди",
    ),
    Intent(
        id="confirm_no",
        domain="confirm",
        title="Отменить ожидающее действие",
        examples=("нет", "отмена", "не надо"),
        canonical="нет",
        handler="WindowsHandler",
        handler_file="zere/core/handlers/windows_handler.py",
        local_trigger="отменена",
    ),
    # ── Рисование (только Python-редакция) ──────────────────────────
    Intent(
        id="draw_shape",
        domain="drawing",
        title="Нарисовать фигуру в Krita или Paint",
        examples=("нарисуй круг", "нарисуй звезду в крите", "поставь треугольник"),
        canonical="нарисуй {shape}",
        handler="DrawingHandler",
        # Разбирает команду рисования не обработчик-делегат, а роутер:
        # в нём и живут фигуры, якоря текста и смена цели.
        handler_file="zere/tools/drawing/drawing_command_router.py",
        local_trigger="нарисуй",
        slots=(
            _enum_slot(
                "shape",
                "Какую фигуру нарисовать?",
                SOURCE_STATIC,
                options=SHAPES,
                description="геометрическая фигура",
            ),
        ),
        clarify_question="Какую фигуру нарисовать?",
        python_only=True,
    ),
    Intent(
        id="draw_text",
        domain="drawing",
        title="Написать текст на холсте",
        examples=("напиши на холсте привет", "нарисуй текст ZERE"),
        canonical="нарисуй текст {payload}",
        handler="DrawingHandler",
        # Разбирает команду рисования не обработчик-делегат, а роутер:
        # в нём и живут фигуры, якоря текста и смена цели.
        handler_file="zere/tools/drawing/drawing_command_router.py",
        local_trigger="текст",
        slots=(
            _text_slot(
                "payload",
                "Какой текст написать на холсте?",
                ("напиши на холсте", "нарисуй текст", "напиши текст", "напиши"),
            ),
        ),
        clarify_question="Какой текст написать на холсте?",
        python_only=True,
    ),
    Intent(
        id="draw_target",
        domain="drawing",
        title="Сменить цель рисования (Krita или Paint)",
        examples=("рисуй в крите", "переключись на пейнт"),
        canonical="рисуй в {target}",
        handler="DrawingHandler",
        # Разбирает команду рисования не обработчик-делегат, а роутер:
        # в нём и живут фигуры, якоря текста и смена цели.
        handler_file="zere/tools/drawing/drawing_command_router.py",
        local_trigger="рисуй в",
        slots=(
            _enum_slot(
                "target",
                "В какой программе рисовать?",
                SOURCE_STATIC,
                options=DRAW_TARGETS,
                description="Krita — «крите», Paint — «пейнте»",
            ),
        ),
        clarify_question="В чём рисовать: в Krita или Paint?",
        python_only=True,
    ),
    Intent(
        id="draw_clear",
        domain="drawing",
        title="Очистить холст",
        examples=("очисти холст", "сотри рисунок"),
        canonical="очисти холст",
        handler="DrawingHandler",
        # Разбирает команду рисования не обработчик-делегат, а роутер:
        # в нём и живут фигуры, якоря текста и смена цели.
        handler_file="zere/tools/drawing/drawing_command_router.py",
        local_trigger="очист",
        confirm=CONFIRM_ROUTER,
        python_only=True,
    ),
    # ── Не команда ──────────────────────────────────────────────────
    Intent(
        id="chat",
        domain="chat",
        title="Вопрос, просьба или обычный разговор — команды нет",
        examples=(
            "привет, как дела?",
            "что такое гравитация",
            "объясни, почему небо синее",
            "а как закрыть процесс, если я не у компа",
        ),
        canonical="",
        handler="AIHandler",
        handler_file="zere/core/handlers/ai_handler.py",
        local_trigger="can_handle",
    ),
)

#: Описания доменов — criteria первого шага стратегии `domain`.
DOMAINS: dict[str, str] = {
    "memory": "память о пользователе: запомнить факт, забыть, показать память",
    "history": "история диалогов: показать или очистить",
    "apps": "приложения: открыть, найти, обновить индекс, посчитать",
    "processes": "процессы системы: список, поиск, завершение",
    "files": "файлы и папки на рабочем столе: создать, найти, удалить",
    "volume": "громкость и звук",
    "games": "игры: какие запущены, статистика, сброс статистики",
    "power": "питание компьютера: выключение, перезагрузка, сон",
    "confirm": "подтверждение «да» или отмена «нет» ожидающего действия",
    "drawing": "рисование в Krita или Paint: фигуры, текст, очистка холста",
    "chat": "вопрос или просьба к ИИ — команды нет",
}

#: Интенты, которые роутер может предложить Jev (все).
INTENTS_BY_ID: dict[str, Intent] = {intent.id: intent for intent in INTENTS}

#: Интенты домена — criteria второго шага стратегии `domain`.
INTENTS_BY_DOMAIN: dict[str, tuple[Intent, ...]] = {
    domain: tuple(intent for intent in INTENTS if intent.domain == domain)
    for domain in DOMAINS
}

#: Псевдоинтент «не команда»: уходит в LLM, а не в пайплайн.
CHAT_INTENT_ID = "chat"


def get_intent(intent_id: str) -> Optional[Intent]:
    """Интент по id (None — неизвестный id от модели: считаем болтовнёй)."""
    return INTENTS_BY_ID.get(intent_id)


def dispatchable(include_python_only: bool = True) -> tuple[Intent, ...]:
    """Интенты для выполнения: без «chat» (это путь в LLM)."""
    return tuple(
        intent
        for intent in INTENTS
        if intent.id != CHAT_INTENT_ID and (include_python_only or not intent.python_only)
    )


def build_command(intent: Intent, slots: dict[str, object]) -> str:
    """Каноническая фраза для пайплайна: подстановка слотов в шаблон."""
    if not intent.canonical:
        return ""
    return intent.canonical.format(**slots).strip()


# ── Локальное извлечение свободного текста ──────────────────────────
_QUOTE_PAIRS = (("«", "»"), ('"', '"'), ("“", "”"), ("'", "'"), ("„", "“"))

#: Слова, которые не могут быть самостоятельным аргументом.
_STOP_PAYLOADS = {
    "пожалуйста",
    "да",
    "нет",
    "это",
    "то",
    "мне",
    "его",
    "её",
    "их",
    "файл",
    "папку",
    "папка",
    "текст",
    "память",
    "холст",
}


def _strip_quoted(text: str) -> str:
    """Текст в кавычках — самый надёжный признак аргумента."""
    for opener, closer in _QUOTE_PAIRS:
        start = text.find(opener)
        if start < 0:
            continue
        end = text.find(closer, start + 1)
        if end > start + 1:
            return text[start + 1 : end].strip()
    return ""


def _cut_phrase(text: str, phrase: str) -> str:
    """Убирает первое вхождение фразы (без учёта регистра) из текста."""
    low = text.lower()
    idx = low.find(phrase.lower())
    if idx < 0:
        return text
    return (text[:idx] + " " + text[idx + len(phrase) :]).strip()


def _cleanup(text: str) -> str:
    """Убирает слова-заполнители, лишние кавычки и пробелы."""
    result = text.strip()
    for filler in sorted(FILLER_WORDS, key=len, reverse=True):
        low = result.lower()
        if low == filler:
            return ""
        if low.startswith(filler + " "):
            result = result[len(filler) :].strip()
        else:
            result = _cut_phrase(result, " " + filler + " ")
    result = result.strip(" .,!?;:—-–\"'«»")
    return " ".join(result.split())


def extract_payload(message: str, triggers: tuple[str, ...]) -> str:
    """Свободный аргумент из фразы: кавычки → снятие триггера → чистка.

    Возвращает "" — если аргумент не извлекается надёжно. Пустая строка
    означает «переспросить», а не «взять что попало»: выдуманный аргумент
    (не тот процесс, не тот файл) хуже уточняющего вопроса.
    """
    text = (message or "").strip()
    if not text:
        return ""

    quoted = _strip_quoted(text)
    if quoted:
        return quoted

    result = text
    for trigger in sorted(triggers, key=len, reverse=True):
        if trigger.lower() in result.lower():
            result = _cut_phrase(result, trigger)
            break

    result = _cleanup(result)

    # Аргумент не может быть пустым, состоять из служебного слова или
    # быть слишком длинным (тогда это, скорее всего, не аргумент, а фраза).
    if not result or result.lower() in _STOP_PAYLOADS or len(result) > 120:
        return ""

    return result
