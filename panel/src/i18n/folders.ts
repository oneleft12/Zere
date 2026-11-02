/**
 * Словарь EN для экрана «folders».
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const FOLDERS_EN: Record<string, string> = {
  // ── Заголовок и поиск ─────────────────────────────────────────
  "Папки": "Folders",
  "Поиск по стандартным папкам, профилю и локальным дискам; открытие в проводнике":
    "Search standard folders, the user profile and local drives; open in Explorer",
  "Поиск папки по имени…": "Search folders by name…",
  "Обновить": "Refresh",

  // ── Загрузка ──────────────────────────────────────────────────
  "Не удалось загрузить папки": "Failed to load folders",
  "Ошибка загрузки папок": "Error loading folders",
  "Повторить": "Retry",
  "Неизвестная ошибка": "Unknown error",

  // ── Пустое состояние и счётчик ────────────────────────────────
  "Ничего не найдено": "Nothing found",
  "Папок нет": "No folders",
  "По запросу «{query}» совпадений нет.": "No matches for «{query}».",
  "Стандартные папки не найдены в профиле пользователя.":
    "No standard folders were found in the user profile.",
  "найдено 0 по «{query}»": "found 0 for «{query}»",
  "стандартных папок: {count}": "standard folders: {count}",
  "показаны {shown} из {total} по «{query}»": "showing {shown} of {total} for «{query}»",
  "найдено {count} по «{query}»": "found {count} for «{query}»",
  "Поиск ограничен по времени и глубине — уточните запрос, если нужной папки нет.":
    "Search is limited by time and depth — refine the query if the folder is missing.",

  // ── Таблица ───────────────────────────────────────────────────
  "Папка": "Folder",
  "Путь": "Path",
  "Изменена": "Modified",
  "Совпадение": "Match",
  "точное имя": "exact name",
  "начало имени": "name prefix",
  "слова": "words",
  "часть имени": "name part",
  "похоже": "similar",
  "путь": "path",
  "стандартная папка": "standard folder",
  "совпадение": "match",

  // ── Открытие ──────────────────────────────────────────────────
  "Открыть": "Open",
  "Открываю папку «{name}»": "Opening folder «{name}»",
  "Не удалось открыть папку: {message}": "Failed to open folder: {message}",
};
