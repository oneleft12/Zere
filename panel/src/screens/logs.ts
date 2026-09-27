/**
 * Экран «Логи» (этап 4, §6): чтение logs/*.log через GET /api/logs —
 * фильтр по уровню, пагинация, без изменения файлов. Сырые исключения
 * сюда не попадают: API отдаёт нормализованные записи {time, level, message, source}.
 */

import { ApiError, apiGet, type LogEntry, type LogLevel, type LogList } from "../api";
import { logEvent } from "../events";
import {
  badge,
  button,
  clear,
  emptyState,
  h,
  loadingRow,
  pageHeader,
  select,
  toast,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

const PAGE_SIZE = 50;
const LEVEL_TONE: Record<LogLevel, "plain" | "warn" | "danger"> = {
  info: "plain",
  warn: "warn",
  error: "danger",
};

export const logsScreen: ScreenFactory = (container): Cleanup => {
  let offset = 0;
  let level: LogLevel | "" = "";
  let total = 0;
  let pageItems = 0;
  let cancelled = false;
  let loading = false;

  const countLabel = h("span", { class: "history__count" });
  const errorBox = h("div", { class: "form-error", hidden: true });
  const list = h("div", { class: "logs-list" });
  const pager = h("div", { class: "history__pager" });

  const levelSelect = select({
    value: "",
    options: [
      { value: "", label: "Все уровни" },
      { value: "info", label: "info" },
      { value: "warn", label: "warn" },
      { value: "error", label: "error" },
    ],
    onChange: (value) => {
      level = value as LogLevel | "";
      offset = 0;
      void load();
    },
  });

  const refreshButton = button("Обновить", () => void load());

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
      "Логи",
      "Файлы logs/*.log в обратном порядке: новые сверху; сбой показывается здесь, не в UI",
      [refreshButton],
    ),
  );

  container.appendChild(
    h(
      "div",
      { class: "history__toolbar" },
      h("div", { class: "history__search" }, levelSelect),
      countLabel,
    ),
  );

  container.appendChild(errorBox);
  container.appendChild(list);
  container.appendChild(pager);

  void load();

  function updateControls(): void {
    prevButton.disabled = loading || offset <= 0;
    nextButton.disabled = loading || offset + pageItems >= total;
    refreshButton.disabled = loading;
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

  // ── Загрузка ───────────────────────────────────────────────────

  async function load(): Promise<void> {
    if (loading) return;
    loading = true;
    errorBox.hidden = true;
    updateControls();

    clear(list);
    list.appendChild(loadingRow("Чтение логов…"));

    try {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
      if (level) params.set("level", level);

      const data = await apiGet<LogList>(`/api/logs?${params.toString()}`);

      if (cancelled) return;

      total = data.total;
      render(data.items);
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
          title: "Не удалось прочитать логи",
          hint: message,
          action: { label: "Повторить", onClick: () => void load() },
        }),
      );
      renderPager();
      toast("Ошибка чтения логов", "danger");
      logEvent(`Ошибка логов: ${message}`);
    } finally {
      loading = false;
      updateControls();
    }
  }

  function render(items: LogEntry[]): void {
    pageItems = items.length;
    clear(list);

    if (items.length === 0) {
      list.appendChild(
        emptyState({
          icon: "📄",
          title: "Записей нет",
          hint: level
            ? `Уровня «${level}» в логах нет.`
            : "Логи появятся после первых событий панели и ассистента.",
        }),
      );
    } else {
      for (const entry of items) list.appendChild(entryRow(entry));
    }

    const from = total === 0 ? 0 : offset + 1;
    const to = offset + pageItems;
    countLabel.textContent = level
      ? `${level}: ${total} · показано ${from}–${to}`
      : `записей: ${total} · показано ${from}–${to}`;

    renderPager();
  }

  function entryRow(entry: LogEntry): HTMLElement {
    return h(
      "div",
      { class: "log-entry fade-in" },
      h("span", { class: "log-entry__time", text: entry.time }),
      badge(entry.level, LEVEL_TONE[entry.level]),
      entry.source ? badge(entry.source, "accent") : null,
      h("span", { class: "log-entry__message", text: entry.message }),
    );
  }

  return () => {
    cancelled = true;
  };
};
