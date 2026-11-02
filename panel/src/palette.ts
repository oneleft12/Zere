/**
 * Командная палитра (Ctrl+K): один вход ко всему, что умеет панель.
 *
 * Панель выросла до четырнадцати экранов, и «куда нажать» стало дороже, чем
 * само действие. Палитра решает это одним полем: экраны, действия панели и
 * команды ZERE ищутся набором букв, выполняются Enter.
 *
 * Клавиатура первична: ↑/↓ выбор, Enter выполнить, Esc закрыть,
 * фокус возвращается на элемент, который палитру открыл.
 */

import { COMMAND_GROUPS } from "./commands";
import { t } from "./i18n";
import { icon, type IconName } from "./icons";
import { clear, h } from "./ui";
import { NAV_GROUPS } from "./shell";
import { navigate } from "./router";
import { currentTheme, toggleTheme } from "./theme";
import { logEvent } from "./events";

interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
  icon: IconName;
  group: string;
  run: () => void;
}

let open = false;

/** Команду из палитры подставляет чат (состояние диалога живёт в нём). */
type Prefill = (text: string) => void;

let prefill: Prefill | null = null;

/** Чат регистрирует здесь способ подстановки команды в поле ввода. */
export function registerChatPrefill(fn: Prefill): void {
  prefill = fn;
}

function buildItems(): PaletteItem[] {
  const items: PaletteItem[] = [];

  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      items.push({
        id: `go:${item.path}`,
        label: t(item.label),
        hint: t("Перейти на экран"),
        icon: item.icon,
        group: t("Перейти"),
        run: () => navigate(item.path),
      });
    }
  }

  items.push({
    id: "act:theme",
    label: currentTheme() === "dark" ? t("Светлая тема") : t("Тёмная тема"),
    hint: t("Оформление панели"),
    icon: currentTheme() === "dark" ? "sun" : "moon",
    group: t("Действия"),
    run: () => {
      const next = toggleTheme();
      logEvent(`Тема переключена: ${next === "dark" ? "тёмная" : "светлая"}`);
    },
  });

  items.push({
    id: "act:update",
    label: t("Проверить обновления ZERE"),
    hint: t("Ветка, коммиты, применение"),
    icon: "update",
    group: t("Действия"),
    run: () => navigate("/update"),
  });

  for (const group of COMMAND_GROUPS) {
    for (const item of group.items) {
      items.push({
        id: `cmd:${item.command}`,
        label: item.command,
        hint: t(item.hint),
        icon: "chat",
        group: t("Команды ZERE"),
        run: () => {
          prefill?.(item.command);
          navigate("/chat");
        },
      });
    }
  }

  return items;
}

/** Подстрочный поиск: «кмир» находит «Открыть память» не хуже прямого. */
function matches(item: PaletteItem, query: string): boolean {
  if (!query) return true;

  const haystack = `${item.label} ${item.hint ?? ""} ${item.group}`.toLowerCase();
  if (haystack.includes(query)) return true;

  // Последовательность символов: прощает пропущенные буквы.
  let index = 0;
  for (const char of haystack) {
    if (char === query[index]) index += 1;
    if (index === query.length) return true;
  }
  return false;
}

export function openPalette(): void {
  if (open) return;
  open = true;

  const previouslyFocused =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;

  const allItems = buildItems();
  let items = allItems;
  let selected = 0;

  const list = h("ul", { class: "palette__list", role: "listbox" });
  const empty = h("div", { class: "palette__empty", text: t("Ничего не найдено"), hidden: true });

  const input = h("input", {
    type: "text",
    placeholder: t("Экран, действие или команда ZERE…"),
    ariaLabel: t("Поиск по панели"),
  });

  const panel = h(
    "div",
    { class: "palette", role: "dialog", ariaLabel: t("Палитра команд") },
    h("div", { class: "palette__search" }, icon("search", { size: 17 }), input, h("kbd", { text: "Esc" })),
    list,
    empty,
    h(
      "div",
      { class: "palette__foot" },
      h("span", {}, h("kbd", { text: "↑ ↓" }), h("span", { text: t("выбор") })),
      h("span", {}, h("kbd", { text: "Enter" }), h("span", { text: t("выполнить") })),
    ),
  );
  panel.setAttribute("aria-modal", "true");

  const backdrop = h("div", {
    class: "palette-backdrop",
    onclick: (event) => {
      if (event.target === backdrop) close();
    },
  });
  backdrop.appendChild(panel);

  function render(): void {
    clear(list);
    empty.hidden = items.length > 0;

    if (items.length === 0) return;

    selected = Math.min(selected, items.length - 1);

    let lastGroup = "";
    items.forEach((item, index) => {
      if (item.group !== lastGroup) {
        lastGroup = item.group;
        list.appendChild(h("li", { class: "palette__group", text: item.group }));
      }

      const button = h(
        "button",
        {
          class: "palette__item",
          type: "button",
          role: "option",
          onclick: () => run(index),
        },
        icon(item.icon, { size: 17 }),
        h("span", { text: item.label }),
        item.hint ? h("span", { class: "palette__hint", text: item.hint }) : undefined,
      );

      button.dataset.selected = String(index === selected);
      // Стабильный идентификатор пункта: за него держатся e2e-сценарии
      // и он не зависит от языка интерфейса.
      button.dataset.id = item.id;
      list.appendChild(h("li", {}, button));
    });
  }

  function scrollToSelected(): void {
    const el = list.querySelector<HTMLElement>('[data-selected="true"]');
    el?.scrollIntoView({ block: "nearest" });
  }

  function run(index: number): void {
    const item = items[index];
    if (!item) return;
    close();
    item.run();
  }

  function close(): void {
    if (!open) return;
    open = false;
    document.removeEventListener("keydown", onKey, true);
    backdrop.remove();
    previouslyFocused?.focus();
  }

  function onKey(event: KeyboardEvent): void {
    if (!backdrop.isConnected) return;

    switch (event.key) {
      case "Escape":
        event.preventDefault();
        close();
        return;
      case "ArrowDown":
        event.preventDefault();
        selected = items.length === 0 ? 0 : (selected + 1) % items.length;
        render();
        scrollToSelected();
        return;
      case "ArrowUp":
        event.preventDefault();
        selected = items.length === 0 ? 0 : (selected - 1 + items.length) % items.length;
        render();
        scrollToSelected();
        return;
      case "Enter":
        event.preventDefault();
        run(selected);
        return;
      default:
        return;
    }
  }

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    items = allItems.filter((item) => matches(item, query));
    // Точное совпадение начала строки поднимаем наверх: Enter без стрелок.
    if (query) {
      items.sort((a, b) => {
        const aStart = a.label.toLowerCase().startsWith(query) ? 0 : 1;
        const bStart = b.label.toLowerCase().startsWith(query) ? 0 : 1;
        return aStart - bStart;
      });
    }
    selected = 0;
    render();
  });

  document.addEventListener("keydown", onKey, true);
  document.body.appendChild(backdrop);

  render();
  input.focus();
}

/** Глобальный ярлык: Ctrl+K (Cmd+K на macOS). */
export function initPalette(): void {
  document.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() !== "k" || !(event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    if (open) return;
    openPalette();
  });
}
