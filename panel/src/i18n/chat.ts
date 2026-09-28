/**
 * Словарь EN для экрана «chat» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const CHAT_EN: Record<string, string> = {
  // ── Шапка и подсказки ─────────────────────────────────────────
  "Чат": "Chat",
  "Ответ приходит потоком (SSE) и сразу сохраняется в истории диалогов":
    "The reply streams in (SSE) and is saved to the conversation history right away",
  "SSE-стрим": "SSE stream",
  "Диалог с ассистентом": "Conversation with the assistant",
  "Enter — отправить": "Enter to send",
  "JARVIS отвечает…": "JARVIS is replying…",

  // ── Композер ──────────────────────────────────────────────────
  "Отправить": "Send",
  "Спросите JARVIS…": "Ask JARVIS…",

  // ── Пустой лог ────────────────────────────────────────────────
  "Начните диалог": "Start a conversation",
  "Спросите JARVIS о процессах, файлах или погоде — ответ придёт потоком и попадёт в историю.":
    "Ask JARVIS about processes, files or the weather — the reply arrives as a stream and goes into the history.",

  // ── Отправка и ошибки ─────────────────────────────────────────
  "Думаю…": "Thinking…",
  "Не удалось получить ответ": "Failed to get a reply",
  "Неизвестная ошибка": "Unknown error",
};
