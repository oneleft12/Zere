/**
 * Точка входа панели ZERE: оболочка, роутер, командная палитра, статус-строка.
 *
 * Статус-строка — пульт панели: каждая служба со своей точкой состояния,
 * орб слева показывает состояние ассистента целиком (покой / не настроен /
 * нет связи). Экран «Голос» перехватывает орб, пока открыт: там он
 * показывает слушание, размышление и речь по-настоящему.
 */

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

import {
  aiSupport,
  apiGet,
  foldersSupport,
  type AiStatus,
  type AiSupport,
  type Health,
  type UpdateStatus,
} from "./api";
import { ASSISTANT_STATE_EVENT, logEvent, type AssistantStateDetail } from "./events";
import { initLang, lang, onLangChange, t } from "./i18n";
import { clear, initToasts, toast } from "./ui";
import { icon } from "./icons";
import { initMotionGuards } from "./motion";
import { initPalette, openPalette } from "./palette";
import { navigate, registerRoute, startRouter } from "./router";
import { createShell, type StatusItem } from "./shell";
import { initTheme, toggleTheme, THEME_EVENT, type Theme } from "./theme";
import { aiScreen } from "./screens/ai";
import { dashboardScreen } from "./screens/dashboard";
import { settingsScreen } from "./screens/settings";
import { personalitiesScreen } from "./screens/personalities";
import { chatScreen } from "./screens/chat";
import { historyScreen } from "./screens/history";
import { memoryScreen } from "./screens/memory";
import { voiceScreen } from "./screens/voice";
import { processesScreen } from "./screens/processes";
import { appsScreen } from "./screens/apps";
import { foldersScreen } from "./screens/folders";
import { pluginsScreen } from "./screens/plugins";
import { logsScreen } from "./screens/logs";
import { updateScreen } from "./screens/update";

/** Состояние ассистента, объявленное экраном (например, голосовым режимом). */

// Язык (этап 5, i18n) читается до создания оболочки.
initLang();
initMotionGuards();

const theme = initTheme();
const shell = createShell((path) => navigate(path), { onOpenPalette: openPalette });
initToasts(shell.toastHost);
initPalette();

/** Иконка темы: луна в тёмной теме, солнце в светлой. */
function renderThemeIcon(next: Theme): void {
  clear(shell.themeButton);
  shell.themeButton.appendChild(icon(next === "dark" ? "moon" : "sun", { size: 17 }));
}

renderThemeIcon(theme);

shell.themeButton.addEventListener("click", () => {
  const next = toggleTheme();
  renderThemeIcon(next);
  logEvent(`Тема переключена: ${next === "dark" ? "тёмная" : "светлая"}`);
});

// Кнопка темы в шапке синхронизируется, когда тему меняют из Настроек
// или командной палитры.
document.addEventListener(THEME_EVENT, (event) => {
  renderThemeIcon((event as CustomEvent<Theme>).detail);
});

// Экраны объявляют состояние ассистента (голосовой режим: слушает/думает/говорит).
// Пока экран ведёт орб сам, оболочка в него не вмешивается: иначе опрос
// /api/health раз в 20 с гасил бы живую фазу голосового режима.
let screenOwnsAssistantState = 0;

document.addEventListener(ASSISTANT_STATE_EVENT, (event) => {
  const detail = (event as CustomEvent<AssistantStateDetail>).detail;
  screenOwnsAssistantState = Date.now();
  shell.setAssistantState(detail.state, detail.label ? t(detail.label) : undefined);
});

// Маршруты: название экрана в шапке, описание — в самом экране.
registerRoute({
  path: "/",
  title: "Главная страница",
  factory: dashboardScreen,
});
registerRoute({
  path: "/ai",
  title: "Подключение ИИ",
  factory: aiScreen,
});
registerRoute({
  path: "/settings",
  title: "Настройки",
  factory: settingsScreen,
});
registerRoute({
  path: "/personalities",
  title: "Личности",
  factory: personalitiesScreen,
});
registerRoute({
  path: "/chat",
  title: "Чат",
  factory: chatScreen,
});
registerRoute({
  path: "/history",
  title: "История",
  factory: historyScreen,
});
registerRoute({
  path: "/memory",
  title: "Память",
  factory: memoryScreen,
});
registerRoute({
  path: "/voice",
  title: "Голос",
  factory: voiceScreen,
});
registerRoute({
  path: "/processes",
  title: "Процессы",
  factory: processesScreen,
});
registerRoute({
  path: "/apps",
  title: "Приложения",
  factory: appsScreen,
});
registerRoute({
  path: "/folders",
  title: "Папки",
  factory: foldersScreen,
});
registerRoute({
  path: "/plugins",
  title: "Плагины",
  factory: pluginsScreen,
});
registerRoute({
  path: "/logs",
  title: "Логи",
  factory: logsScreen,
});
registerRoute({
  path: "/update",
  title: "Обновления",
  factory: updateScreen,
});

startRouter(shell.content, (route) => {
  shell.setTitle(t(route.title));
  shell.setActive(route.path);
});

// Статус-строка: опрос /api/health (§5.3: микрофон · индекс · версия),
// состояние ИИ (/api/ai: облако / локальная модель / не настроен) и
// отметка о доступном обновлении из /api/update (кэш автопроверки, без сети).
let updateNoticeShown = false;
let aiNoticeShown = false;

/** Метка свежести данных в шапке: видно, что состояние не «застыло». */
function freshTime(): string {
  return new Date().toLocaleTimeString(lang() === "en" ? "en-US" : "ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// Редакция бэкенда: Python-панель умеет настройку ИИ, C#-панель — нет.
// Определяем один раз, чтобы не показывать «Маршрут не найден» и не
// скрывать рабочие экраны там, где бэкенд просто не ответил.
let aiSupportState: AiSupport = "unknown";

void aiSupport().then((state) => {
  aiSupportState = state;

  if (state === "unsupported") {
    // C#-редакция: настройка облачного ключа не реализована — прячем пункт меню.
    shell.setNavVisible("/ai", false);
    logEvent("Настройка облачного ключа недоступна: C#-редакция панели");
  } else if (state === "restart-required") {
    toast(t("Перезапустите ZERE: настройка ИИ включится после обновления сервера"), "warn");
    logEvent("Сервер ZERE старее панели: нужен перезапуск для настройки ИИ");
  }

  void refreshStatus();
});

// Экран «Папки» есть только в Python-редакции. На C#-панели маршрута нет —
// прячем пункт меню, а не показываем «Маршрут не найден».
void foldersSupport().then((state) => {
  if (state === "unsupported") {
    shell.setNavVisible("/folders", false);
    logEvent("Поиск папок недоступен: C#-редакция панели");
  }
});

async function refreshStatus(): Promise<void> {
  try {
    const [health, update] = await Promise.all([
      apiGet<Health>("/api/health"),
      apiGet<UpdateStatus>("/api/update").catch(() => null),
    ]);

    // Состояние ИИ спрашиваем только у бэкенда, который его умеет.
    const canAskAi = aiSupportState === "ready" || aiSupportState === "unknown";
    const ai = canAskAi
      ? await apiGet<AiStatus>("/api/ai").catch(() => null)
      : null;

    const statuses: StatusItem[] = [
      {
        text: health.ollama === "ok" ? "Ollama OK" : t("Ollama недоступен"),
        state: health.ollama === "ok" ? "ok" : "danger",
      },
      {
        text: health.whisper === "ok" ? "Whisper OK" : t("Whisper отсутствует"),
        state: health.whisper === "ok" ? "ok" : "warn",
      },
      { text: health.tts.engine, state: "ok" },
      { text: t("память: {count}", { count: health.memory.count }), state: "ok" },
    ];

    let aiLabel = "";
    let aiState: StatusItem["state"] = "idle";

    if (canAskAi) {
      if (ai) {
        if (ai.activeProvider === "cloud") {
          aiLabel = t("ИИ: облако");
          aiState = "ok";
        } else if (ai.activeProvider === "local") {
          aiLabel = t("ИИ: локально");
          aiState = "ok";
        } else {
          aiLabel = t("ИИ: не настроен");
          aiState = "warn";
        }
      }
    } else if (aiSupportState === "restart-required") {
      aiLabel = t("ИИ: перезапустите ZERE");
      aiState = "warn";
    } else {
      aiLabel = t("ИИ: только локально");
      aiState = "idle";
    }

    if (aiLabel) statuses.push({ text: aiLabel, state: aiState });

    shell.setStatuses(statuses);
    shell.setVersion(health.version);
    shell.setSubtitle(t("обновлено {time}", { time: freshTime() }));

    // Состояние ассистента — только если его не ведёт открытый экран.
    if (Date.now() - screenOwnsAssistantState > 5000) {
      shell.setAssistantState(
        ai && !ai.ready ? "error" : "idle",
        ai && !ai.ready
          ? t("ИИ не настроен: включите ключ или локальную модель")
          : t("ZERE готов"),
      );
    }

    shell.statusRight.textContent = update?.updateAvailable
      ? `${health.branch} · ${health.version} · ${t("обновление: {count}", { count: update.behind })}`
      : `${health.branch} · ${health.version}`;

    // Один раз за сессию: не превращаем каждые 20 с в напоминание.
    if (update?.updateAvailable && !updateNoticeShown) {
      updateNoticeShown = true;
      toast(t("Доступно обновление ZERE: {count} коммитов — «Обновления»", { count: update.behind }), "warn");
    }

    // ИИ не настроен — один раз подсказываем, где ввести ключ или включить
    // локальную модель (требование 1: состояние видно сразу при входе).
    if (ai && !ai.ready && !aiNoticeShown) {
      aiNoticeShown = true;
      toast(t("Чтобы начать, введите API-ключ или установите локальную модель"), "warn");
    }
  } catch {
    shell.setStatuses([{ text: t("панель не отвечает"), state: "danger" }]);
    shell.setAssistantState("offline", t("Нет связи с ZERE"));
    shell.setSubtitle(t("нет связи с сервером"));
  }
}

void refreshStatus();
window.setInterval(() => void refreshStatus(), 20_000);

// Смена языка (этап 5): перерисовываем текущий экран и статус-строку.
onLangChange(() => {
  navigate(window.location.pathname);
  void refreshStatus();
});

logEvent("Панель запущена");
