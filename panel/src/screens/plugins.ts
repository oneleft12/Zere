/**
 * Экран «Плагины» (этап 4, §6): read-only список загруженных плагинов
 * и честные флаги P1-3 — handlersConnected=false до починки PluginManager,
 * поэтому никаких выключателей: панель не соврёт про управление.
 */

import { ApiError, apiGet, type PluginList } from "../api";
import { logEvent } from "../events";
import {
  badge,
  button,
  card,
  clear,
  emptyState,
  h,
  keyValue,
  loadingRow,
  pageHeader,
  toast,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

const TYPE_TONE: Record<PluginList["items"][number]["type"], "accent" | "ok" | "warn" | "plain"> = {
  Personality: "accent",
  CommandHandler: "ok",
  MemoryProvider: "plain",
  VoiceEngine: "warn",
  Other: "plain",
};

export const pluginsScreen: ScreenFactory = (container): Cleanup => {
  let cancelled = false;
  let loading = false;

  const body = h("div", {});
  const refreshButton = button("Обновить", () => void load());

  container.appendChild(
    pageHeader(
      "Плагины",
      "Только просмотр: включение обработчиков возможно после починки P1-3",
      [refreshButton],
    ),
  );
  container.appendChild(body);

  void load();

  async function load(): Promise<void> {
    if (loading) return;
    loading = true;
    refreshButton.disabled = true;

    clear(body);
    body.appendChild(loadingRow("Загрузка плагинов…"));

    try {
      const data = await apiGet<PluginList>("/api/plugins");

      if (cancelled) return;
      render(data);
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
      clear(body);
      body.appendChild(
        emptyState({
          icon: "⚠️",
          title: "Не удалось загрузить плагины",
          hint: message,
          action: { label: "Повторить", onClick: () => void load() },
        }),
      );
      toast("Ошибка загрузки плагинов", "danger");
      logEvent(`Ошибка плагинов: ${message}`);
    } finally {
      loading = false;
      refreshButton.disabled = false;
    }
  }

  function render(data: PluginList): void {
    clear(body);

    const summary = card(
      "Состояние",
      h(
        "div",
        { class: "pill-row" },
        badge(
          `обработчики подключены: ${data.handlersConnected ? "да" : "нет"}`,
          data.handlersConnected ? "ok" : "warn",
        ),
        badge(`командных обработчиков: ${data.commandHandlersCount}`, "plain"),
        badge(
          `личность: ${data.activePersonality ? `${data.activePersonality.id} · ${data.activePersonality.style}` : "—"}`,
          "accent",
        ),
      ),
      h("p", { class: "panel-note", text:
        "handlersConnected=false — честный флаг этапа 4: пайплайн состоит из 9 "
        + "фиксированных обработчиков, PluginManager подключает только личности. "
        + "Переключатели появятся после P1-3.",
      }),
    );

    const grid = h("div", { class: "grid-12 fade-in" });
    summary.classList.add("col-6");
    grid.appendChild(summary);

    if (data.items.length === 0) {
      grid.appendChild(
        h(
          "div",
          { class: "col-12" },
          emptyState({
            icon: "🧩",
            title: "Плагины не найдены",
            hint: "PluginManager не загрузил ни встроенного, ни внешнего плагина.",
          }),
        ),
      );
    } else {
      for (const plugin of data.items) {
        const item = card(
          undefined,
          h(
            "div",
            { class: "plugin-card__head" },
            h("h3", { class: "card__title", text: plugin.name }),
            badge(plugin.type, TYPE_TONE[plugin.type]),
          ),
          h("p", { class: "panel-note", text: plugin.description }),
          keyValue([
            { key: "ID", value: plugin.id },
            { key: "Версия", value: plugin.version },
            { key: "Автор", value: plugin.author },
          ]),
        );
        item.classList.add("col-6");
        grid.appendChild(item);
      }
    }

    body.appendChild(grid);
  }

  return () => {
    cancelled = true;
  };
};
