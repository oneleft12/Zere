/**
 * Экран «Память» (этап 3 плана, §6): таблица воспоминаний, серверный
 * поиск (`?search=` в GET /api/memory), фильтр по источнику (категории
 * берутся из данных, не хардкодятся), добавление/правка через модалку
 * и удаление с подтверждением (P0-3: сервер отдаёт 404 без id).
 */

import { ApiError, apiDelete, apiGet, apiPost, type MemoryItem, type MemoryList } from "../api";
import { logEvent } from "../events";
import {
  badge,
  button,
  clear,
  confirmDialog,
  emptyState,
  field,
  h,
  loadingRow,
  modal,
  pageHeader,
  select,
  textInput,
  toast,
} from "../ui";
import type { Cleanup, ScreenFactory } from "../router";

// Лимиты контракта (docs/api/openapi.yaml → MemoryCreateRequest).
const MAX_KEY = 200;
const MAX_VALUE = 2000;
const MAX_CATEGORY = 100;
const DEFAULT_CATEGORY = "User";
const SEARCH_DEBOUNCE_MS = 300;

export const memoryScreen: ScreenFactory = (container): Cleanup => {
  let all: MemoryItem[] = [];
  let search = "";
  let category = "";
  let loading = false;
  let cancelled = false;
  let searchTimer = 0;
  let openDialog: HTMLElement | null = null;
  let closeOpenDialog: (() => void) | null = null;

  const countLabel = h("span", { class: "history__count" });
  const errorBox = h("div", { class: "form-error", hidden: true });
  const list = h("div", { class: "table-wrap" });

  const searchInput = textInput({
    value: "",
    placeholder: "Поиск по ключу и значению…",
    onInput: (value) => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        if (value === search) return;
        search = value;
        void load();
      }, SEARCH_DEBOUNCE_MS);
    },
  });

  // Источник — это категория из данных; «User» присутствует по контракту.
  const categorySelect = select({
    value: "",
    options: [{ value: "", label: "Все источники" }],
    onChange: (value) => {
      category = value;
      render();
    },
  });

  const addButton = button("Добавить запись", () => openEditor(null), "primary");

  container.appendChild(
    pageHeader(
      "Память",
      "Факты, которые JARVIS запомнил о вас: вручную и извлечённые автоматически",
      [addButton],
    ),
  );

  container.appendChild(
    h(
      "div",
      { class: "history__toolbar" },
      h("div", { class: "history__search" }, searchInput),
      categorySelect,
      countLabel,
    ),
  );

  container.appendChild(errorBox);
  container.appendChild(list);

  void load();

  // ── Данные ─────────────────────────────────────────────────────

  async function load(): Promise<void> {
    if (loading) return;
    loading = true;
    errorBox.hidden = true;
    addButton.disabled = true;

    clear(list);
    list.appendChild(loadingRow("Загрузка памяти…"));

    try {
      const data = await apiGet<MemoryList>(
        search ? `/api/memory?search=${encodeURIComponent(search)}` : "/api/memory",
      );

      if (cancelled) return;

      all = data.items;
      syncCategoryFilter();
      render();
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
      errorBox.textContent = message;
      errorBox.hidden = false;
      all = [];
      clear(list);
      list.appendChild(
        emptyState({
          icon: "⚠️",
          title: "Не удалось загрузить память",
          hint: message,
          action: { label: "Повторить", onClick: () => void load() },
        }),
      );
      countLabel.textContent = "";
      toast("Ошибка загрузки памяти", "danger");
      logEvent(`Ошибка памяти: ${message}`);
    } finally {
      loading = false;
      addButton.disabled = false;
    }
  }

  /** Фильтр источников строится из фактических категорий — без хардкода. */
  function syncCategoryFilter(): void {
    const present = Array.from(new Set(all.map((item) => item.category))).sort();
    if (category && !present.includes(category)) category = "";

    const options = [
      { value: "", label: "Все источники" },
      ...present.map((value) => ({ value, label: value })),
    ];

    categorySelect.replaceChildren(...options.map((option) => {
      const el = h("option", { value: option.value, text: option.label });
      if (option.value === category) el.selected = true;
      return el;
    }));
    categorySelect.value = category;
  }

  function visible(): MemoryItem[] {
    return category ? all.filter((item) => item.category === category) : all;
  }

  function render(): void {
    const rows = visible();
    clear(list);

    if (rows.length === 0) {
      list.appendChild(
        emptyState({
          icon: "🧠",
          title: search || category ? "Ничего не найдено" : "Память пуста",
          hint:
            search || category
              ? "Измените запрос или фильтр источника."
              : "Добавьте запись вручную или попросите JARVIS что-нибудь запомнить.",
          action:
            search || category
              ? undefined
              : { label: "Добавить запись", onClick: () => openEditor(null) },
        }),
      );
      countLabel.textContent = `записей: ${all.length}`;
      return;
    }

    countLabel.textContent =
      rows.length === all.length
        ? `записей: ${all.length}`
        : `найдено ${rows.length} из ${all.length}`;

    list.appendChild(memoryTable(rows));
  }

  function memoryTable(rows: MemoryItem[]): HTMLElement {
    const head = h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", { text: "Ключ" }),
        h("th", { text: "Значение" }),
        h("th", { text: "Источник" }),
        h("th", { text: "Создано" }),
        h("th", { text: "" }),
      ),
    );

    const body = h(
      "tbody",
      {},
      ...rows.map((item) =>
        h(
          "tr",
          {},
          h("td", { class: "table--mono", text: item.key }),
          h("td", { text: item.value }),
          h("td", {}, badge(item.category, item.category === DEFAULT_CATEGORY ? "accent" : "plain")),
          h("td", { class: "table--mono", text: formatDate(item.createdAt) }),
          h(
            "td",
            { class: "mem-table__actions" },
            button("Изменить", () => openEditor(item)),
            button("Удалить", () => void remove(item), "danger"),
          ),
        ),
      ),
    );

    return h("table", { class: "table" }, head, body);
  }

  // ── Редактор (добавление / правка) ─────────────────────────────

  function openEditor(item: MemoryItem | null): void {
    if (openDialog) return;

    const isNew = item === null;
    const errorEl = h("div", { class: "form-error", hidden: true });

    const keyInput = textInput({ value: item?.key ?? "", placeholder: "например: любимый язык" });
    const valueInput = textInput({ value: item?.value ?? "", placeholder: "например: Python" });
    // Ключ менять нельзя: POST — upsert по ключу, иначе осталась бы старая запись.
    keyInput.disabled = !isNew;

    const known = Array.from(new Set(all.map((entry) => entry.category)));
    if (isNew && !known.includes(DEFAULT_CATEGORY)) known.push(DEFAULT_CATEGORY);

    const categoryPicker = select({
      value: item?.category ?? DEFAULT_CATEGORY,
      options: known.map((value) => ({ value, label: value })),
    });

    const dialog = modal({
      title: isNew ? "Новая запись памяти" : "Изменить запись",
      body: h(
        "div",
        { class: "form-grid form-grid--single" },
        field("Ключ", keyInput, isNew ? undefined : "Ключ — идентификатор записи, он не меняется"),
        field("Значение", valueInput),
        field("Источник", categoryPicker, "«User» — записано вручную, иное — извлечено из диалога"),
        errorEl,
      ),
      actions: [
        { label: "Отмена", onClick: () => close() },
        {
          label: "Сохранить",
          variant: "primary",
          onClick: () => void save(),
        },
      ],
      onClose: () => close(),
    });

    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") close();
    };

    function close(): void {
      if (openDialog !== dialog) return;
      openDialog = null;
      closeOpenDialog = null;
      document.removeEventListener("keydown", onKey);
      dialog.remove();
    }

    async function save(): Promise<void> {
      const key = keyInput.value.trim();
      const value = valueInput.value;
      const selectedCategory = categoryPicker.value.trim();

      const problem =
        validateField("ключ", key, MAX_KEY) ??
        validateField("значение", value, MAX_VALUE) ??
        validateField("источник", selectedCategory, MAX_CATEGORY);

      if (problem) {
        errorEl.textContent = problem;
        errorEl.hidden = false;
        return;
      }

      errorEl.hidden = true;

      try {
        const saved = await apiPost<MemoryItem>("/api/memory", {
          key,
          value,
          category: selectedCategory,
        });

        if (cancelled) return;

        close();
        toast(isNew ? "Запись добавлена" : "Запись обновлена", "ok");
        logEvent(`Память: ${isNew ? "добавлена" : "обновлена"} запись «${saved.key}»`);
        await load();
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
        errorEl.textContent = message;
        errorEl.hidden = false;
        toast("Не удалось сохранить запись", "danger");
        logEvent(`Ошибка сохранения памяти: ${message}`);
      }
    }

    document.addEventListener("keydown", onKey);
    document.body.appendChild(dialog);
    openDialog = dialog;
    closeOpenDialog = close;
    (isNew ? keyInput : valueInput).focus();
  }

  // ── Удаление ───────────────────────────────────────────────────

  async function remove(item: MemoryItem): Promise<void> {
    const confirmed = await confirmDialog({
      title: "Удалить запись из памяти?",
      message: `Ключ: «${item.key}» · значение: «${item.value}». Действие необратимо.`,
      confirmLabel: "Удалить",
    });

    if (!confirmed) {
      toast("Удаление отменено", "plain");
      logEvent(`Память: удаление «${item.key}» отклонено пользователем`);
      return;
    }

    try {
      await apiDelete(`/api/memory/${item.id}`);

      if (cancelled) return;

      toast(`Запись «${item.key}» удалена`, "ok");
      logEvent(`Память: удалена запись «${item.key}»`);
      await load();
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : "Неизвестная ошибка";
      toast(`Не удалось удалить запись: ${message}`, "danger");
      logEvent(`Ошибка удаления памяти: ${message}`);
    }
  }

  return () => {
    cancelled = true;
    window.clearTimeout(searchTimer);
    closeOpenDialog?.(); // снимаем модалку и её слушатель Escape
  };

  // ── Утилиты ────────────────────────────────────────────────────

  function validateField(name: string, value: string, max: number): string | null {
    if (!value.trim()) return `Поле «${name}» не может быть пустым.`;
    if (value.length > max) return `Поле «${name}» длиннее ${max} символов.`;
    return null;
  }

  function formatDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }
};
