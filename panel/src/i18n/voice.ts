/**
 * Словарь EN для экрана «voice» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const VOICE_EN: Record<string, string> = {
  // ── Шапка и загрузка ──────────────────────────────────────────
  "Голос": "Voice",
  "Настройки voiceVolume/ttsEngine/… через POST /api/voice; тесты ходят в живой VoiceManager":
    "Settings voiceVolume/ttsEngine/… via POST /api/voice; tests hit the live VoiceManager",
  "Загрузка голосовых настроек…": "Loading voice settings…",
  "Не удалось загрузить голосовые настройки": "Failed to load voice settings",
  "Неизвестная ошибка": "Unknown error",
  "Повторить": "Retry",

  // ── Кнопки и сохранение ───────────────────────────────────────
  "Сохранить": "Save",
  "Отменить изменения": "Revert changes",
  "Сохранено — вступит в силу после перезапуска": "Saved — takes effect after restart",
  "Громкость применена сразу": "Volume applied immediately",
  "Применено сразу, без перезапуска": "Applied immediately, without a restart",
  "Сервер отклонил настройки: {message}": "The server rejected the settings: {message}",
  "Ошибка сохранения голосовых настроек": "Failed to save voice settings",

  // ── Карточка настроек ─────────────────────────────────────────
  "Голосовой вывод": "Voice output",
  "Голосовой вывод включён": "Voice output enabled",
  "Громкость": "Volume",
  "Применяется сразу, без перезапуска": "Applied immediately, without a restart",
  "TTS-движок": "TTS engine",
  "pocket — клонирование голоса": "pocket — voice cloning",
  "chattts — реалистичный голос, без клонирования": "chattts — realistic voice, no cloning",
  "silero — русский голос: ударения, цифры и английские слова": "silero — Russian voice: stress marks, numbers and English words",
  "Смена движка вступает в силу после перезапуска": "Engine change takes effect after restart",
  "DSP-обработка озвучки (ChatTTS)": "Speech DSP (ChatTTS)",
  "EQ + мягкая компрессия + нормализация": "EQ + gentle compression + normalization",
  "Применяется сразу; выключено — «сырой» выход TTS без фильтров":
    "Applied immediately; off — raw TTS output without filters",
  "Референс голоса (WAV)": "Voice reference (WAV)",
  "путь к WAV-референсу, пусто = встроенный голос":
    "path to the WAV reference, empty = built-in voice",

  // ── Возможности реализации ────────────────────────────────────
  "Возможности реализации": "Implementation capabilities",
  "запись референса: {value}": "reference recording: {value}",
  "PocketTTS: {value}": "PocketTTS: {value}",
  "скорость речи: {value}": "speech speed: {value}",
  "громкость сразу: {value}": "instant volume: {value}",
  "DSP-обработка: {value}": "DSP processing: {value}",
  "включена": "on",
  "выключена": "off",
  "Обработка": "Processing",
  "DSP включена": "DSP on",
  "DSP выключена": "DSP off",
  "микрофон (STT): {value}": "microphone (STT): {value}",
  "есть": "yes",
  "нет": "no",
  "да": "yes",
  "задаётся": "configurable",
  "фиксирована": "fixed",
  "доступен": "available",
  "Значения честные для текущей реализации: C# умеет больше, Python-порт отдаёт false там, где функции ещё нет — панель это показывает, а не скрывает.":
    "The values are honest for the current implementation: C# can do more, "
      + "the Python port returns false where a feature does not exist yet — "
      + "the panel shows that instead of hiding it.",
  "Референс": "Reference",
  "Движок": "Engine",

  // ── Тестирование ──────────────────────────────────────────────
  "Тестирование": "Testing",
  "Фраза для озвучки": "Phrase to speak",
  "Фраза для озвучки (до 500 символов)": "Phrase to speak (up to 500 characters)",
  "Синтез через активный движок; при 503 в ответе указана причина":
    "Synthesis via the active engine; on 503 the response contains the reason",
  "Проверка голоса. Привет!": "Voice test. Hello!",
  "Озвучить": "Speak",
  "Записать референс (15 с)": "Record reference (15 s)",
  "Эта реализация не записывает референс (capabilities.recordReference=false)":
    "This implementation cannot record a reference (capabilities.recordReference=false)",
  "Тест микрофона": "Microphone test",
  "STT сейчас недоступен (capabilities.sttTest=false)":
    "STT is currently unavailable (capabilities.sttTest=false)",
  "Введите фразу для озвучки.": "Enter a phrase to speak.",
  "Фраза длиннее {max} символов.": "The phrase is longer than {max} characters.",
  "Фраза озвучена": "Phrase spoken",
  "Тест озвучки не удался": "Speech test failed",

  // ── Запись референса ──────────────────────────────────────────
  "Записать референс голоса?": "Record a voice reference?",
  "Микрофон запишет 15 секунд вашей речи для клонирования голоса. Говорите чётко и без шума.":
    "The microphone will record 15 seconds of your speech for voice cloning. Speak clearly and avoid noise.",
  "Начать запись": "Start recording",
  "Запись референса отменена": "Reference recording cancelled",
  "Референс записан и сохранён в конфигурации":
    "Reference recorded and saved to the configuration",
  "Запись референса не удалась": "Reference recording failed",

  // ── Распознавание ─────────────────────────────────────────────
  "Распознано: «{text}»": "Recognized: “{text}”",
  "Микрофон ничего не распознал.": "The microphone did not recognize anything.",
  "Распознавание выполнено": "Recognition complete",
  "Тест микрофона не удался": "Microphone test failed",

  // ── Режим голоса (непрерывный слушатель) ──────────────────────
  "Режим голоса": "Voice mode",
  "Слушать постоянно": "Listen continuously",
  "Состояние режима": "Mode state",
  "нет данных": "no data",
  "выключен": "off",
  "ждёт «{word}»": "waiting for “{word}”",
  "слушает без триггера": "listening without a trigger",
  "слушает команду": "listening for a command",
  "формулирует ответ": "generating an answer",
  "озвучивает ответ": "speaking the answer",
  "ошибка": "error",
  "Состояние режима недоступно: сервер не отдаёт /api/voice/mode.":
    "Mode state unavailable: the server does not expose /api/voice/mode.",
  "Распознавание речи недоступно — режим голоса включить нельзя":
    "Speech recognition is unavailable — voice mode cannot be enabled",
  "STT недоступен: режим голоса включить нельзя, доступны только тесты.":
    "STT is unavailable: voice mode cannot be enabled, only tests are available.",
  "Скажите «{word}», затем команду; «выход» — выключить режим.":
    "Say “{word}” and then a command; say “выход” to turn the mode off.",
  "Слово-триггер выключено — говорите команду сразу; «выход» — выключить режим.":
    "The wake word is off — speak commands right away; say “выход” to turn the mode off.",
  "Последняя команда": "Last command",
  "Последний ответ": "Last answer",
  "Ошибка режима": "Mode error",
  "Голосовой режим включён": "Voice mode enabled",
  "Голосовой режим выключен": "Voice mode disabled",
  "Не удалось переключить режим: {message}": "Failed to toggle the mode: {message}",
  "Ошибка переключения голосового режима": "Failed to toggle voice mode",
};
