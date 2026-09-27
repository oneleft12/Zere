/**
 * Дашборд (§5.4): ряд StatusPill, метрики, лента событий сессии.
 * Данные — только фактические из API; серверная лента /api/logs — этап 4.
 */

import { apiGet, type Config, type Health, type Personality } from "../api";
import { getEvents, logEvent, subscribeEvents } from "../events";
import {
  button,
  card,
  clear,
  emptyState,
  h,
  loadingRow,
  metric,
  pageHeader,
  statusPill,
} from "../ui";
import { navigate, type Cleanup, type ScreenFactory } from "../router";

interface DashboardData {
  health: Health;
  config: Config;
  personality: Personality | null;
}

async function fetchData(): Promise<DashboardData> {
  const [health, config, personality] = await Promise.allSettled([
    apiGet<Health>("/api/health"),
    apiGet<Config>("/api/config"),
    apiGet<Personality>("/api/personality"),
  ]);

  if (health.status === "rejected") throw health.reason;
  if (config.status === "rejected") throw config.reason;

  return {
    health: health.value,
    config: config.value,
    personality: personality.status === "fulfilled" ? personality.value : null,
  };
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export const dashboardScreen: ScreenFactory = (container): Cleanup => {
  container.appendChild(
    pageHeader("Дашборд", "Состояние сервисов ассистента", [
      button("Обновить", () => {
        logEvent("Обновление статусов по кнопке");
        void load();
      }, "primary"),
    ]),
  );

  const body = h("div", { class: "grid-12 fade-in" });
  container.appendChild(body);

  const eventsCard = card(
    "Последние события",
    h("div", { class: "events-box" }),
  );

  function renderEvents(): void {
    const box = eventsCard.querySelector(".events-box");
    if (!box) return;

    clear(box);

    const items = getEvents().slice(0, 5);

    if (items.length === 0) {
      box.appendChild(
        emptyState({ icon: "🗒", title: "Событий пока нет", hint: "Здесь появятся действия в этой сессии панели." }),
      );
      return;
    }

    const list = h("ul", { class: "event-list" });
    for (const item of items) {
      list.appendChild(
        h(
          "li",
          {},
          h("span", { class: "event-list__time", text: formatTime(item.time) }),
          h("span", { text: item.text }),
        ),
      );
    }
    box.appendChild(list);
  }

  function renderData(data: DashboardData): void {
    const { health, config, personality } = data;
    clear(body);

    const pills = h(
      "div",
      { class: "pill-row" },
      statusPill({
        label: "Ollama",
        value: health.ollama === "ok" ? "OK" : "недоступен",
        state: health.ollama === "ok" ? "ok" : "danger",
      }),
      statusPill({ label: "Модель", value: config.model, state: "ok" }),
      statusPill({
        label: "Whisper",
        value: health.whisper === "ok" ? "OK" : "отсутствует",
        state: health.whisper === "ok" ? "ok" : "warn",
      }),
      statusPill({ label: "TTS-движок", value: health.tts.engine, state: "ok" }),
      statusPill({ label: "Память", value: `${health.memory.count}`, state: "ok" }),
    );

    const metrics = h(
      "div",
      { class: "metrics-row" },
      metric(personality?.activeStyle ?? "—", "Стиль личности"),
      metric(`${Math.round(config.voiceVolume * 100)}%`, "Громкость голоса"),
      metric(`${config.ollamaTimeoutMinutes} мин`, "Таймаут Ollama"),
      metric(health.version, "Версия", `ветка ${health.branch}`),
    );

    const statusesCard = card("Статусы", pills);
    statusesCard.classList.add("col-12");

    const metricsCard = card("Метрики", metrics);
    metricsCard.classList.add("col-6");

    eventsCard.classList.add("col-6");

    const actionsCard = card(
      "Быстрые действия",
      h(
        "div",
        { class: "pill-row" },
        button("Настройки", () => navigate("/settings")),
        button("Личности", () => navigate("/personalities")),
      ),
    );
    actionsCard.classList.add("col-12");

    body.appendChild(statusesCard);
    body.appendChild(metricsCard);
    body.appendChild(eventsCard);
    body.appendChild(actionsCard);

    renderEvents();
  }

  function renderError(error: unknown): void {
    clear(body);

    const message = error instanceof Error ? error.message : "Неизвестная ошибка";
    body.appendChild(
      h(
        "div",
        { class: "col-12" },
        emptyState({
          icon: "⚠️",
          title: "Не удалось загрузить статусы",
          hint: message,
          action: { label: "Повторить", onClick: () => void load() },
        }),
      ),
    );
  }

  async function load(): Promise<void> {
    clear(body);
    body.appendChild(h("div", { class: "col-12" }, loadingRow("Опрос сервисов…")));

    try {
      renderData(await fetchData());
    } catch (error) {
      renderError(error);
    }
  }

  const unsubscribe = subscribeEvents(renderEvents);

  void load();

  return () => {
    unsubscribe();
  };
};
