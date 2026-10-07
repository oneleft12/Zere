/**
 * Словарь EN для экрана «Подключение ИИ» и блока статуса ИИ
 * (дашборд, чат, статус-строка).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 */

export const AI_EN: Record<string, string> = {
  // ── Навигация и статус-строка ──────────────────────────────────
  "Подключение ИИ": "AI connection",
  "ИИ": "AI",
  "ИИ: облако": "AI: cloud",
  "ИИ: локально": "AI: local",
  "ИИ: не настроен": "AI: not configured",
  "ИИ и модель": "AI and model",
  "ИИ не настроен": "AI is not configured",
  "Настроить ИИ": "Configure AI",
  "Проверить ИИ": "Check AI",
  "Чтобы начать, введите API-ключ или установите локальную модель":
    "To get started, enter an API key or install a local model",
  "Облачная модель": "Cloud model",
  "Локальная модель": "Local model",
  "Провайдер не выбран": "No provider selected",
  "Введите API-ключ или установите локальную модель": "Enter an API key or install a local model",

  // ── Экран подключения ИИ ──────────────────────────────────────
  "Проверка подключения ИИ…": "Checking AI connection…",
  "Не удалось получить состояние ИИ": "Failed to load AI status",
  "Не удалось загрузить состояние ИИ": "Failed to load AI status",
  "Свой API-ключ или локальная модель — что использовать для ответов":
    "Your own API key or a local model — what should answer",
  "Обновить состояние": "Refresh status",
  "Состояние подключения": "Connection status",
  "Как использовать ИИ": "How to use AI",
  "Режим": "Mode",
  "Отвечает": "Answering",
  "Файл настроек": "Settings file",
  "авто": "auto",
  "только облачный ключ": "cloud key only",
  "только локальная модель": "local model only",
  "облачная модель": "cloud model",
  "локальная модель": "local model",
  "никто — ИИ не настроен": "nobody — AI is not configured",
  "Авто — сначала API-ключ, иначе локальная модель":
    "Auto — API key first, local model otherwise",
  "Использовать свой API-ключ": "Use my API key",
  "Использовать локальную модель": "Use a local model",
  "Режим ИИ сохранён": "AI mode saved",
  "«Авто» удобен по умолчанию: ключ есть — идём в облако, нет — считаем локально.":
    "“Auto” is the sensible default: with a key requests go to the cloud, without one they run locally.",

  // ── Облачный ключ ─────────────────────────────────────────────
  "Свой API-ключ (облачная модель)": "My API key (cloud model)",
  "Провайдер": "Provider",
  "Провайдер сохранён": "Provider saved",
  "Модель": "Model",
  "API-ключ": "API key",
  "Ключ хранится только на бэкенде и никогда не выводится целиком":
    "The key is stored on the backend only and is never shown in full",
  "Ключ можно получить здесь: ": "Get a key here: ",
  "Проверить ключ": "Test key",
  "Сохранить": "Save",
  "Удалить ключ": "Delete key",
  "Ключ": "Key",
  "Маска": "Mask",
  "Источник": "Source",
  "Проверен": "Checked",
  "ключ не найден": "key not found",
  "ключ сохранён и работает": "key saved and working",
  "ключ не работает": "key does not work",
  "ключ сохранён, не проверен": "key saved, not tested",
  "свой ключ (config/ai.json)": "own key (config/ai.json)",
  "ключ владельца (окружение сервера)": "owner key (server environment)",
  "нет": "none",
  "Используется ключ владельца из переменных окружения сервера — его нельзя удалить из панели.":
    "The owner key from the server environment is used — it cannot be deleted from the panel.",
  "Проверка ключа — рабочий запрос: список моделей, при необходимости минимальный запрос к чату.":
    "Testing a key performs a real request: the model list, and a minimal chat request if needed.",
  "Ключ рабочий": "The key works",
  "Ключ не прошёл проверку": "The key failed the check",
  "Введите API-ключ.": "Enter an API key.",
  "API-ключ сохранён": "API key saved",
  "Ключ не сохранён": "The key was not saved",
  "API-ключ удалён": "API key deleted",
  "Не удалось удалить ключ": "Failed to delete the key",
  "Сервер отклонил настройки ИИ": "The server rejected the AI settings",

  // ── Локальная модель ──────────────────────────────────────────
  "Локальная модель (Ollama или свой сервер)": "Local model (Ollama or your own server)",
  "Адрес локального сервера": "Local server address",
  "Ollama по умолчанию: http://127.0.0.1:11434/v1":
    "Ollama default: http://127.0.0.1:11434/v1",
  "Лёгкая модель для слабого ПК": "Light model for a weak PC",
  "оставить текущую: {model}": "keep current: {model}",
  "Локальная модель сохранена": "Local model saved",
  "По умолчанию предлагаются модели 0.5B–3B: тяжёлые не нужны слабому ПК":
    "Suggested models are 0.5B–3B: a weak PC does not need heavy ones",
  "Проверить локальную модель": "Test local model",
  "Сохранить адрес и модель": "Save address and model",
  "Настройки локальной модели сохранены": "Local model settings saved",
  "Скачать модель": "Download model",
  "Сервер": "Server",
  "запущен": "running",
  "не запущен": "not running",
  "Нужная модель": "Required model",
  "загружена": "downloaded",
  "не загружена": "not downloaded",
  "Найдено моделей": "Models found",
  "Локальная модель не отвечает": "The local model did not respond",
  "Готовлю загрузку…": "Preparing download…",
  "Загрузка не удалась": "Download failed",
  "Локальная модель не найдена": "Local model not found",
  "Скопировать команду": "Copy command",
  "Скачать Ollama": "Download Ollama",
  "Команда скопирована": "Command copied",
  "Скопируйте команду вручную": "Copy the command manually",
  "Кнопка «Скачать модель» работает, если Ollama уже запущена — прогресс появится выше.":
    "The “Download model” button works when Ollama is already running — progress appears above.",
  "Для слабых ПК: 0.5B–1.5B, для средних: 3B–4B":
    "For weak PCs: 0.5B–1.5B, for mid-range: 3B–4B",

  // ── Редакция без настройки ключа / устаревший сервер ──────────
  "ИИ: только локально": "AI: local only",
  "ИИ: перезапустите ZERE": "AI: restart ZERE",
  "Перезапустите ZERE: настройка ИИ включится после обновления сервера":
    "Restart ZERE: AI settings will appear after the server update",
  "Нужен перезапуск ZERE": "ZERE needs a restart",
  "Панель обновилась, а сервер ZERE работает со старым кодом: закройте и снова запустите ZERE — настройка ИИ появится.":
    "The panel was updated but the ZERE server still runs the old code: close and start ZERE again to get AI settings.",
  "В этой редакции настраивается только локальная модель":
    "This edition can only use a local model",
  "Эта сборка панели новее сервера ZERE: перезапустите ZERE, чтобы включить настройку ключа. Локальная модель (Ollama) продолжает работать — её состояние видно на дашборде.":
    "This panel build is newer than the ZERE server: restart ZERE to enable key setup. The local model (Ollama) keeps working — its status is shown on the dashboard.",
  "На дашборд": "Go to dashboard",
  "Сервер ZERE старее панели: закройте и снова запустите ZERE — появится настройка облачного ключа.":
    "The ZERE server is older than the panel: close and start ZERE again to get cloud key settings.",
  "Настройка облачного ключа появится после перезапуска ZERE; пока работает локальная модель (Ollama).":
    "Cloud key setup appears after ZERE is restarted; for now the local model (Ollama) is used.",
  "Подключено: локальная модель · {model}": "Connected: local model · {model}",
  "Локальная модель недоступна": "Local model unavailable",
  "Настройка ключа — после перезапуска ZERE": "Key setup appears after ZERE restarts",
};
