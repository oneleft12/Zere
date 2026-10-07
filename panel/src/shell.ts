/**
 * Оболочка экрана (§5.3): сайдбар 220px, шапка, контент, статус-строка.
 */

import { onLangChange, t } from "./i18n";
import { h } from "./ui";

export interface NavItem {
  path: string;
  icon: string;
  label: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

/** Полная навигация из §5.3; «soon»-экраны подключаются на этапах 3–4. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Ассистент",
    items: [
      { path: "/", icon: "🟠", label: "Дашборд" },
      { path: "/chat", icon: "💬", label: "Чат" },
      { path: "/history", icon: "🕘", label: "История" },
      { path: "/memory", icon: "🧠", label: "Память" },
    ],
  },
  {
    label: "Система",
    items: [
      { path: "/voice", icon: "🎙", label: "Голос" },
      { path: "/processes", icon: "⚙️", label: "Процессы" },
      { path: "/apps", icon: "📦", label: "Приложения" },
      { path: "/plugins", icon: "🧩", label: "Плагины" },
      { path: "/logs", icon: "📜", label: "Логи" },
    ],
  },
  {
    label: "Панель",
    items: [
      { path: "/settings", icon: "⚙", label: "Настройки" },
      { path: "/update", icon: "⬆", label: "Обновления" },
      { path: "/personalities", icon: "🎭", label: "Личности" },
    ],
  },
];

export interface ShellInstance {
  /** Область экрана (роутер монтирует сюда). */
  content: HTMLElement;
  /** Левая часть статус-строки (статусы сервисов). */
  statusLeft: HTMLElement;
  /** Правая часть статус-строки (ветка/версия). */
  statusRight: HTMLElement;
  /** Хост для Toast-уведомлений. */
  toastHost: HTMLElement;
  /** Кнопка переключения темы в шапке. */
  themeButton: HTMLButtonElement;
  /** Заголовок шапки (роутер обновляет). */
  setTitle(title: string): void;
  /** Активный пункт навигации (роутер обновляет). */
  setActive(path: string): void;
}

export function createShell(onNavigate: (path: string) => void): ShellInstance {
  const navButtons = new Map<string, HTMLButtonElement>();

  // Привязки строк к языку (этап 5, i18n): при смене языка перерисовываем.
  const langBindings: Array<() => void> = [];

  const sidebar = h("aside", { class: "sidebar" });
  sidebar.appendChild(
    h(
      "div",
      { class: "sidebar__brand" },
      h("span", { class: "sidebar__brand-glyph", text: "◈" }),
      h("span", { text: "ZERE" }),
    ),
  );

  const nav = h("nav", { class: "sidebar__nav" });

  for (const group of NAV_GROUPS) {
    const groupLabel = h("div", { class: "sidebar__group-label", text: t(group.label) });
    langBindings.push(() => {
      groupLabel.textContent = t(group.label);
    });
    nav.appendChild(groupLabel);

    for (const item of group.items) {
      const labelEl = h("span", { class: "nav-item__label", text: t(item.label) });
      const buttonEl = h(
        "button",
        {
          class: "nav-item",
          type: "button",
          title: t(item.label),
          onclick: () => onNavigate(item.path),
        },
        h("span", { class: "nav-item__icon", text: item.icon }),
        labelEl,
      );

      langBindings.push(() => {
        labelEl.textContent = t(item.label);
        buttonEl.title = t(item.label);
      });

      navButtons.set(item.path, buttonEl);
      nav.appendChild(buttonEl);
    }
  }

  sidebar.appendChild(nav);

  const titleEl = h("h1", { class: "shell__title", text: t("Дашборд") });
  const themeButton = h("button", {
    class: "btn btn--ghost",
    type: "button",
    ariaLabel: t("Переключить тему"),
    text: "☾",
  });
  langBindings.push(() => {
    themeButton.ariaLabel = t("Переключить тему");
  });

  const header = h(
    "header",
    { class: "shell__header" },
    titleEl,
    h("div", { class: "shell__header-actions" }, themeButton),
  );

  const content = h("main", { class: "shell__content" });

  const statusLeft = h("span", { class: "shell__status-item", text: t("● статусы…") });
  const statusRight = h("span", { class: "shell__status-item", text: "" });

  const status = h(
    "footer",
    { class: "shell__status" },
    statusLeft,
    statusRight,
  );

  const main = h(
    "div",
    { class: "shell__main" },
    header,
    content,
    status,
  );

  const shellEl = h("div", { class: "shell" }, sidebar, main);

  const app = document.getElementById("app");
  if (!app) throw new Error("#app не найден");

  app.appendChild(shellEl);

  const toastHost = h("div", { class: "toast-host" });
  document.body.appendChild(toastHost);

  // Смена языка (этап 5): обновляем подписи оболочки на месте.
  onLangChange(() => {
    for (const apply of langBindings) apply();
  });

  return {
    content,
    statusLeft,
    statusRight,
    toastHost,
    themeButton,
    setTitle(title: string): void {
      titleEl.textContent = title;
    },
    setActive(path: string): void {
      for (const [itemPath, buttonEl] of navButtons) {
        buttonEl.classList.toggle("nav-item--active", itemPath === path);
      }
    },
  };
}
