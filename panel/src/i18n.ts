/**
 * Локализация UI (этап 5, i18n ru→en): язык выбирается в «Настройках».
 *
 * Словарь — русская строка → английская. t() вне словаря возвращает
 * исходную строку, поэтому непереведённое аккуратно падает на ru,
 * а не превращается в пустоту. Подстановка: t("Привет, {name}", {name}).
 */

import { APPS_EN } from "./i18n/apps";
import { AI_EN } from "./i18n/ai";
import { CHAT_EN } from "./i18n/chat";
import { DASHBOARD_EN } from "./i18n/dashboard";
import { FOLDERS_EN } from "./i18n/folders";
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
  "Разделы панели": "Panel sections",
  "Состояние служб": "Service status",
  "Состояние ассистента": "Assistant state",
  "Свернуть панель": "Collapse sidebar",
  "Развернуть панель": "Expand sidebar",
  "Поиск и команды": "Search and commands",
  "Поиск по панели": "Search the panel",
  "Экран, действие или команда ZERE…": "Screen, action or ZERE command…",
  "Палитра команд": "Command palette",
  "Перейти": "Go to",
  "Перейти на экран": "Open screen",
  "Действия": "Actions",
  "Команды ZERE": "ZERE commands",
  "Тёмная тема": "Dark theme",
  "Оформление панели": "Panel appearance",
  "Проверить обновления ZERE": "Check for ZERE updates",
  "Ветка, коммиты, применение": "Branch, commits, apply",
  "выбор": "select",
  "выполнить": "run",
  "Скопировать": "Copy",
  "Скопировать команду": "Copy command",
  "отправить": "send",
  "ZERE готов": "ZERE is ready",
  "ZERE думает": "ZERE is thinking",
  "ZERE отвечает": "ZERE is answering",
  "Ответ не получен": "No answer",
  "ИИ не настроен: включите ключ или локальную модель":
    "AI is not configured: add a key or run a local model",
  "панель не отвечает": "panel is not responding",
  "нет связи с сервером": "no connection to the server",
  "обновлено {time}": "updated {time}",
  "Нет связи с ZERE": "No connection to ZERE",
  "Состояние сервисов ассистента": "Assistant service health",
  "Ответ приходит потоком и сразу попадает в историю":
    "The answer streams in and lands in history right away",
  "Модель, язык, голос и память в одном файле": "Model, language, voice and memory in one file",
  "Характер и температура ответов ассистента": "The assistant's character and answer temperature",
  "Каждый диалог с ассистентом": "Every conversation with the assistant",
  "Что ZERE знает о вас и о проектах": "What ZERE knows about you and your projects",
  "Слово-триггер, распознавание речи и озвучка ответов":
    "Wake word, speech recognition and spoken answers",
  "Запущенные программы и завершение процессов": "Running programs and killing processes",
  "Индекс установленных программ и алиасы запуска": "Installed app index and launch aliases",
  "Личности и обработчики команд, встроенные и внешние":
    "Personalities and command handlers, built-in and external",
  "Последние события сервера ZERE": "Latest ZERE server events",
  "Проверка ветки и обновление из GitHub": "Branch check and update from GitHub",
  "Свой ключ облачной модели или локальная модель на этом ПК":
    "Your cloud model key or a local model on this PC",
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
  "Язык ассистента": "Assistant language",
  "Язык ответов ассистента: смена действует сразу, без перезапуска":
    "Assistant answer language: applied immediately, no restart needed",
  "русский": "Russian",
  "английский": "English",
  // ── Дашборд, ИИ, голос, плагины: строки, которые раньше падали на ru ──
  "ZERE готов отвечать": "ZERE is ready",
  "ZERE без модели": "ZERE has no model configured",
  "Стиль": "Style",
  "Открыть чат": "Open chat",
  "Записей в памяти": "Memory records",
  "Локальная модель не ответила": "The local model did not respond",
  "Ключ можно получить здесь: ": "Get a key here: ",
  "Фаза непрерывного слушателя: слово-триггер → команда → ответ":
    "Continuous listener phase: wake word → command → answer",
  "Плагины-обработчики подключены к конвейеру: их команды работают. Внешние плагины кладутся в ./plugins/*.py и загружаются при старте.":
    "Command-handler plugins are wired into the pipeline: their commands work. External plugins live in ./plugins/*.py and are loaded on start.",
  "handlersConnected=false — плагины-обработчики этой сборки не подключены к конвейеру: они видны в списке, но команд не получают.":
    "handlersConnected=false — this build does not wire command-handler plugins into the pipeline: they are listed but never receive commands.",
  "Значения честные для текущей реализации: C# умеет больше, Python-порт отдаёт false там, где функции ещё нет — панель это показывает, а не скрывает.":
    "Values reflect the current implementation honestly: the C# edition does more, the Python port reports false where a feature is missing — the panel shows that instead of hiding it.",
  "Двухбуквенный код: ru, en": "Two-letter code: ru, en",
  "Таймаут Ollama, мин": "Ollama timeout, min",
  "От 1 до 120 минут": "From 1 to 120 minutes",
  "Голосовой вывод включён": "Voice output enabled",
  "pocket — клонирование голоса": "pocket — voice cloning",
  "silero — русский голос: ударения, цифры и английские слова": "silero — Russian voice: stress marks, numbers and English words",
  "Референс голоса (WAV)": "Voice reference (WAV)",
  "путь к WAV-референсу, пусто = встроенный голос":
    "path to the WAV reference, empty = built-in voice",
  "Смена применяется сразу": "Applied immediately",
};

/** Словари экранов лежат в panel/src/i18n/<screen>.ts — по файлу на экран. */
const EN: Record<string, string> = {
  ...CORE_EN,
  ...AI_EN,
  ...DASHBOARD_EN,
  ...CHAT_EN,
  ...HISTORY_EN,
  ...MEMORY_EN,
  ...VOICE_EN,
  ...PROCESSES_EN,
  ...APPS_EN,
  ...FOLDERS_EN,
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
