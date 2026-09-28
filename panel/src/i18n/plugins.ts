/**
 * Словарь EN для экрана «plugins» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const PLUGINS_EN: Record<string, string> = {
  // ── Заголовок и загрузка ──────────────────────────────────────
  "Плагины": "Plugins",
  "Только просмотр: включение обработчиков возможно после починки P1-3":
    "Read-only: handlers can be enabled after the P1-3 fix",
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
  "handlersConnected=false — честный флаг этапа 4: пайплайн состоит из 9 фиксированных обработчиков, PluginManager подключает только личности. Переключатели появятся после P1-3.":
    "handlersConnected=false — the honest stage 4 flag: the pipeline consists of 9 fixed handlers, PluginManager only attaches personalities. Toggles will appear after P1-3.",

  // ── Список плагинов ───────────────────────────────────────────
  "Плагины не найдены": "No plugins found",
  "PluginManager не загрузил ни встроенного, ни внешнего плагина.":
    "PluginManager loaded neither built-in nor external plugins.",
  "Версия": "Version",
  "Автор": "Author",
};
