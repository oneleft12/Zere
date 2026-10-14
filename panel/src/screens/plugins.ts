/**
 * Экран «Плагины» (этап 4, §6): read-only список загруженных плагинов
 * и честный флаг P1-3 — `handlersConnected` показывает, подключены ли
 * плагины-обработчики к конвейеру именно этой сборки (в Python-редакции
 * подключены, во внешней — нет). Выключателей нет: панель не соврёт
 * про управление, которого пока не существует.
 */

import { ApiError, apiGet, type PluginList } from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  button,
  card,
  clear,
  emptyState,
  h,
  keyValue,
  skeleton,
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
  const refreshButton = button(t("Обновить"), () => void load(), "default", "refresh");

  container.appendChild(
    pageHeader(
      t("Плагины"),
      t("Только просмотр: включение обработчиков возможно после починки P1-3"),
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
    body.appendChild(skeleton("card", 3));

    try {
      const data = await apiGet<PluginList>("/api/plugins");

      if (cancelled) return;
      render(data);
    } catch (error) {
      if (cancelled) return;

      // Сообщение ошибки приходит с сервера — его не переводим.
      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      clear(body);
      body.appendChild(
        emptyState({
          icon: "alert",
          title: t("Не удалось загрузить плагины"),
          hint: message,
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
      toast(t("Ошибка загрузки плагинов"), "danger");
      logEvent(`Ошибка плагинов: ${message}`);
    } finally {
      loading = false;
      refreshButton.disabled = false;
    }
  }

  function render(data: PluginList): void {
    clear(body);

    const personality = data.activePersonality
      ? `${data.activePersonality.id} · ${data.activePersonality.style}`
      : "—";

    // Подсказка зависит от флага: при подключённых обработчиках объяснять
    // «почему не работает» нечего, а молчать про неработающие — нельзя.
    const handlersNote = data.handlersConnected
      ? h("p", { class: "panel-note", text: t(
        "Плагины-обработчики подключены к конвейеру: их команды работают. "
        + "Внешние плагины кладутся в ./plugins/*.py и загружаются при старте.",
      ) })
      : h("p", { class: "panel-note", text: t(
        "handlersConnected=false — плагины-обработчики этой сборки не подключены "
        + "к конвейеру: они видны в списке, но команд не получают. "
        + "Переключатели появятся после P1-3.",
      ) });

    const summary = card(
      t("Состояние"),
      h(
        "div",
        { class: "pill-row" },
        badge(
          t(data.handlersConnected ? "обработчики подключены: да" : "обработчики подключены: нет"),
          data.handlersConnected ? "ok" : "warn",
        ),
        badge(t("командных обработчиков: {count}", { count: data.commandHandlersCount }), "plain"),
        badge(t("личность: {value}", { value: personality }), "accent"),
      ),
      handlersNote,
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
            icon: "plugins",
            title: t("Плагины не найдены"),
            hint: t("PluginManager не загрузил ни встроенного, ни внешнего плагина."),
          }),
        ),
      );
    } else {
      for (const plugin of data.items) {
        // Имя, описание и метаданные плагина приходят с сервера — не переводим.
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
            { key: t("Версия"), value: plugin.version },
            { key: t("Автор"), value: plugin.author },
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
