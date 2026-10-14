/**
 * Экран «Плагины» (этап 4, §6): инвентарь загруженных плагинов, честный флаг
 * `handlersConnected` и — если бэкенд умеет (`GET /api/plugins/mcp`) — настройка
 * MCP-плагинов: выбор браузера для Playwright MCP и состояние серверов.
 *
 * Выбор браузера идёт тем же кодом, что команда «браузер выбери opera gx» в
 * чате (`PlaywrightMcpPlugin.select_browser`): правила одни, отказ плагина
 * показывается текстом как есть, выбор сохраняется в config/mcp.json.
 *
 * Маршрутов `/api/plugins/mcp*` в C#-редакции нет (там нет MCP-плагинов),
 * поэтому 404 — не ошибка: блок просто не рисуется.
 */

import {
  ApiError,
  apiGet,
  apiPost,
  type McpBrowserSelected,
  type McpPluginList,
  type McpPluginState,
  type PluginList,
} from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  button,
  card,
  clear,
  emptyState,
  field,
  h,
  keyValue,
  select,
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
  /** Последние ответы: по ним перерисовываем экран после выбора браузера. */
  let plugins: PluginList | null = null;
  let mcpState: McpPluginState[] | null = null;

  const body = h("div", {});
  const refreshButton = button(t("Обновить"), () => void load(), "default", "refresh");

  container.appendChild(
    pageHeader(
      t("Плагины"),
      t("Список плагинов; у MCP-плагинов настраивается браузер"),
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
      const mcp = await loadMcp();

      if (cancelled) return;
      plugins = data;
      mcpState = mcp;
      render(data, mcp);
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

  /** Состояние MCP-плагинов; `null` — бэкенд такого маршрута не имеет. */
  async function loadMcp(): Promise<McpPluginState[] | null> {
    try {
      const data = await apiGet<McpPluginList>("/api/plugins/mcp");

      return data.items;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;

      // Маршрут есть, но ответил ошибкой: не прячем молча — это видно в логе.
      logEvent(
        `MCP-плагины: ${error instanceof ApiError ? error.message : t("Неизвестная ошибка")}`,
      );

      return null;
    }
  }

  /** Выбор браузера: тот же путь, что у команды «браузер выбери …» в чате. */
  async function chooseBrowser(name: string, trigger: HTMLButtonElement): Promise<void> {
    trigger.disabled = true;

    try {
      const result = await apiPost<McpBrowserSelected>("/api/plugins/mcp/browser", {
        browser: name,
      });

      toast(result.message, "ok");
      logEvent(result.message);

      if (plugins !== null && !cancelled) {
        mcpState = result.items;
        render(plugins, result.items);
      }
    } catch (error) {
      // Отказ плагина («Opera GX не найден», «не знаю браузер») приходит
      // готовым русским текстом — показываем его, а не «ошибка 400».
      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      toast(message, "danger");
      logEvent(`Выбор браузера: ${message}`);

      // Отказ (браузер не найден) — состояние на сервере не изменилось:
      // перерисовываем, чтобы селект показывал реальный выбор, а не отклонённый.
      if (plugins !== null && !cancelled) render(plugins, mcpState);
    } finally {
      trigger.disabled = false;
    }
  }

  function browserCard(mcp: McpPluginState[]): HTMLElement | null {
    const plugin = mcp.find((item) => item.browser);

    if (!plugin || !plugin.browser) return null;

    const browser = plugin.browser;
    let chosen = browser.current;

    const control = select({
      value: browser.current,
      options: browser.options.map((option) => ({
        value: option.id,
        label: option.available
          ? option.label
          : t("{label} — не найден", { label: option.label }),
      })),
      onChange: (value) => {
        chosen = value;
      },
    });

    const apply = button(
      t("Выбрать браузер"),
      () => void chooseBrowser(chosen, apply),
      "primary",
    );

    const unavailable = browser.options.find((option) => option.id === browser.current);

    return card(
      t("Браузер для плагина MCP"),
      field(t("Браузер"), control, t("Выбор сохраняется и переживает перезапуск ZERE.")),
      h("div", { class: "pill-row" }, apply),
      keyValue([
        { key: t("Сейчас"), value: browser.currentLabel },
        {
          key: t("Запуск"),
          value: browser.channel
            ? t("канал Playwright: {channel}", { channel: browser.channel })
            : t("по пути к opera.exe"),
        },
        ...(browser.path ? [{ key: "browserPath", value: browser.path }] : []),
      ]),
      h("p", {
        class: "panel-note",
        text: unavailable && !unavailable.available && unavailable.hint
          ? unavailable.hint
          : t("То же делает команда «браузер выбери opera gx» в чате."),
      }),
    );
  }

  function mcpCard(mcp: McpPluginState[]): HTMLElement {
    const rows = mcp.map((item) =>
      keyValue([
        { key: item.serverId, value: item.command || t("не настроен в config/mcp.json") },
        {
          key: t("Состояние"),
          value: item.running
            ? t("сервер запущен")
            : item.enabled
              ? t("включён, сервер поднимется при первой команде")
              : t("выключен в config/mcp.json"),
        },
        ...(item.lastError ? [{ key: t("Последняя ошибка"), value: item.lastError }] : []),
      ]),
    );

    return card(t("MCP-серверы"), ...rows);
  }

  function render(data: PluginList, mcp: McpPluginState[] | null): void {
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
        + "к конвейеру: они видны в списке, но команд не получают.",
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

    // Настройка MCP: карточка браузера первой — её и открывают на этом экране.
    const browser = mcp ? browserCard(mcp) : null;

    if (browser) {
      browser.classList.add("col-6");
      grid.appendChild(browser);
    }

    if (mcp && mcp.length > 0) {
      const servers = mcpCard(mcp);
      servers.classList.add("col-6");
      grid.appendChild(servers);
    }

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
