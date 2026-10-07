/**
 * Локализация UI (этап 5, i18n ru→en): язык выбирается в «Настройках».
 *
 * Словарь — русская строка → английская. t() вне словаря возвращает
 * исходную строку, поэтому непереведённое аккуратно падает на ru,
 * а не превращается в пустоту. Подстановка: t("Привет, {name}", {name}).
 */

import { APPS_EN } from "./i18n/apps";
import { CHAT_EN } from "./i18n/chat";
import { DASHBOARD_EN } from "./i18n/dashboard";
import { HISTORY_EN } from "./i18n/history";
import { LOGS_EN } from "./i18n/logs";
import { MEMORY_EN } from "./i18n/memory";
import { PERSONALITIES_EN } from "./i18n/personalities";
import { PLUGINS_EN } from "./i18n/plugins";
import { PROCESSES_EN } from "./i18n/processes";
import { UPDATE_EN } from "./i18n/update";
import { VOICE_EN } from "./i18n/voice";

export type Lang = "ru" | "en";

const STORAGE_KEY = "zere-lang";

/** ru → en. Ключи — точные русские строки из интерфейса. */
const CORE_EN: Record<string, string> = {
  // ── Оболочка (shell, статус) ───────────────────────────────────
  "Ассистент": "Assistant",
  "Система": "System",
  "Панель": "Panel",
  "Дашборд": "Dashboard",
  "Чат": "Chat",
  "История": "History",
  "Память": "Memory",
  "Голос": "Voice",
  "Процессы": "Processes",
  "Приложения": "Applications",
  "Плагины": "Plugins",
  "Логи": "Logs",
  "Настройки": "Settings",
  "Личности": "Personalities",
  "Переключить тему": "Toggle theme",
  "● статусы…": "● statuses…",
  "● панель не отвечает": "● panel is not responding",
  "Ollama недоступен": "Ollama unavailable",
  "Whisper отсутствует": "Whisper missing",
  "память: {count}": "memory: {count}",
  "Панель запущена": "Panel started",
  "Тема переключена: тёмная": "Theme switched: dark",
  "Тема переключена: светлая": "Theme switched: light",
  "Тема переключена: {theme}": "Theme switched: {theme}",

  // ── Компоненты (ui.ts) ─────────────────────────────────────────
  "Отмена": "Cancel",
  "Подтвердить": "Confirm",
  "Повторить": "Retry",
  "Обновить": "Refresh",
  "Сохранить": "Save",
  "Сохранение…": "Saving…",
  "Загрузка…": "Loading…",
  "Нет данных": "No data",
  "Что-то пошло не так": "Something went wrong",

  // ── Настройки ──────────────────────────────────────────────────
  "Конфигурация ассистента: модель, язык, голос, память — всё в одном месте":
    "Assistant configuration: model, language, voice, memory — all in one place",
  "Отменить изменения": "Revert changes",
  "Имя ассистента": "Assistant name",
  "Язык общения": "Chat language",
  "Модель Ollama": "Ollama model",
  "Таймаут ответа, мин": "Response timeout, min",
  "Голосовой вывод": "Voice output",
  "Голос включён": "Voice enabled",
  "Громкость": "Volume",
  "TTS-движок": "TTS engine",
  "Референс голоса": "Voice reference",
  "Автоизвлечение фактов из диалога": "Auto-extract facts from conversation",
  "Оформление": "Appearance",
  "Светлая тема": "Light theme",
  "Тёмная тема — по умолчанию. CSS-анимации автоматически сокращаются при системной настройке «уменьшить движение».":
    "Dark theme is the default. CSS animations are automatically reduced when the system setting “reduce motion” is on.",
  "О программе": "About",
  "Версия": "Version",
  "Ветка": "Branch",
  "Схема конфига": "Config schema",
  "Файл": "File",
  "API-контракт": "API contract",
  "Язык интерфейса": "Interface language",
  "Конфигурация сохранена": "Configuration saved",
  "Ошибка сохранения настроек": "Failed to save settings",
  "Настройки сохранены в config/config.json": "Settings saved to config/config.json",
  "Изменения настроек отброшены": "Settings changes discarded",
  "Не удалось загрузить конфигурацию": "Failed to load configuration",
  "Сервер отклонил конфигурацию: {message}": "Server rejected the configuration: {message}",
  "Схема конфигурации v1.7": "Configuration schema v1.7",
  "все 10 ключей обязательны": "all 10 keys are required",
  "только читаемые поля (поля-призраки скрыты)": "readable fields only (phantom fields hidden)",
  "Авто-сохранение в config/config.json": "Auto-saved to config/config.json",
  "Смена языка применяется к ассистенту после сохранения":
    "Language change applies to the assistant after saving",
  "Загрузка конфигурации…": "Loading configuration…",
  "Неизвестная ошибка": "Unknown error",
  "Конфигурация config/config.json — строгая схема, валидация на сервере":
    "config/config.json — strict schema, validated server-side",
  "Язык": "Language",
  "Двухбуквенный код: ru, en": "Two-letter code: ru, en",
  "Таймаут Ollama, мин": "Ollama timeout, min",
  "От 1 до 120 минут": "From 1 to 120 minutes",
  "Голосовой вывод включён": "Voice output enabled",
  "pocket — клонирование голоса": "pocket — voice cloning",
  "piper — быстрый, без клонирования": "piper — fast, no cloning",
  "Референс голоса (WAV)": "Voice reference (WAV)",
  "путь к WAV-референсу, пусто = встроенный голос":
    "path to the WAV reference, empty = built-in voice",
  "Смена применяется сразу": "Applied immediately",
};

/** Словари экранов лежат в panel/src/i18n/<screen>.ts — по файлу на экран. */
const EN: Record<string, string> = {
  ...CORE_EN,
  ...DASHBOARD_EN,
  ...CHAT_EN,
  ...HISTORY_EN,
  ...MEMORY_EN,
  ...VOICE_EN,
  ...PROCESSES_EN,
  ...APPS_EN,
  ...PLUGINS_EN,
  ...LOGS_EN,
  ...PERSONALITIES_EN,
  ...UPDATE_EN,
};

let current: Lang = "ru";
const listeners = new Set<() => void>();

/** Читает сохранённый язык; вызывается один раз до создания оболочки. */
export function initLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    current = saved === "en" ? "en" : "ru";
  } catch {
    current = "ru";
  }

  document.documentElement.lang = current === "en" ? "en" : "ru";
  return current;
}

export function lang(): Lang {
  return current;
}

export function setLang(next: Lang): void {
  if (next === current) return;
  current = next;
  document.documentElement.lang = next === "en" ? "en" : "ru";

  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // localStorage может быть недоступен — язык просто не запомнится
  }

  for (const listener of listeners) listener();
}

/** Подписка на смену языка; возвращает функцию отписки. */
export function onLangChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Перевод: en → словарь, ru и пропуски → исходная строка. */
export function t(key: string, vars?: Record<string, string | number>): string {
  let text = current === "en" ? (EN[key] ?? key) : key;

  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }

  return text;
}
