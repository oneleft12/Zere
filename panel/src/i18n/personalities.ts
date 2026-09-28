/**
 * Словарь EN для экрана «personalities» (этап 5, i18n ru→en).
 * Ключ — точная русская строка, переданная в t(); значение — перевод.
 * Плейсхолдеры {var} сохраняются как есть.
 */
export const PERSONALITIES_EN: Record<string, string> = {
  // ── Шапка ─────────────────────────────────────────────────────
  "Личности": "Personalities",
  "Активная личность: {id} · стиль {style}": "Active personality: {id} · style {style}",
  "стилей: {count}": "styles: {count}",
  "Стиль сохраняется в config/plugins.json и переживает рестарт ассистента.":
    "The style is saved to config/plugins.json and survives an assistant restart.",

  // ── Карточки стилей ───────────────────────────────────────────
  "активный": "active",
  "Описание появится позже": "Description will appear later",
  "Дружелюбный, тёплый, с эмодзи": "Friendly, warm, with emojis",
  "Официальный, строгий, профессиональный": "Official, strict, professional",
  "Саркастичный, с иронией и юмором": "Sarcastic, with irony and humor",
  "Деловой, без лишних слов": "Businesslike, no wasted words",
  "Неформальный, на «ты»": "Informal, relaxed and conversational",

  // ── Смена стиля ───────────────────────────────────────────────
  "Стиль «{name}» сохранён — переживёт рестарт": "Style “{name}” saved — will survive a restart",
  "Не удалось сменить стиль": "Failed to switch style",

  // ── Загрузка и ошибки ─────────────────────────────────────────
  "Загрузка личностей…": "Loading personalities…",
  "Не удалось загрузить личности": "Failed to load personalities",
  "Повторить": "Retry",
  "Неизвестная ошибка": "Unknown error",
};
