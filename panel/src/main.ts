/**
 * Точка входа панели ZERE. Этап 2: оболочка, роутер, статус-строка;
 * экраны подключаются по мере реализации (дашборд, настройки, личности).
 */

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

import { apiGet, type Health, type UpdateStatus } from "./api";
import { logEvent } from "./events";
import { initLang, onLangChange, t } from "./i18n";
import { initToasts, toast } from "./ui";
import { navigate, registerRoute, startRouter } from "./router";
import { createShell } from "./shell";
import { initTheme, toggleTheme, THEME_EVENT, type Theme } from "./theme";
import { dashboardScreen } from "./screens/dashboard";
import { settingsScreen } from "./screens/settings";
import { personalitiesScreen } from "./screens/personalities";
import { chatScreen } from "./screens/chat";
import { historyScreen } from "./screens/history";
import { memoryScreen } from "./screens/memory";
import { voiceScreen } from "./screens/voice";
import { processesScreen } from "./screens/processes";
import { appsScreen } from "./screens/apps";
import { pluginsScreen } from "./screens/plugins";
import { logsScreen } from "./screens/logs";
import { updateScreen } from "./screens/update";

// Язык (этап 5, i18n) читается до создания оболочки.
initLang();

const theme = initTheme();
const shell = createShell((path) => navigate(path));
initToasts(shell.toastHost);

shell.themeButton.textContent = theme === "dark" ? "☾" : "☀";
shell.themeButton.addEventListener("click", () => {
  const next = toggleTheme();
  shell.themeButton.textContent = next === "dark" ? "☾" : "☀";
  logEvent(`Тема переключена: ${next === "dark" ? "тёмная" : "светлая"}`);
});

// Кнопка темы в шапке синхронизируется, когда тему меняют из Настроек.
document.addEventListener(THEME_EVENT, (event) => {
  const next = (event as CustomEvent<Theme>).detail;
  shell.themeButton.textContent = next === "dark" ? "☾" : "☀";
});

// Маршруты. Этап 2: дашборд/настройки/личности; 3: чат/история/память;
// 4: голос/процессы/приложения/плагины/логи.
registerRoute({ path: "/", title: "Дашборд", factory: dashboardScreen });
registerRoute({ path: "/settings", title: "Настройки", factory: settingsScreen });
registerRoute({ path: "/personalities", title: "Личности", factory: personalitiesScreen });
registerRoute({ path: "/chat", title: "Чат", factory: chatScreen });
registerRoute({ path: "/history", title: "История", factory: historyScreen });
registerRoute({ path: "/memory", title: "Память", factory: memoryScreen });
registerRoute({ path: "/voice", title: "Голос", factory: voiceScreen });
registerRoute({ path: "/processes", title: "Процессы", factory: processesScreen });
registerRoute({ path: "/apps", title: "Приложения", factory: appsScreen });
registerRoute({ path: "/plugins", title: "Плагины", factory: pluginsScreen });
registerRoute({ path: "/logs", title: "Логи", factory: logsScreen });
registerRoute({ path: "/update", title: "Обновления", factory: updateScreen });

startRouter(shell.content, (route) => {
  shell.setTitle(t(route.title));
  shell.setActive(route.path);
});

// Статус-строка: опрос /api/health (§5.3: микрофон · индекс · версия) и
// отметка о доступном обновлении из /api/update (кэш автопроверки, без сети).
let updateNoticeShown = false;

async function refreshStatus(): Promise<void> {
  try {
    const [health, update] = await Promise.all([
      apiGet<Health>("/api/health"),
      apiGet<UpdateStatus>("/api/update").catch(() => null),
    ]);
    const ollama = health.ollama === "ok" ? "Ollama OK" : t("Ollama недоступен");
    const whisper = health.whisper === "ok" ? "Whisper OK" : t("Whisper отсутствует");
    const memory = t("память: {count}", { count: health.memory.count });

    shell.statusLeft.textContent = `● ${ollama} · ${whisper} · ${health.tts.engine} · ${memory}`;
    shell.statusRight.textContent = update?.updateAvailable
      ? `${health.branch} · ${health.version} · ⬆ ${t("обновление: {count}", { count: update.behind })}`
      : `${health.branch} · ${health.version}`;

    // Один раз за сессию: не превращаем каждые 20 с в напоминание.
    if (update?.updateAvailable && !updateNoticeShown) {
      updateNoticeShown = true;
      toast(t("Доступно обновление ZERE: {count} коммитов — «Обновления»", { count: update.behind }), "warn");
    }
  } catch {
    shell.statusLeft.textContent = t("● панель не отвечает");
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
