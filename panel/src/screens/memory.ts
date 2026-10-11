/**
 * Экран «Память» (этап 3 плана, §6): таблица воспоминаний, серверный
 * поиск (`?search=` в GET /api/memory), фильтр по источнику (категории
 * берутся из данных, не хардкодятся), добавление/правка через модалку
 * и удаление с подтверждением (P0-3: сервер отдаёт 404 без id).
 */

import { ApiError, apiDelete, apiGet, apiPost, type MemoryItem, type MemoryList } from "../api";
import { logEvent } from "../events";
import { t } from "../i18n";
import {
  badge,
  button,
  clear,
  confirmDialog,
  emptyState,
  field,
  h,
  skeleton,
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
    placeholder: t("Поиск по ключу и значению…"),
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
    options: [{ value: "", label: t("Все источники") }],
    onChange: (value) => {
      category = value;
      render();
    },
  });

  const addButton = button(t("Добавить запись"), () => openEditor(null), "primary", "plus");

  container.appendChild(
    pageHeader(
      t("Память"),
      t("Факты, которые ZERE запомнил о вас: вручную и извлечённые автоматически"),
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
    list.appendChild(skeleton("table", 6));

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

      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      errorBox.textContent = message;
      errorBox.hidden = false;
      all = [];
      clear(list);
      list.appendChild(
        emptyState({
          icon: "alert",
          title: t("Не удалось загрузить память"),
          hint: message,
          action: { label: t("Повторить"), onClick: () => void load() },
        }),
      );
      countLabel.textContent = "";
      toast(t("Ошибка загрузки памяти"), "danger");
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
      { value: "", label: t("Все источники") },
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
          icon: "memory",
          title: search || category ? t("Ничего не найдено") : t("Память пуста"),
          hint:
            search || category
              ? t("Измените запрос или фильтр источника.")
              : t("Добавьте запись вручную или попросите ZERE что-нибудь запомнить."),
          action:
            search || category
              ? undefined
              : { label: t("Добавить запись"), onClick: () => openEditor(null) },
        }),
      );
      countLabel.textContent = t("записей: {count}", { count: all.length });
      return;
    }

    countLabel.textContent =
      rows.length === all.length
        ? t("записей: {count}", { count: all.length })
        : t("найдено {shown} из {total}", { shown: rows.length, total: all.length });

    list.appendChild(memoryTable(rows));
  }

  function memoryTable(rows: MemoryItem[]): HTMLElement {
    const head = h(
      "thead",
      {},
      h(
        "tr",
        {},
        h("th", { text: t("Ключ") }),
        h("th", { text: t("Значение") }),
        h("th", { text: t("Источник") }),
        h("th", { text: t("Создано") }),
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
            button(t("Изменить"), () => openEditor(item)),
            button(t("Удалить"), () => void remove(item), "danger", "trash"),
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

    const keyInput = textInput({ value: item?.key ?? "", placeholder: t("например: любимый язык") });
    const valueInput = textInput({ value: item?.value ?? "", placeholder: t("например: Python") });
    // Ключ менять нельзя: POST — upsert по ключу, иначе осталась бы старая запись.
    keyInput.disabled = !isNew;

    const known = Array.from(new Set(all.map((entry) => entry.category)));
    if (isNew && !known.includes(DEFAULT_CATEGORY)) known.push(DEFAULT_CATEGORY);

    const categoryPicker = select({
      value: item?.category ?? DEFAULT_CATEGORY,
      options: known.map((value) => ({ value, label: value })),
    });

    const dialog = modal({
      title: isNew ? t("Новая запись памяти") : t("Изменить запись"),
      body: h(
        "div",
        { class: "form-grid form-grid--single" },
        field(
          t("Ключ"),
          keyInput,
          isNew ? undefined : t("Ключ — идентификатор записи, он не меняется"),
        ),
        field(t("Значение"), valueInput),
        field(
          t("Источник"),
          categoryPicker,
          t("«User» — записано вручную, иное — извлечено из диалога"),
        ),
        errorEl,
      ),
      actions: [
        { label: t("Отмена"), onClick: () => close() },
        {
          label: t("Сохранить"),
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
        validateField(t("ключ"), key, MAX_KEY) ??
        validateField(t("значение"), value, MAX_VALUE) ??
        validateField(t("источник"), selectedCategory, MAX_CATEGORY);

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
        toast(isNew ? t("Запись добавлена") : t("Запись обновлена"), "ok");
        logEvent(`Память: ${isNew ? "добавлена" : "обновлена"} запись «${saved.key}»`);
        await load();
      } catch (error) {
        if (cancelled) return;

        const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
        errorEl.textContent = message;
        errorEl.hidden = false;
        toast(t("Не удалось сохранить запись"), "danger");
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
      title: t("Удалить запись из памяти?"),
      message: t("Ключ: «{key}» · значение: «{value}». Действие необратимо.", {
        key: item.key,
        value: item.value,
      }),
      confirmLabel: t("Удалить"),
    });

    if (!confirmed) {
      toast(t("Удаление отменено"), "plain");
      logEvent(`Память: удаление «${item.key}» отклонено пользователем`);
      return;
    }

    try {
      await apiDelete(`/api/memory/${item.id}`);

      if (cancelled) return;

      toast(t("Запись «{key}» удалена", { key: item.key }), "ok");
      logEvent(`Память: удалена запись «${item.key}»`);
      await load();
    } catch (error) {
      if (cancelled) return;

      const message = error instanceof ApiError ? error.message : t("Неизвестная ошибка");
      toast(t("Не удалось удалить запись: {message}", { message }), "danger");
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
    if (!value.trim()) return t("Поле «{name}» не может быть пустым.", { name });
    if (value.length > max) return t("Поле «{name}» длиннее {max} символов.", { name, max });
    return null;
  }

  function formatDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }
};
