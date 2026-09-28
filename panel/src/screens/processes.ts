/**
 * Экран «Процессы» (этап 4, §6): список с поиском (?q), завершение
 * процесса и команды питания. Любое необратимое действие — ConfirmDialog,
 * затем серверный двухшаг с ttlToken (P0-3: двойная защита — UI и сервер).
 */

import {
  ApiError,
  apiConfirm,
  apiGet,
  type KillResult,
  type PowerAction,
  type PowerResult,
  type ProcessInfo,
  type ProcessList,
} from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
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

const SEARCH_DEBOUNCE_MS = 300;
const MAX_QUERY = 100; // серверный лимит параметра q

// Русские строки POWER_LABELS переводятся в t() в местах использования:
// на верхнем уровне модуля язык ещё не инициализирован.
const POWER_LABELS: Record<PowerAction, { label: string; title: string; message: string; confirm: string }> = {
  shutdown: {
    label: "Выключение",
    title: "Выключить компьютер?",
    message: "Компьютер будет выключен. Несохранённые данные будут потеряны.",
    confirm: "Выключить",
  },
  restart: {
    label: "Перезагрузка",
    title: "Перезагрузить компьютер?",
    message: "Компьютер будет перезагружен. Несохранённые данные будут потеряны.",
    confirm: "Перезагрузить",
  },
  sleep: {
    label: "Сон",
    title: "Перевести в сон?",
    message: "Работа будет приостановлена до нажатия кнопки питания.",
    confirm: "В сон",
  },
};

export const processesScreen: ScreenFactory = (container): Cleanup => {
  let query = "";
  let total = 0;
  let cancelled = false;
  let loading = false;
  let busy = false; // kill/power в полёте — блокируем кнопки
  let searchTimer = 0;

  const countLabel = h("span", { class: "history__count" });
  const errorBox = h("div", { class: "form-error", hidden: true });
  const list = h("div", { class: "table-wrap" });

  const searchInput = textInput({
    value: "",
    placeholder: t("Поиск по имени процесса…"),
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

  const refreshButton = button(t("Обновить"), () => void load());
  const powerButtons: Array<{ action: PowerAction; el: HTMLButtonElement }> = (
    ["sleep", "restart", "shutdown"] as PowerAction[]
  ).map((action) => ({
    action,
    el: button(t(POWER_LABELS[action].label), () => void power(action), action === "sleep" ? "default" : "danger"),
  }));

  container.appendChild(
    pageHeader(
      t("Процессы"),
      t("Завершение и питание требуют подтверждения: ConfirmDialog, затем токен TTL 60 с"),
      [...powerButtons.map((p) => p.el), refreshButton],
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
    refreshButton.disabled = loading || busy;
    for (const { el } of powerButtons) el.disabled = loading || busy;
  }

  // ── Загрузка ───────────────────────────────────────────────────

  async function load(): Promise<void> {
    if (loading) return;
    loading = true;
    errorBox.hidden = true;
    updateControls();

    clear(list);
    list.appendChild(loadingRow(t("Загрузка процессов…")));

    try {
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      const data = await apiGet<ProcessList>(`/api/processes?${params.toString()}`);

      if (cancelled) return;
      render(data.items);
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
          icon: "⚠️",
          title: t("Не удалось загрузить процессы"),
          hint: message,
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
      toast(t("Ошибка загрузки процессов"), "danger");
      logEvent(`Ошибка процессов: ${message}`);
    } finally {
      loading = false;
      updateControls();
    }
  }

  function render(items: ProcessInfo[]): void {
    total = items.length;
    clear(list);

    if (items.length === 0) {
      list.appendChild(
        emptyState({
          icon: "🔍",
          title: query ? t("Ничего не найдено") : t("Процессы не найдены"),
          hint: query
            ? t("По запросу «{query}» совпадений нет.", { query })
            : t("Система не показала ни одного процесса."),
        }),
      );
      countLabel.textContent = t("процессов: {count}", { count: 0 });
      return;
    }

    list.appendChild(buildTable(items));

    const shown = query
      ? t("найдено {count} по «{query}»", { count: total, query })
      : t("процессов: {count}", { count: total });
    countLabel.textContent = `${shown} · ${t("память сверху")}`;
  }

  function buildTable(items: ProcessInfo[]): HTMLElement {
    const head = h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", { text: t("Имя") }),
        h("th", { text: "PID" }),
        h("th", { text: t("Память, МБ") }),
        h("th", { text: t("Отвечает") }),
        h("th", { text: t("Тип") }),
        h("th", { text: "" }),
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
          h("td", { class: "table--mono", text: String(item.pid) }),
          h("td", { class: "table--mono", text: String(Math.round(item.memoryMb)) }),
          h("td", {}, badge(item.responding ? t("да") : t("нет"), item.responding ? "ok" : "danger")),
          h(
            "td",
            {},
            item.protected ? badge(t("системный"), "warn") : badge(t("пользовательский"), "plain"),
          ),
          h(
            "td",
            { class: "row-actions" },
            button(
              t("Завершить"),
              () => void kill(item),
              "danger",
            ),
          ),
        ),
      ),
    );

    const tableEl = h("table", { class: "table" }, head, body);

    // Системные процессы завершать нельзя — и UI это показывает, и сервер
    // всё равно ответит 400 PROTECTED (двойная защита).
    const rows = tableEl.querySelectorAll<HTMLButtonElement>("tbody tr .row-actions .btn");
    items.forEach((item, index) => {
      if (item.protected && rows[index]) {
        rows[index].disabled = true;
        rows[index].title = t("Системный процесс — завершение запрещено");
      }
    });

    return tableEl;
  }

  // ── Завершение процесса ────────────────────────────────────────

  async function kill(item: ProcessInfo): Promise<void> {
    if (busy) return;

    if (item.protected) {
      toast(t("«{name}» — системный процесс, завершение запрещено", { name: item.name }), "warn");
      return;
    }

    const confirmed = await confirmDialog({
      title: t("Завершить «{name}»?", { name: item.name }),
      message: t("PID {pid} · память {mb} МБ. Процесс будет завершён принудительно.", {
        pid: item.pid,
        mb: Math.round(item.memoryMb),
      }),
      confirmLabel: t("Завершить процесс"),
    });

    if (!confirmed) {
      toast(t("Завершение процесса отменено"), "plain");
      logEvent(`Завершение процесса отклонено: ${item.name} (PID ${item.pid})`);
      return;
    }

    busy = true;
    updateControls();

    try {
      const result = await apiConfirm<KillResult>(`/api/processes/${item.pid}/kill`, "KILL");

      if (cancelled) return;

      toast(t("Процесс «{name}» (PID {pid}) завершён", { name: result.name, pid: result.pid }), "ok");
      logEvent(`Процесс завершён: ${result.name} (PID ${result.pid})`);
      await load();
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      toast(t("Не удалось завершить: {message}", { message }), "danger");
      logEvent(`Ошибка завершения процесса: ${message}`);
    } finally {
      busy = false;
      updateControls();
    }
  }

  // ── Команды питания ────────────────────────────────────────────

  async function power(action: PowerAction): Promise<void> {
    if (busy) return;

    const spec = POWER_LABELS[action];
    const confirmed = await confirmDialog({
      title: t(spec.title),
      message: t(spec.message),
      confirmLabel: t(spec.confirm),
    });

    if (!confirmed) {
      toast(t("Команда питания отменена"), "plain");
      logEvent(`Команда питания отклонена: ${action}`);
      return;
    }

    busy = true;
    updateControls();

    try {
      const result = await apiConfirm<PowerResult>(`/api/power/${action}`, "POWER");

      if (cancelled) return;

      if (result.status === "executed") {
        toast(t("Команда «{label}» выполнена", { label: t(spec.label) }), "ok");
        logEvent(`Питание выполнено: ${action}`);
      } else {
        toast(t("Команда «{label}» не выполнена", { label: t(spec.label) }), "danger");
        logEvent(`Питание не выполнено: ${action}`);
      }
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      toast(t("Ошибка команды питания: {message}", { message }), "danger");
      logEvent(`Ошибка питания (${action}): ${message}`);
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
