/**
 * Словарь EN для экрана «memory» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const MEMORY_EN: Record<string, string> = {
  // ── Шапка, поиск, фильтр ──────────────────────────────────────
  "Память": "Memory",
  "Факты, которые JARVIS запомнил о вас: вручную и извлечённые автоматически":
    "Facts JARVIS has remembered about you: added manually and extracted automatically",
  "Поиск по ключу и значению…": "Search by key and value…",
  "Все источники": "All sources",
  "Добавить запись": "Add record",

  // ── Загрузка, ошибки, пустое состояние ────────────────────────
  "Загрузка памяти…": "Loading memory…",
  "Неизвестная ошибка": "Unknown error",
  "Не удалось загрузить память": "Failed to load memory",
  "Повторить": "Retry",
  "Ошибка загрузки памяти": "Error loading memory",
  "Ничего не найдено": "Nothing found",
  "Память пуста": "Memory is empty",
  "Измените запрос или фильтр источника.": "Change your query or the source filter.",
  "Добавьте запись вручную или попросите JARVIS что-нибудь запомнить.":
    "Add a record manually or ask JARVIS to remember something.",
  "записей: {count}": "records: {count}",
  "найдено {shown} из {total}": "found {shown} of {total}",

  // ── Таблица ───────────────────────────────────────────────────
  "Ключ": "Key",
  "Значение": "Value",
  "Источник": "Source",
  "Создано": "Created",
  "Изменить": "Edit",
  "Удалить": "Delete",

  // ── Редактор ──────────────────────────────────────────────────
  "например: любимый язык": "e.g. favorite language",
  "например: Python": "e.g. Python",
  "Новая запись памяти": "New memory record",
  "Изменить запись": "Edit record",
  "Ключ — идентификатор записи, он не меняется":
    "The key identifies the record and cannot be changed",
  "«User» — записано вручную, иное — извлечено из диалога":
    "“User” — added manually; anything else — extracted from the conversation",
  "Отмена": "Cancel",
  "Сохранить": "Save",

  // ── Валидация ─────────────────────────────────────────────────
  "ключ": "key",
  "значение": "value",
  "источник": "source",
  "Поле «{name}» не может быть пустым.": "The “{name}” field cannot be empty.",
  "Поле «{name}» длиннее {max} символов.": "The “{name}” field is longer than {max} characters.",

  // ── Сохранение ────────────────────────────────────────────────
  "Запись добавлена": "Record added",
  "Запись обновлена": "Record updated",
  "Не удалось сохранить запись": "Failed to save the record",

  // ── Удаление ──────────────────────────────────────────────────
  "Удалить запись из памяти?": "Delete this memory record?",
  "Ключ: «{key}» · значение: «{value}». Действие необратимо.":
    "Key: “{key}” · value: “{value}”. This action cannot be undone.",
  "Удаление отменено": "Deletion cancelled",
  "Запись «{key}» удалена": "Record “{key}” deleted",
  "Не удалось удалить запись: {message}": "Failed to delete the record: {message}",
};
