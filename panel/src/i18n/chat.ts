/**
 * Словарь EN для экрана «chat» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const CHAT_EN: Record<string, string> = {
  // ── Шапка и подсказки ─────────────────────────────────────────
  "Чат": "Chat",
  "Ответ приходит потоком (SSE) и сразу сохраняется в истории диалогов":
    "The reply streams in (SSE) and is saved to the conversation history right away",
  "SSE-стрим": "SSE stream",
  "Диалог с ассистентом": "Conversation with the assistant",
  "Enter — отправить": "Enter to send",
  "ZERE отвечает…": "ZERE is replying…",

  // ── Композер ──────────────────────────────────────────────────
  "Отправить": "Send",
  "Спросите ZERE…": "Ask ZERE…",

  // ── Голосовое в чате (POST /api/voice/listen) ─────────────────
  "Записать голосовое": "Record a voice message",
  "Идёт запись голосового…": "Recording a voice message…",
  "Распознавание речи недоступно": "Speech recognition is unavailable",
  "STT недоступен (capabilities.sttTest=false) — кнопка выключена":
    "STT is unavailable (capabilities.sttTest=false) — the button is disabled",
  "Проверяю микрофон…": "Checking the microphone…",
  "Запись ≈5 с с микрофона машины ZERE, затем распознавание; Shift+клик — отправить сразу":
    "Records ≈5 s from the ZERE machine's microphone, then transcribes; Shift+click sends right away",
  "Слушаю микрофон…": "Listening to the microphone…",
  "ZERE слушает": "ZERE is listening",
  "Микрофон ничего не распознал": "The microphone picked up nothing",
  "Не удалось записать голосовое: {message}": "Failed to record the voice message: {message}",

  // ── Режим голоса в шапке чата (GET/POST /api/voice/mode) ──────
  // Фазы цикла берутся из i18n/voice.ts: формулировки те же, что на «Голосе».
  "Режим голоса": "Voice mode",
  "Режим голоса: {state}": "Voice mode: {state}",
  "Включить режим голоса: слово-триггер → команда → ответ голосом":
    "Turn voice mode on: wake word → command → spoken answer",
  "Выключить режим голоса": "Turn voice mode off",
  "Переключаю режим голоса…": "Switching voice mode…",
  "Состояние режима недоступно: сервер не отдаёт /api/voice/mode":
    "Mode state is unavailable: the server does not expose /api/voice/mode",
  // ── Голосовая реплика в диалоге (поле turn) ───────────────────
  "Реплика из голосового режима": "Line from voice mode",

  // ── Пустой лог ────────────────────────────────────────────────
  "Начните диалог": "Start a conversation",
  "Спросите ZERE о процессах, файлах или погоде — ответ придёт потоком и попадёт в историю.":
    "Ask ZERE about processes, files or the weather — the reply arrives as a stream and goes into the history.",

  // ── Отправка и ошибки ─────────────────────────────────────────
  "Думаю…": "Thinking…",
  "Не удалось получить ответ": "Failed to get a reply",
  "Неизвестная ошибка": "Unknown error",

  // ── Справочник команд (commands.ts) ───────────────────────────
  "Команды ZERE": "ZERE commands",
  "Нажмите команду — она подставится в поле ввода":
    "Click a command to insert it into the input field",
  "Поиск команды…": "Search commands…",
  "Вставить в поле ввода": "Insert into the input field",
  "Ничего не найдено — попробуйте другой запрос":
    "Nothing found — try another query",

  // Группы
  "История диалогов": "Conversation history",
  "Файлы на рабочем столе": "Files on the desktop",
  "Папки в системе": "Folders on the system",
  "Игры": "Games",
  "Питание": "Power",
  "Рисование: Krita и Paint": "Drawing: Krita and Paint",
  "только Python-редакция": "Python edition only",
  "Вопросы к ИИ": "Questions to the AI",
  "Консольные команды": "Console commands",
  "только в окне консоли ZERE, не в чате":
    "only in the ZERE console window, not in chat",

  // Память
  "Сохранить факт: ключ — первое слово, значение — остальные":
    "Save a fact: the first word is the key, the rest is the value",
  "Найти папку по имени (профиль и диски)":
    "Find a folder by name (profile and drives)",
  "Найти приложение, а если его нет — папку":
    "Find an application, or a folder if there is none",
  "Открыть папку в проводнике": "Open the folder in Explorer",
  "Открыть папку по номеру из прошлой выдачи":
    "Open a folder by its number from the previous results",
  "Открыть последнюю найденную папку": "Open the last found folder",
  "Сохранить факт явной парой «ключ = значение»":
    "Save a fact as an explicit “key = value” pair",
  "Показать все воспоминания": "Show every memory",
  "Спросить из памяти: имя, проект, видеокарта, windows":
    "Ask memory for: name, project, GPU, windows",
  "Вся память о пользователе": "Everything remembered about you",
  "Поиск по памяти; если не найдено — отвечает ИИ":
    "Search memory; if nothing is found, the AI answers",
  "Изменить значение существующего ключа": "Change the value of an existing key",
  "Удалить одну запись из памяти": "Delete a single memory entry",
  "Полностью очистить память": "Erase all memory",

  // История
  "Последние 20 пар «вы → ZERE»": "The last 20 “you → ZERE” pairs",
  "То же самое другими словами": "The same thing in other words",
  "Очистить историю разговоров": "Clear the conversation history",

  // Приложения
  "Запуск приложения по имени или алиасу":
    "Launch an application by name or alias",
  "Поиск приложения в индексе": "Search the application index",
  "Переиндексировать установленные приложения":
    "Re-index the installed applications",
  "Сколько приложений в индексе": "How many applications are indexed",

  // Процессы
  "15 самых «тяжёлых» процессов (ещё: «что запущено», «задачи»)":
    "The 15 heaviest processes (also: “что запущено”, “задачи”)",
  "Найти процесс по имени": "Find a process by name",
  "Завершить процесс: системные защищены, нужно подтверждение":
    "Kill a process: system ones are protected, confirmation required",
  "Подтвердить необратимое действие (действует 60 секунд)":
    "Confirm an irreversible action (valid for 60 seconds)",
  "Отменить ожидающее действие": "Cancel the pending action",

  // Файлы
  "Создать папку": "Create a folder",
  "Создать файл": "Create a file",
  "Найти файл по имени": "Find a file by name",
  "Удалить файл — только после подтверждения":
    "Delete a file — only after confirmation",
  "Удалить последний созданный файл": "Delete the last created file",

  // Громкость
  "Установить уровень 0–100": "Set the level 0–100",
  "Громче на шаг (ещё: «погромче»)": "One step louder (also: “погромче”)",
  "Тише на шаг (ещё: «потише»)": "One step quieter (also: “потише”)",
  "Выключить звук (mute)": "Mute the sound",
  "Вернуть звук": "Unmute the sound",

  // Игры
  "Какие игры запущены прямо сейчас": "Which games are running right now",
  "Наигранное время за сегодня": "Time played today",
  "Обнулить счётчик времени за сегодня": "Reset today's play-time counter",

  // Питание
  "Выключение — с подтверждением «да»/«нет»":
    "Shut down — confirmed with “да”/“нет”",
  "Перезагрузка с подтверждением": "Restart — with confirmation",
  "Перевести компьютер в сон": "Put the computer to sleep",

  // Рисование
  "Ещё фигуры: квадрат, прямоугольник, треугольник, овал, звезда, линия":
    "More shapes: square, rectangle, triangle, ellipse, star, line",
  "Текст на холсте (ещё: «напиши на холсте привет»)":
    "Text on the canvas (also: “напиши на холсте привет”)",
  "Назвать цель прямо в команде": "Name the target right in the command",
  "Сменить цель по умолчанию (ещё: «рисуй в пейнте»)":
    "Change the default target (also: “рисуй в пейнте”)",
  "Стереть нарисованное": "Erase what was drawn",

  // Браузер: сайты, YouTube и музыка (один блок)
  "Браузер: сайты, YouTube и музыка": "Browser: sites, YouTube and music",
  "плагин MCP; нужен Python-бэкенд и включение в config/mcp.json; музыка играет в том же браузере":
    "an MCP plugin; needs the Python backend and enabling in config/mcp.json; music plays in the same browser",
  "Перейти по адресу (ещё: «перейди на …», «открой сайт …»)":
    "Navigate to an address (also: “перейди на …”, “открой сайт …”)",
  "Что сейчас на странице (снимок для модели)":
    "What is on the page now (a snapshot for the model)",
  "Найти текст на странице; в ответе ссылки вида e5":
    "Find text on the page; the answer lists refs like e5",
  "Клик по ссылке из снимка (ещё: «нажми на …»)":
    "Click a ref from the snapshot (also: “нажми на …”)",
  "Ввести текст в поле: ссылка, двоеточие, текст":
    "Type into a field: ref, colon, text",
  "Снимок экрана страницы": "Screenshot of the page",
  "Вернуться на предыдущую страницу": "Go back to the previous page",
  "Закрыть браузер": "Close the browser",
  "Какой браузер выбран сейчас": "Which browser is selected now",
  "Какие браузеры доступны на этой машине":
    "Which browsers are available on this machine",
  "Сменить браузер: edge, chrome, opera gx, chromium (выбор сохраняется)":
    "Switch the browser: edge, chrome, opera gx, chromium (the choice is saved)",
  "Все инструменты Playwright MCP (25)": "All Playwright MCP tools (25)",
  "Любой инструмент напрямую: <инструмент> {json}":
    "Any tool directly: <tool> {json}",

  // YouTube и музыка (внутри блока «Браузер»)
  "Открыть YouTube и включить музыку (запрос по умолчанию)":
    "Open YouTube and start music (default query)",
  "Найти первое видео по запросу и включить его с миксом":
    "Find the first video for a query and play it as a mix",
  "Открыть YouTube без воспроизведения": "Open YouTube without playback",
  "Поставить на паузу (ещё: «выключи музыку»)":
    "Pause (also: “выключи музыку”)",
  "Продолжить воспроизведение (ещё: «сними с паузы»)":
    "Resume playback (also: “сними с паузы”)",
  "Следующий трек в миксе (ещё: «следующая песня»)":
    "Next track in the mix (also: “следующая песня”)",
  "Предыдущий трек в миксе": "Previous track in the mix",
  "Название текущего трека и пауза/воспроизведение":
    "The current track title and pause/play state",

  // Заметки Obsidian: MCP
  "Заметки Obsidian: MCP": "Obsidian notes: MCP",
  "плагин MCP; нужен Python-бэкенд и хранилище в config/mcp.json":
    "an MCP plugin; needs the Python backend and a vault in config/mcp.json",
  "Поиск по заметкам (ещё: «найди в заметках …»)":
    "Search the notes (also: “найди в заметках …”)",
  "Список заметок хранилища": "List the vault notes",
  "Список тегов": "List the tags",
  "Прочитать заметку по пути": "Read a note by path",
  "Создать заметку; текст после двоеточия — содержимое":
    "Create a note; the text after the colon is the body",
  "Дописать в конец заметки": "Append to the end of a note",
  "Все инструменты сервера заметок (25)": "All note-server tools (25)",

  // Вопросы к ИИ
  "Всё, что не команда, уходит подключённой модели (облако или Ollama)":
    "Anything that is not a command goes to the connected model (cloud or Ollama)",
  "Обычный вопрос — ответ приходит потоком в чат":
    "An ordinary question — the answer streams into the chat",

  // Консоль
  "Открыть панель настроек в браузере": "Open the settings panel in the browser",
  "Включить голосовой режим (ещё: «voice»)":
    "Turn on voice mode (also: “voice”)",
  "Выйти из ZERE": "Quit ZERE",
};
