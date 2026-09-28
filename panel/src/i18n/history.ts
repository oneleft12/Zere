/**
 * Словарь EN для экрана «history» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const HISTORY_EN: Record<string, string> = {
  // ── Шапка и панель управления ─────────────────────────────────
  "История": "History",
  "Сохранённые пары «вопрос → ответ»; очистка требует подтверждения":
    "Saved “question → answer” pairs; clearing requires confirmation",
  "Поиск по вопросам и ответам…": "Search questions and answers…",
  "Экспорт JSON": "Export JSON",
  "Очистить": "Clear",
  "← Назад": "← Back",
  "Вперёд →": "Forward →",

  // ── Пагинация, загрузка, ошибки ───────────────────────────────
  "0 записей": "0 records",
  "{from}–{to} из {total}": "{from}–{to} of {total}",
  "Загрузка истории…": "Loading history…",
  "Неизвестная ошибка": "Unknown error",
  "Не удалось загрузить историю": "Failed to load history",
  "Повторить": "Retry",
  "Ошибка загрузки истории": "Error loading history",

  // ── Пустое состояние и счётчики ───────────────────────────────
  "Ничего не найдено": "Nothing found",
  "История пуста": "History is empty",
  "По запросу «{query}» совпадений нет.": "No matches for «{query}».",
  "Диалоги начнут появляться здесь после первых сообщений в чате.":
    "Conversations will appear here after your first messages in chat.",
  "найдено {total} · показано {from}–{to}": "found {total} · showing {from}–{to}",
  "записей: {total} · показано {from}–{to}": "records: {total} · shown {from}–{to}",

  // ── Карточка диалога ──────────────────────────────────────────
  "Вы": "You",

  // ── Очистка ───────────────────────────────────────────────────
  "Очистить историю?": "Clear history?",
  "Будет удалено записей: {count}. Отменить это действие будет невозможно.":
    "{count} records will be deleted. This action cannot be undone.",
  "Удалить историю": "Delete history",
  "Очистка истории отменена": "History clearing cancelled",
  "История очищена — удалено записей: {count}": "History cleared — {count} records deleted",
  "Не удалось очистить историю: {message}": "Failed to clear history: {message}",

  // ── Экспорт ───────────────────────────────────────────────────
  "Экспортировано записей: {count}": "Exported records: {count}",
  "Экспорт не удался: {message}": "Export failed: {message}",
};
