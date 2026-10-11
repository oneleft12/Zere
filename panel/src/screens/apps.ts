/**
 * Экран «Приложения» (этап 4, §6): индекс установленных приложений
 * (поиск ?q) и переиндексация с отчётом «сколько найдено за сколько».
 */

import { ApiError, apiGet, apiPost, type AppList, type AppReindexResponse } from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  button,
  clear,
  emptyState,
  h,
  skeleton,
  pageHeader,
  textInput,
  toast,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

const SEARCH_DEBOUNCE_MS = 300;
const MAX_QUERY = 100; // серверный лимит параметра q

export const appsScreen: ScreenFactory = (container): Cleanup => {
  let query = "";
  let total = 0;
  let cancelled = false;
  let loading = false;
  let busy = false;
  let searchTimer = 0;

  const countLabel = h("span", { class: "history__count" });
  const errorBox = h("div", { class: "form-error", hidden: true });
  const list = h("div", { class: "table-wrap" });

  const searchInput = textInput({
    value: "",
    placeholder: t("Поиск по имени или алиасу…"),
    onInput: (value) => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        const next = value.slice(0, MAX_QUERY);
        if (next === query) return;
        query = next;
        void load();
      }, SEARCH_DEBOUNCE_MS);
    },
  });

  const reindexButton = button(t("Переиндексировать"), () => void reindex(), "primary", "refresh");

  container.appendChild(
    pageHeader(
      t("Приложения"),
      t("Индекс сканеров (реестр, меню «Пуск», AppPaths, LocalAppData) для голосового запуска"),
      [reindexButton],
    ),
  );

  container.appendChild(
    h(
      "div",
      { class: "history__toolbar" },
      h("div", { class: "history__search" }, searchInput),
      countLabel,
    ),
  );

  container.appendChild(errorBox);
  container.appendChild(list);

  void load();

  function updateControls(): void {
    reindexButton.disabled = loading || busy;
  }

  // ── Загрузка ───────────────────────────────────────────────────

  async function load(): Promise<void> {
    if (loading) return;
    loading = true;
    errorBox.hidden = true;
    updateControls();

    clear(list);
    list.appendChild(skeleton("table", 6));

    try {
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      const data = await apiGet<AppList>(`/api/apps?${params.toString()}`);

      if (cancelled) return;
      render(data.items, data.total);
    } catch (error) {
      if (cancelled) return;

      // Сообщение ошибки приходит с сервера — его не переводим.
      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      errorBox.textContent = message;
      errorBox.hidden = false;
      total = 0;
      countLabel.textContent = "";
      clear(list);
      list.appendChild(
        emptyState({
          icon: "alert",
          title: t("Не удалось загрузить приложения"),
          hint: message,
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
      toast(t("Ошибка загрузки приложений"), "danger");
      logEvent(`Ошибка приложений: ${message}`);
    } finally {
      loading = false;
      updateControls();
    }
  }

  function render(items: AppList["items"], serverTotal: number): void {
    total = serverTotal;
    clear(list);

    if (items.length === 0) {
      list.appendChild(
        emptyState({
          icon: "plugins",
          title: query ? t("Ничего не найдено") : t("Индекс пуст"),
          hint: query
            ? t("По запросу «{query}» совпадений нет.", { query })
            : t("Нажмите «Переиндексировать», чтобы сканеры собрали установленные приложения."),
          action: query ? undefined : { label: t("Переиндексировать"), onClick: () => void reindex() },
        }),
      );
      countLabel.textContent = t("приложений: {count}", { count: 0 });
      return;
    }

    list.appendChild(buildTable(items));

    countLabel.textContent = query
      ? t("найдено {count} по «{query}» из {total}", { count: items.length, query, total })
      : t("приложений: {count}", { count: total });
  }

  function buildTable(items: AppList["items"]): HTMLElement {
    const head = h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", { text: t("Название") }),
        h("th", { text: t("Категория") }),
        h("th", { text: t("Сканер") }),
        h("th", { text: t("Приоритет") }),
        h("th", { text: t("Алиасы") }),
        h("th", { text: t("Путь") }),
      ),
    );

    const body = h(
      "tbody",
      {},
      ...items.map((item) =>
        h(
          "tr",
          {},
          h("td", { text: item.name }),
          h("td", {}, badge(item.category || "—", item.category ? "accent" : "plain")),
          h("td", { text: item.source }),
          h("td", { class: "table--mono", text: String(item.priority) }),
          h("td", { text: item.aliases.length > 0 ? item.aliases.join(", ") : "—" }),
          h("td", { class: "table--mono", text: item.executablePath }),
        ),
      ),
    );

    return h("table", { class: "table" }, head, body);
  }

  // ── Переиндексация ──────────────────────────────────────────────

  async function reindex(): Promise<void> {
    if (busy) return;

    busy = true;
    updateControls();

    try {
      const result = await apiPost<AppReindexResponse>("/api/apps/reindex", {});

      if (cancelled) return;

      toast(t("Найдено приложений: {count} за {ms} мс", { count: result.count, ms: result.durationMs }), "ok");
      logEvent(`Индекс приложений обновлён: ${result.count} за ${result.durationMs} мс`);
      await load();
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      toast(t("Переиндексация не удалась: {message}", { message }), "danger");
      logEvent(`Ошибка переиндексации: ${message}`);
    } finally {
      busy = false;
      updateControls();
    }
  }

  return () => {
    cancelled = true;
    window.clearTimeout(searchTimer);
  };
};
