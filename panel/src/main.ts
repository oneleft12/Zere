/**
 * Точка входа панели JARVIS. Этап 2: оболочка, роутер, статус-строка;
 * экраны подключаются по мере реализации (дашборд, настройки, личности).
 */

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";

import { apiGet, type Health } from "./api";
import { logEvent } from "./events";
import { initToasts } from "./ui";
import { navigate, registerRoute, startRouter } from "./router";
import { createShell } from "./shell";
import { initTheme, toggleTheme } from "./theme";
import { futureScreen } from "./screens/future";
import { dashboardScreen } from "./screens/dashboard";
import { settingsScreen } from "./screens/settings";

const theme = initTheme();
const shell = createShell((path) => navigate(path));
initToasts(shell.toastHost);

shell.themeButton.textContent = theme === "dark" ? "☾" : "☀";
shell.themeButton.addEventListener("click", () => {
  const next = toggleTheme();
  shell.themeButton.textContent = next === "dark" ? "☾" : "☀";
  logEvent(`Тема переключена: ${next === "dark" ? "тёмная" : "светлая"}`);
});

// Маршруты. Этап 2: дашборд/настройки/личности; 3–4: остальные.
registerRoute({ path: "/", title: "Дашборд", factory: dashboardScreen });
registerRoute({ path: "/settings", title: "Настройки", factory: settingsScreen });
registerRoute({
  path: "/personalities",
  title: "Личности",
  factory: futureScreen("Личности", 2),
});
registerRoute({ path: "/chat", title: "Чат", factory: futureScreen("Чат", 3) });
registerRoute({ path: "/history", title: "История", factory: futureScreen("История", 3) });
registerRoute({ path: "/memory", title: "Память", factory: futureScreen("Память", 3) });
registerRoute({ path: "/voice", title: "Голос", factory: futureScreen("Голос", 4) });
registerRoute({ path: "/processes", title: "Процессы", factory: futureScreen("Процессы", 4) });
registerRoute({ path: "/apps", title: "Приложения", factory: futureScreen("Приложения", 4) });
registerRoute({ path: "/plugins", title: "Плагины", factory: futureScreen("Плагины", 4) });
registerRoute({ path: "/logs", title: "Логи", factory: futureScreen("Логи", 4) });

startRouter(shell.content, (route) => {
  shell.setTitle(route.title);
  shell.setActive(route.path);
});

// Статус-строка: опрос /api/health (§5.3: микрофон · индекс · версия).
async function refreshStatus(): Promise<void> {
  try {
    const health = await apiGet<Health>("/api/health");
    const ollama = health.ollama === "ok" ? "Ollama OK" : "Ollama недоступен";
    const whisper = health.whisper === "ok" ? "Whisper OK" : "Whisper отсутствует";

    shell.statusLeft.textContent = `● ${ollama} · ${whisper} · ${health.tts.engine} · память: ${health.memory.count}`;
    shell.statusRight.textContent = `${health.branch} · ${health.version}`;
  } catch {
    shell.statusLeft.textContent = "● панель не отвечает";
  }
}

void refreshStatus();
window.setInterval(() => void refreshStatus(), 20_000);

logEvent("Панель запущена");
