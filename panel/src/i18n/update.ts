/**
 * Словарь EN для экрана «update» (обновление из GitHub, docs/UPDATE.md).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const UPDATE_EN: Record<string, string> = {
  // ── Заголовок и подзаголовок ──────────────────────────────────
  "Обновления": "Updates",
  "ZERE обновляется из GitHub быстрой перемоткой ветки: config/, zere.db и голосовые модели не перезаписываются":
    "ZERE updates itself from GitHub by fast-forwarding the branch: config/, zere.db and voice models are never overwritten",

  // ── Кнопки и состояния ────────────────────────────────────────
  "Проверить обновления": "Check for updates",
  "Обновить сейчас": "Update now",
  "git pull --ff-only текущей ветки": "git pull --ff-only of the current branch",
  "Обновление сейчас недоступно": "Update is unavailable right now",
  "Чтение состояния обновления…": "Reading update state…",
  "Обращение к GitHub…": "Contacting GitHub…",
  "Обновление применяется: git pull и зависимости…":
    "Applying the update: git pull and dependencies…",

  // ── Карточка состояния ────────────────────────────────────────
  "Состояние": "State",
  "Ветка": "Branch",
  "Установлено": "Installed",
  "Доступно": "Available",
  "нет обновлений": "no updates",
  "+{count} коммитов": "+{count} commits",
  "Рабочая копия": "Working copy",
  "есть правки": "local changes",
  "чисто": "clean",
  "Редакция": "Edition",
  "Репозиторий": "Repository",
  "Текущий коммит": "Current commit",
  "Удалённая ветка": "Remote branch",
  "Проверено": "Checked",
  "ещё не проверялось": "not checked yet",

  // ── Новые коммиты ─────────────────────────────────────────────
  "Новые коммиты": "New commits",
  "Новых коммитов нет": "No new commits",
  "Локальная ветка совпадает с удалённой.":
    "The local branch matches the remote one.",

  // ── Результат последнего обновления ───────────────────────────
  "Последнее обновление": "Last update",
  "Обновление ещё не запускалось": "The update has not run yet",
  "История обновлений не ведётся: показан результат последнего запуска.":
    "Update history is not stored: only the last run result is shown.",
  "применено": "applied",
  "отклонено": "declined",
  "зависимости: {value}": "dependencies: {value}",
  "Код на диске новее запущенного: закройте и снова запустите ZERE, чтобы изменения вступили в силу.":
    "The code on disk is newer than the running one: close and start ZERE again for the changes to take effect.",

  // ── Уведомления и ошибки ──────────────────────────────────────
  "Доступно {count} новых коммитов": "{count} new commits available",
  "Установлена последняя версия ветки": "The branch is up to date",
  "Проверка обновлений не удалась": "Update check failed",
  "Не удалось получить состояние обновления": "Failed to read the update state",
  "Доступно обновление ZERE: {count} коммитов — «Обновления»":
    "ZERE update available: {count} commits — see “Updates”",
  "обновление: {count}": "update: {count}",
  "актуальная версия": "up to date",
  "Открыть обновления": "Open updates",
  "Статус": "Status",
};
