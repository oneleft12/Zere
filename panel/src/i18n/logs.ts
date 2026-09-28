/**
 * Словарь EN для экрана «logs» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const LOGS_EN: Record<string, string> = {
  // ── Заголовок и фильтры ───────────────────────────────────────
  "Логи": "Logs",
  "Файлы logs/*.log в обратном порядке: новые сверху; сбой показывается здесь, не в UI":
    "logs/*.log files in reverse order: newest on top; failures are shown here, not in the UI",
  "Все уровни": "All levels",
  "Обновить": "Refresh",
  "← Назад": "← Back",
  "Вперёд →": "Forward →",

  // ── Пагинация и счётчик ───────────────────────────────────────
  "{count} записей": "{count} entries",
  "{from}–{to} из {total}": "{from}–{to} of {total}",
  "{level}: {total} · показано {from}–{to}": "{level}: {total} · shown {from}–{to}",
  "записей: {total} · показано {from}–{to}": "records: {total} · shown {from}–{to}",

  // ── Загрузка и ошибки ─────────────────────────────────────────
  "Чтение логов…": "Reading logs…",
  "Неизвестная ошибка": "Unknown error",
  "Не удалось прочитать логи": "Failed to read logs",
  "Повторить": "Retry",
  "Ошибка чтения логов": "Error reading logs",

  // ── Пустое состояние ──────────────────────────────────────────
  "Записей нет": "No entries",
  "Уровня «{level}» в логах нет.": "No «{level}» entries in the logs.",
  "Логи появятся после первых событий панели и ассистента.":
    "Logs will appear after the first panel and assistant events.",
};
