/**
 * Словарь EN для экрана «processes» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const PROCESSES_EN: Record<string, string> = {
  // ── Заголовок и поиск ─────────────────────────────────────────
  "Процессы": "Processes",
  "Завершение и питание требуют подтверждения: ConfirmDialog, затем токен TTL 60 с":
    "Kill and power actions require confirmation: ConfirmDialog, then a 60 s TTL token",
  "Поиск по имени процесса…": "Search by process name…",
  "Обновить": "Refresh",

  // ── Команды питания ───────────────────────────────────────────
  "Выключение": "Shut down",
  "Выключить компьютер?": "Shut down the computer?",
  "Компьютер будет выключен. Несохранённые данные будут потеряны.":
    "The computer will be shut down. Unsaved data will be lost.",
  "Выключить": "Shut down",
  "Перезагрузка": "Restart",
  "Перезагрузить компьютер?": "Restart the computer?",
  "Компьютер будет перезагружен. Несохранённые данные будут потеряны.":
    "The computer will be restarted. Unsaved data will be lost.",
  "Перезагрузить": "Restart",
  "Сон": "Sleep",
  "Перевести в сон?": "Put the computer to sleep?",
  "Работа будет приостановлена до нажатия кнопки питания.":
    "Work will be suspended until the power button is pressed.",
  "В сон": "Sleep",
  "Команда питания отменена": "Power command cancelled",
  "Команда «{label}» выполнена": "Command «{label}» executed",
  "Команда «{label}» не выполнена": "Command «{label}» not executed",
  "Ошибка команды питания: {message}": "Power command error: {message}",

  // ── Загрузка списка ───────────────────────────────────────────
  "Загрузка процессов…": "Loading processes…",
  "Неизвестная ошибка": "Unknown error",
  "Не удалось загрузить процессы": "Failed to load processes",
  "Повторить": "Retry",
  "Ошибка загрузки процессов": "Error loading processes",

  // ── Пустое состояние и счётчик ────────────────────────────────
  "Ничего не найдено": "Nothing found",
  "Процессы не найдены": "No processes found",
  "По запросу «{query}» совпадений нет.": "No matches for «{query}».",
  "Система не показала ни одного процесса.": "The system showed no processes at all.",
  "процессов: {count}": "processes: {count}",
  "найдено {count} по «{query}»": "found {count} for «{query}»",
  "память сверху": "highest memory first",

  // ── Таблица ───────────────────────────────────────────────────
  "Имя": "Name",
  "Память, МБ": "Memory, MB",
  "Отвечает": "Responsive",
  "Тип": "Type",
  "да": "yes",
  "нет": "no",
  "системный": "system",
  "пользовательский": "user",
  "Завершить": "End",
  "Системный процесс — завершение запрещено": "System process — termination is forbidden",

  // ── Завершение процесса ───────────────────────────────────────
  "«{name}» — системный процесс, завершение запрещено":
    "«{name}» is a system process; termination is forbidden",
  "Завершить «{name}»?": "End «{name}»?",
  "PID {pid} · память {mb} МБ. Процесс будет завершён принудительно.":
    "PID {pid} · memory {mb} MB. The process will be terminated forcibly.",
  "Завершить процесс": "End process",
  "Завершение процесса отменено": "Process termination cancelled",
  "Процесс «{name}» (PID {pid}) завершён": "Process «{name}» (PID {pid}) terminated",
  "Не удалось завершить: {message}": "Failed to terminate: {message}",
};
