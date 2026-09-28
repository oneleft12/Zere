/**
 * Словарь EN для экрана «apps» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const APPS_EN: Record<string, string> = {
  // ── Заголовок и поиск ─────────────────────────────────────────
  "Приложения": "Applications",
  "Индекс сканеров (реестр, меню «Пуск», AppPaths, LocalAppData) для голосового запуска":
    "Scanner index (registry, Start menu, AppPaths, LocalAppData) for voice launching",
  "Поиск по имени или алиасу…": "Search by name or alias…",
  "Переиндексировать": "Reindex",

  // ── Загрузка списка ───────────────────────────────────────────
  "Загрузка приложений…": "Loading applications…",
  "Неизвестная ошибка": "Unknown error",
  "Не удалось загрузить приложения": "Failed to load applications",
  "Повторить": "Retry",
  "Ошибка загрузки приложений": "Error loading applications",

  // ── Пустое состояние и счётчик ────────────────────────────────
  "Ничего не найдено": "Nothing found",
  "Индекс пуст": "Index is empty",
  "По запросу «{query}» совпадений нет.": "No matches for «{query}».",
  "Нажмите «Переиндексировать», чтобы сканеры собрали установленные приложения.":
    "Click “Reindex” so the scanners collect the installed applications.",
  "приложений: {count}": "applications: {count}",
  "найдено {count} по «{query}» из {total}": "found {count} for «{query}» of {total}",

  // ── Таблица ───────────────────────────────────────────────────
  "Название": "Name",
  "Категория": "Category",
  "Сканер": "Scanner",
  "Приоритет": "Priority",
  "Алиасы": "Aliases",
  "Путь": "Path",

  // ── Переиндексация ────────────────────────────────────────────
  "Найдено приложений: {count} за {ms} мс": "Found {count} applications in {ms} ms",
  "Переиндексация не удалась: {message}": "Reindexing failed: {message}",
};
