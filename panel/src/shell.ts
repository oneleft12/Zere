/**
 * Оболочка экрана (§5.3): сайдбар 220px, шапка, контент, статус-строка.
 */

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

  const sidebar = h("aside", { class: "sidebar" });
  sidebar.appendChild(
    h(
      "div",
      { class: "sidebar__brand" },
      h("span", { class: "sidebar__brand-glyph", text: "◈" }),
      h("span", { text: "JARVIS" }),
    ),
  );

  const nav = h("nav", { class: "sidebar__nav" });

  for (const group of NAV_GROUPS) {
    nav.appendChild(h("div", { class: "sidebar__group-label", text: group.label }));

    for (const item of group.items) {
      const buttonEl = h(
        "button",
        {
          class: "nav-item",
          type: "button",
          title: item.label,
          onclick: () => onNavigate(item.path),
        },
        h("span", { class: "nav-item__icon", text: item.icon }),
        h("span", { class: "nav-item__label", text: item.label }),
      );

      navButtons.set(item.path, buttonEl);
      nav.appendChild(buttonEl);
    }
  }

  sidebar.appendChild(nav);

  const titleEl = h("h1", { class: "shell__title", text: "Дашборд" });
  const themeButton = h("button", {
    class: "btn btn--ghost",
    type: "button",
    ariaLabel: "Переключить тему",
    text: "☾",
  });

  const header = h(
    "header",
    { class: "shell__header" },
    titleEl,
    h("div", { class: "shell__header-actions" }, themeButton),
  );

  const content = h("main", { class: "shell__content" });

  const statusLeft = h("span", { class: "shell__status-item", text: "● статусы…" });
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
