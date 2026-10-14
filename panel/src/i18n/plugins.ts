/**
 * Словарь EN для экрана «plugins» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const PLUGINS_EN: Record<string, string> = {
  // ── Заголовок и загрузка ──────────────────────────────────────
  "Плагины": "Plugins",
  "Список плагинов; у MCP-плагинов настраивается браузер":
    "Plugin list; MCP plugins let you choose the browser",
  "Обновить": "Refresh",
  "Загрузка плагинов…": "Loading plugins…",
  "Неизвестная ошибка": "Unknown error",
  "Не удалось загрузить плагины": "Failed to load plugins",
  "Повторить": "Retry",
  "Ошибка загрузки плагинов": "Error loading plugins",

  // ── Карточка «Состояние» ──────────────────────────────────────
  "Состояние": "Status",
  "обработчики подключены: да": "handlers connected: yes",
  "обработчики подключены: нет": "handlers connected: no",
  "командных обработчиков: {count}": "command handlers: {count}",
  "личность: {value}": "personality: {value}",
  "handlersConnected=false — плагины-обработчики этой сборки не подключены к конвейеру: они видны в списке, но команд не получают.":
    "handlersConnected=false — this build's plugin handlers are not wired into the pipeline: they appear in the list but receive no commands.",
  "Плагины-обработчики подключены к конвейеру: их команды работают. Внешние плагины кладутся в ./plugins/*.py и загружаются при старте.":
    "Plugin handlers are wired into the pipeline: their commands work. External plugins go into ./plugins/*.py and are loaded at startup.",

  // ── Список плагинов ───────────────────────────────────────────
  "Плагины не найдены": "No plugins found",
  "PluginManager не загрузил ни встроенного, ни внешнего плагина.":
    "PluginManager loaded neither built-in nor external plugins.",
  "Версия": "Version",
  "Автор": "Author",
  // ── MCP: выбор браузера и состояние серверов ──────────────────
  "Браузер для плагина MCP": "Browser for the MCP plugin",
  "Браузер": "Browser",
  "Выбор сохраняется и переживает перезапуск ZERE.":
    "The choice is saved and survives a ZERE restart.",
  "Выбрать браузер": "Choose browser",
  "Сейчас": "Current",
  "Запуск": "Launch",
  "канал Playwright: {channel}": "Playwright channel: {channel}",
  "по пути к opera.exe": "by the opera.exe path",
  "{label} — не найден": "{label} — not found",
  "То же делает команда «браузер выбери opera gx» в чате.":
    "The chat command “браузер выбери opera gx” does the same.",
  "MCP-серверы": "MCP servers",
  "не настроен в config/mcp.json": "not configured in config/mcp.json",
  "сервер запущен": "server is running",
  "включён, сервер поднимется при первой команде":
    "enabled, the server starts on the first command",
  "выключен в config/mcp.json": "disabled in config/mcp.json",
  "Последняя ошибка": "Last error",
};
