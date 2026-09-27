/**
 * Экран «История» (этап 3 плана, §6): лента диалогов, серверный поиск
 * (`?search=` в GET /api/history), пагинация, экспорт в JSON и очистка
 * с явным подтверждением (P0-3: сервер тоже требует confirm=DELETE).
 */

import { ApiError, apiDelete, apiGet, type HistoryItem, type HistoryPage } from "../api";
import { logEvent } from "../events";
import {
  button,
  clear,
  confirmDialog,
  emptyState,
  h,
  loadingRow,
  pageHeader,
  textInput,
  toast,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

const PAGE_SIZE = 20;
const EXPORT_PAGE_SIZE = 500; // серверный максимум limit
const EXPORT_MAX_PAGES = 20; // страховка от бесконечного цикла
const SEARCH_DEBOUNCE_MS = 300;

export const historyScreen: ScreenFactory = (container): Cleanup => {
  let offset = 0;
  let search = "";
  let total = 0;
  let pageItems = 0;
  let cancelled = false;
  let loading = false;
  let searchTimer = 0;

  const countLabel = h("span", { class: "history__count" });

  const searchInput = textInput({
    value: "",
    placeholder: "Поиск по вопросам и ответам…",
    onInput: (value) => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        if (value === search) return;
        search = value;
        offset = 0;
        void load();
      }, SEARCH_DEBOUNCE_MS);
    },
  });

  const exportButton = button("Экспорт JSON", () => void exportHistory());
  const clearButton = button("Очистить", () => void clearHistory(), "danger");

  const list = h("div", { class: "history-list" });
  const pager = h("div", { class: "history__pager" });
  const errorBox = h("div", { class: "form-error", hidden: true });

  const prevButton = button("← Назад", () => {
    offset = Math.max(0, offset - PAGE_SIZE);
    void load();
  });

  const nextButton = button("Вперёд →", () => {
    offset += PAGE_SIZE;
    void load();
  });

  container.appendChild(
    pageHeader(
      "История",
      "Сохранённые пары «вопрос → ответ»; очистка требует подтверждения",
      [clearButton, exportButton],
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
  container.appendChild(pager);

  void load();

  // ── Управление элементами ──────────────────────────────────────

  function updateControls(): void {
    prevButton.disabled = loading || offset <= 0;
    nextButton.disabled = loading || offset + pageItems >= total;
    exportButton.disabled = loading || total === 0;
    clearButton.disabled = loading || total === 0;
  }

  function renderPager(): void {
    clear(pager);
    pager.append(
      prevButton,
      h("span", {
        class: "history__pos",
        text: total === 0 ? "0 записей" : `${offset + 1}–${offset + pageItems} из ${total}`,
      }),
      nextButton,
    );
    updateControls();
  }

  // ── Загрузка и рендер ──────────────────────────────────────────

  async function load(): Promise<void> {
    if (loading) return;
    loading = true;
    errorBox.hidden = true;
    updateControls();

    clear(list);
    list.appendChild(loadingRow("Загрузка истории…"));

    try {
      const page = await apiGet<HistoryPage>(buildPath(offset, search));

      if (cancelled) return;

      total = page.total;
      render(page.items);
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
      errorBox.textContent = message;
      errorBox.hidden = false;
      pageItems = 0;
      countLabel.textContent = "";
      clear(list);
      list.appendChild(
        emptyState({
          icon: "⚠️",
          title: "Не удалось загрузить историю",
          hint: message,
          action: { label: "Повторить", onClick: () => void load() },
        }),
      );
      renderPager();
      toast("Ошибка загрузки истории", "danger");
      logEvent(`Ошибка истории: ${message}`);
    } finally {
      loading = false;
      updateControls();
    }
  }

  function render(items: HistoryItem[]): void {
    pageItems = items.length;
    clear(list);

    if (items.length === 0) {
      list.appendChild(
        emptyState({
          icon: "🗂",
          title: search ? "Ничего не найдено" : "История пуста",
          hint: search
            ? `По запросу «${search}» совпадений нет.`
            : "Диалоги начнут появляться здесь после первых сообщений в чате.",
        }),
      );
    } else {
      for (const item of items) {
        list.appendChild(conversationCard(item));
      }
    }

    const from = total === 0 ? 0 : offset + 1;
    const to = offset + pageItems;
    countLabel.textContent = search
      ? `найдено ${total} · показано ${from}–${to}`
      : `записей: ${total} · показано ${from}–${to}`;

    renderPager();
  }

  function conversationCard(item: HistoryItem): HTMLElement {
    return h(
      "article",
      { class: "conv fade-in" },
      h("div", { class: "conv__role conv__role--user", text: "Вы" }),
      h("p", { class: "conv__text", text: item.userMessage }),
      h("div", { class: "conv__role conv__role--ai", text: "JARVIS" }),
      h("p", { class: "conv__text", text: item.jarvisResponse }),
      h("div", { class: "conv__meta", text: formatTimestamp(item.timestamp) }),
    );
  }

  // ── Действия ───────────────────────────────────────────────────

  async function clearHistory(): Promise<void> {
    const confirmed = await confirmDialog({
      title: "Очистить историю?",
      message: `Будет удалено записей: ${total}. Отменить это действие будет невозможно.`,
      confirmLabel: "Удалить историю",
    });

    if (!confirmed) {
      toast("Очистка истории отменена", "plain");
      logEvent("Очистка истории отклонена пользователем");
      return;
    }

    try {
      const result = await apiDelete<{ deleted: number }>("/api/history", { confirm: "DELETE" });

      if (cancelled) return;

      toast(`История очищена — удалено записей: ${result.deleted}`, "ok");
      logEvent(`История очищена: удалено ${result.deleted}`);
      offset = 0;
      await load();
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
      toast(`Не удалось очистить историю: ${message}`, "danger");
      logEvent(`Ошибка очистки истории: ${message}`);
    }
  }

  async function exportHistory(): Promise<void> {
    exportButton.disabled = true;

    try {
      const items = await fetchAll();

      if (cancelled) return;

      downloadJson(`jarvis-history-${dateStamp()}.json`, {
        exportedAt: new Date().toISOString(),
        search,
        total: items.length,
        items,
      });

      toast(`Экспортировано записей: ${items.length}`, "ok");
      logEvent(`Экспорт истории: ${items.length} записей`);
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
      toast(`Экспорт не удался: ${message}`, "danger");
      logEvent(`Ошибка экспорта истории: ${message}`);
    } finally {
      updateControls();
    }
  }

  /** Выгружает все страницы (limit ≤ 500 на запрос), а не только видимую. */
  async function fetchAll(): Promise<HistoryItem[]> {
    const items: HistoryItem[] = [];

    for (let page = 0; page < EXPORT_MAX_PAGES; page += 1) {
      const data = await apiGet<HistoryPage>(buildPath(items.length, search, EXPORT_PAGE_SIZE));
      items.push(...data.items);

      if (data.items.length < EXPORT_PAGE_SIZE || items.length >= data.total) break;
    }

    return items;
  }

  function buildPath(pageOffset: number, query: string, limit = PAGE_SIZE): string {
    const params = new URLSearchParams({ limit: String(limit), offset: String(pageOffset) });
    if (query) params.set("search", query);
    return `/api/history?${params.toString()}`;
  }

  return () => {
    cancelled = true;
    window.clearTimeout(searchTimer);
  };

  // ── Утилиты ────────────────────────────────────────────────────

  function formatTimestamp(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function dateStamp(): string {
    const now = new Date();
    const pad = (part: number): string => String(part).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  }

  function downloadJson(filename: string, payload: unknown): void {
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = h("a", { href: url, text: "" });
    link.setAttribute("download", filename);
    document.body.appendChild(link);
    link.click();
    link.remove();
    // Отозвать сразу можно оборвать загрузку в некоторых браузерах.
    window.setTimeout(() => URL.revokeObjectURL(url), 4000);
  }
};
