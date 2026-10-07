/**
 * Дашборд (§5.4): ряд StatusPill, метрики, лента событий сессии.
 * Данные — только фактические из API; серверная лента /api/logs — этап 4.
 */

import {
  apiGet,
  aiSupport,
  type AiStatus,
  type AiSupport,
  type Config,
  type Health,
  type Personality,
  type UpdateStatus,
} from "../api";
import { getEvents, logEvent, subscribeEvents } from "../events";
import { t } from "../i18n";
import {
  badge,
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
  update: UpdateStatus | null;
  ai: AiStatus | null;
  /** Умеет ли запущенный бэкенд настройку ИИ (редакция/перезапуск). */
  aiSupport: AiSupport;
}

async function fetchData(): Promise<DashboardData> {
  const [health, config, personality, update, ai] = await Promise.allSettled([
    apiGet<Health>("/api/health"),
    apiGet<Config>("/api/config"),
    apiGet<Personality>("/api/personality"),
    apiGet<UpdateStatus>("/api/update"),
    apiGet<AiStatus>("/api/ai"),
  ]);

  if (health.status === "rejected") throw health.reason;
  if (config.status === "rejected") throw config.reason;

  return {
    health: health.value,
    config: config.value,
    personality: personality.status === "fulfilled" ? personality.value : null,
    update: update.status === "fulfilled" ? update.value : null,
    ai: ai.status === "fulfilled" ? ai.value : null,
    aiSupport: await aiSupport(),
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
    pageHeader(t("Дашборд"), t("Состояние сервисов ассистента"), [
      button(t("Обновить"), () => {
        logEvent("Обновление статусов по кнопке");
        void load();
      }, "primary"),
    ]),
  );

  const body = h("div", { class: "grid-12 fade-in" });
  container.appendChild(body);

  const eventsCard = card(
    t("Последние события"),
    h("div", { class: "events-box" }),
  );

  function renderEvents(): void {
    const box = eventsCard.querySelector(".events-box");
    if (!box) return;

    clear(box);

    const items = getEvents().slice(0, 5);

    if (items.length === 0) {
      box.appendChild(
        emptyState({ icon: "🗒", title: t("Событий пока нет"), hint: t("Здесь появятся действия в этой сессии панели.") }),
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
    const { health, config, personality, update, ai, aiSupport: support } = data;
    clear(body);

    const pills = h(
      "div",
      { class: "pill-row" },
      statusPill({
        label: "Ollama",
        value: health.ollama === "ok" ? "OK" : t("недоступен"),
        state: health.ollama === "ok" ? "ok" : "danger",
      }),
      statusPill({ label: t("Модель"), value: config.model, state: "ok" }),
      statusPill({
        label: "Whisper",
        value: health.whisper === "ok" ? "OK" : t("отсутствует"),
        state: health.whisper === "ok" ? "ok" : "warn",
      }),
      statusPill({ label: t("TTS-движок"), value: health.tts.engine, state: "ok" }),
      statusPill({ label: t("Память"), value: `${health.memory.count}`, state: "ok" }),
    );

    const metrics = h(
      "div",
      { class: "metrics-row" },
      metric(personality?.activeStyle ?? "—", t("Стиль личности")),
      metric(`${Math.round(config.voiceVolume * 100)}%`, t("Громкость голоса")),
      metric(t("{value} мин", { value: config.ollamaTimeoutMinutes }), t("Таймаут Ollama")),
      metric(health.version, t("Версия"), t("ветка {branch}", { branch: health.branch })),
    );

    const statusesCard = card(t("Статусы"), pills);
    statusesCard.classList.add("col-12");

    // ── ИИ: облачный ключ или локальная модель (требование 1) ────
    // Без /api/ai (старая сборка или не перезапущенный сервер) показываем
    // фактическое состояние локальной модели из /api/health и честно
    // объясняем, почему настройки ключа тут нет.
    const fallbackNote =
      support === "restart-required"
        ? t("Сервер ZERE старее панели: закройте и снова запустите ZERE — появится настройка облачного ключа.")
        : t("Настройка облачного ключа появится после перезапуска ZERE; пока работает локальная модель (Ollama).");

    const aiCard = card(
      t("ИИ и модель"),
      h(
        "div",
        { class: "update-section" },
        h(
          "div",
          { class: "pill-row" },
          statusPill({
            label: t("ИИ"),
            value: ai
              ? ai.summary
              : health.ollama === "ok"
                ? t("Подключено: локальная модель · {model}", { model: config.model })
                : t("Локальная модель недоступна"),
            state: ai
              ? ai.activeProvider === "none"
                ? "danger"
                : "ok"
              : health.ollama === "ok"
                ? "ok"
                : "danger",
          }),
          statusPill({
            label: t("Режим"),
            value: ai ? ai.mode : t("только локальная модель"),
            state: "idle",
          }),
        ),
        h("p", {
          class: "panel-note",
          text: ai ? ai.message : fallbackNote,
        }),
        ai && !ai.ready && ai.local.installHint
          ? h(
              "div",
              { class: "code-line" },
              h("code", { text: ai.local.installHint.command }),
            )
          : null,
        h(
          "div",
          { class: "pill-row" },
          support === "unsupported"
            ? badge(t("Настройка ключа — после перезапуска ZERE"), "plain")
            : button(t("Настроить ИИ"), () => navigate("/ai"), "primary"),
        ),
      ),
    );
    aiCard.classList.add("col-12");

    const metricsCard = card(t("Метрики"), metrics);
    metricsCard.classList.add("col-6");

    eventsCard.classList.add("col-6");

    const actionsCard = card(
      t("Быстрые действия"),
      h(
        "div",
        { class: "pill-row" },
        button(t("Настройки"), () => navigate("/settings")),
        button(t("Личности"), () => navigate("/personalities")),
      ),
    );
    actionsCard.classList.add("col-12");

    const updateCard = card(
      t("Обновления"),
      h(
        "div",
        { class: "update-section" },
        h(
          "div",
          { class: "pill-row" },
          statusPill({
            label: t("Статус"),
            value: update?.updateAvailable
              ? t("+{count} коммитов", { count: update.behind })
              : t("актуальная версия"),
            state: update?.updateAvailable ? "warn" : "ok",
          }),
          statusPill({
            label: t("Ветка"),
            value: update ? `${update.remote}/${update.branch}` : health.branch,
            state: "idle",
          }),
        ),
        h(
          "div",
          { class: "pill-row" },
          button(t("Открыть обновления"), () => navigate("/update")),
        ),
      ),
    );
    updateCard.classList.add("col-12");

    body.appendChild(statusesCard);
    body.appendChild(aiCard);
    body.appendChild(metricsCard);
    body.appendChild(eventsCard);
    body.appendChild(actionsCard);
    body.appendChild(updateCard);

    renderEvents();
  }

  function renderError(error: unknown): void {
    clear(body);

    const message = error instanceof Error ? error.message : t("Неизвестная ошибка");
    body.appendChild(
      h(
        "div",
        { class: "col-12" },
        emptyState({
          icon: "⚠️",
          title: t("Не удалось загрузить статусы"),
          hint: message,
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      ),
    );
  }

  async function load(): Promise<void> {
    clear(body);
    body.appendChild(h("div", { class: "col-12" }, loadingRow(t("Опрос сервисов…"))));

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
