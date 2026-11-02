/**
 * Оболочка экрана (§5.3): сайдбар, шапка, контент, статус-строка.
 *
 * Здесь живут два «живых» элемента панели:
 *  - переезжающий индикатор активного пункта (один элемент на всю навигацию,
 *    поэтому переход читается как движение, а не как мигание подсветки);
 *  - орб ассистента — состояние ZERE одним взглядом (покой, слушает, думает,
 *    говорит, нет связи).
 */

import { onLangChange, t } from "./i18n";
import { icon, type IconName } from "./icons";
import { h, iconButton, orb, type OrbState } from "./ui";

export interface NavItem {
  path: string;
  icon: IconName;
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
      { path: "/", icon: "dashboard", label: "Главная страница" },
      { path: "/ai", icon: "ai", label: "Подключение ИИ" },
      { path: "/chat", icon: "chat", label: "Чат" },
      { path: "/history", icon: "history", label: "История" },
      { path: "/memory", icon: "memory", label: "Память" },
    ],
  },
  {
    label: "Система",
    items: [
      { path: "/voice", icon: "voice", label: "Голос" },
      { path: "/processes", icon: "processes", label: "Процессы" },
      { path: "/apps", icon: "apps", label: "Приложения" },
      { path: "/folders", icon: "folders", label: "Папки" },
      { path: "/plugins", icon: "plugins", label: "Плагины" },
      { path: "/logs", icon: "logs", label: "Логи" },
    ],
  },
  {
    label: "Панель",
    items: [
      { path: "/settings", icon: "settings", label: "Настройки" },
      { path: "/update", icon: "update", label: "Обновления" },
      { path: "/personalities", icon: "personalities", label: "Личности" },
    ],
  },
];

/** Строка состояния службы в подвале: цвет точки несёт смысл. */
export interface StatusItem {
  text: string;
  state?: "ok" | "warn" | "danger" | "live" | "idle";
}

export interface ShellOptions {
  /** Вызов командной палитры (Ctrl+K и кнопка поиска в шапке). */
  onOpenPalette: () => void;
}

export interface ShellInstance {
  /** Область экрана (роутер монтирует сюда). */
  content: HTMLElement;
  /** Правая часть статус-строки (ветка/версия). */
  statusRight: HTMLElement;
  /** Хост для Toast-уведомлений. */
  toastHost: HTMLElement;
  /** Кнопка переключения темы в шапке. */
  themeButton: HTMLButtonElement;
  /** Заголовок шапки (роутер обновляет). */
  setTitle(title: string): void;
  /** Подзаголовок шапки: зачем этот экран. */
  setSubtitle(subtitle: string): void;
  /** Службы слева в статус-строке. */
  setStatuses(items: StatusItem[]): void;
  /** Состояние ассистента на орбе. */
  setAssistantState(state: OrbState, label?: string): void;
  /** Активный пункт навигации (роутер обновляет). */
  setActive(path: string): void;
  /** Показать/скрыть пункт меню: экраны, которых нет в редакции, не мозолят глаза. */
  setNavVisible(path: string, visible: boolean): void;
  /** Версия ZERE у знака в сайдбаре. */
  setVersion(version: string): void;
}

type SidebarPref = "wide" | "rail";

const SIDEBAR_KEY = "zere-sidebar";

function readSidebarPref(): SidebarPref {
  try {
    return window.localStorage.getItem(SIDEBAR_KEY) === "rail" ? "rail" : "wide";
  } catch {
    return "wide"; // приватный режим браузера — просто широкая панель
  }
}

export function createShell(
  onNavigate: (path: string) => void,
  options: ShellOptions,
): ShellInstance {
  const navButtons = new Map<string, HTMLButtonElement>();

  // Привязки строк к языку (этап 5, i18n): при смене языка перерисовываем.
  const langBindings: Array<() => void> = [];

  // ── Сайдбар ───────────────────────────────────────────────────

  const brandMark = h("span", { class: "sidebar__brand-glyph" });
  brandMark.appendChild(icon("brand", { size: 18 }));

  const brandVersion = h("span", { class: "sidebar__brand-version", text: "" });

  const sidebar = h(
    "aside",
    { class: "sidebar" },
    h(
      "div",
      { class: "sidebar__brand" },
      brandMark,
      h("span", { class: "sidebar__brand-name", text: "ZERE" }),
      brandVersion,
    ),
  );

  const nav = h("nav", { class: "sidebar__nav", ariaLabel: t("Разделы панели") });
  const rail = h("span", { class: "sidebar__rail" });
  nav.appendChild(rail);

  for (const group of NAV_GROUPS) {
    const groupLabel = h("div", { class: "sidebar__group-label", text: t(group.label) });
    langBindings.push(() => {
      groupLabel.textContent = t(group.label);
    });
    nav.appendChild(groupLabel);

    for (const item of group.items) {
      const labelEl = h("span", { class: "nav-item__label", text: t(item.label) });
      const iconEl = h("span", { class: "nav-item__icon" });
      iconEl.appendChild(icon(item.icon, { size: 18 }));

      const buttonEl = h(
        "button",
        {
          class: "nav-item",
          type: "button",
          title: t(item.label),
          onclick: () => onNavigate(item.path),
        },
        iconEl,
        labelEl,
      );
      buttonEl.dataset.label = t(item.label);

      langBindings.push(() => {
        labelEl.textContent = t(item.label);
        buttonEl.title = t(item.label);
        buttonEl.dataset.label = t(item.label);
      });

      navButtons.set(item.path, buttonEl);
      nav.appendChild(buttonEl);
    }
  }

  sidebar.appendChild(nav);

  // ── Сворачивание в рейку ──────────────────────────────────────
  // Узкий экран всегда показывает рейку: широкая панель на 390px съела бы
  // половину ширины и дала бы горизонтальное переполнение.

  const narrow = window.matchMedia("(max-width: 1100px)");
  let sidebarPref = readSidebarPref();
  let activeButton: HTMLButtonElement | null = null;

  const sidebarToggle = iconButton("sidebar", t("Свернуть панель"), () => {
    const next: SidebarPref = sidebarPref === "rail" ? "wide" : "rail";
    sidebarPref = next;
    try {
      window.localStorage.setItem(SIDEBAR_KEY, next);
    } catch {
      // Настройка необязательная: без localStorage рейка просто не запомнится.
    }
    applySidebar();
  });

  function railActive(): boolean {
    return sidebarPref === "rail" || narrow.matches;
  }

  function applySidebar(): void {
    const railMode = railActive();
    sidebar.classList.toggle("sidebar--rail", railMode);
    sidebarToggle.title = railMode ? t("Развернуть панель") : t("Свернуть панель");
    sidebarToggle.setAttribute("aria-label", sidebarToggle.title);
    railUpdate();
  }

  /** Переезд индикатора к активному пункту: считаем от позиции кнопки. */
  function railUpdate(): void {
    const target = activeButton;
    if (!target || target.hidden) {
      rail.classList.remove("sidebar__rail--ready");
      return;
    }

    rail.style.setProperty("--rail-y", `${target.offsetTop + 7}px`);
    rail.style.setProperty("--rail-h", `${Math.max(target.offsetHeight - 14, 14)}px`);
    rail.classList.add("sidebar__rail--ready");
  }

  narrow.addEventListener("change", applySidebar);
  // Ширина сайдбара анимируется — после перехода позиции кнопок меняются.
  sidebar.addEventListener("transitionend", (event) => {
    if (event.propertyName === "width") railUpdate();
  });
  window.addEventListener("resize", railUpdate);

  const sidebarFoot = h(
    "div",
    { class: "sidebar__foot" },
    sidebarToggle,
  );
  sidebar.appendChild(sidebarFoot);

  // ── Шапка ─────────────────────────────────────────────────────

  const titleEl = h("h1", { class: "shell__title", text: t("Главная страница") });
  const subtitleEl = h("p", { class: "shell__subtitle", text: "" });

  const searchButton = h(
    "button",
    { class: "shell__search", type: "button", onclick: () => options.onOpenPalette() },
    icon("search", { size: 15 }),
    h("span", { class: "shell__search-text", text: t("Поиск и команды") }),
    h("kbd", { text: "Ctrl K" }),
  );

  const themeButton = h("button", {
    class: "btn btn--ghost btn--icon btn--theme",
    type: "button",
    ariaLabel: t("Переключить тему"),
  });
  langBindings.push(() => {
    themeButton.ariaLabel = t("Переключить тему");
  });

  const header = h(
    "header",
    { class: "shell__header" },
    h("div", { class: "shell__heading" }, titleEl, subtitleEl),
    h(
      "div",
      { class: "shell__header-actions" },
      searchButton,
      themeButton,
    ),
  );

  // ── Орб и статус-строка ───────────────────────────────────────

  const orbEl = orb("idle", { label: t("Состояние ассистента") });
  const statusLeft = h("div", { class: "shell__status-left" });
  const statusRight = h("span", { class: "shell__status-right", text: "" });
  // Орб вне контейнера служб: `setStatuses` перерисовывает только список,
  // поэтому лицо ассистента не мигает при каждом опросе состояния.
  const statusLead = h("div", { class: "shell__status-lead" }, orbEl, statusLeft);

  const status = h(
    "footer",
    { class: "shell__status", ariaLabel: t("Состояние служб") },
    statusLead,
    statusRight,
  );

  const content = h("main", { class: "shell__content" });

  const main = h("div", { class: "shell__main" }, header, content, status);
  const shellEl = h("div", { class: "shell" }, sidebar, main);

  const app = document.getElementById("app");
  if (!app) throw new Error("#app не найден");

  app.appendChild(shellEl);
  applySidebar();

  const toastHost = h("div", { class: "toast-host" });
  document.body.appendChild(toastHost);

  // Смена языка (этап 5): обновляем подписи оболочки на месте.
  onLangChange(() => {
    for (const apply of langBindings) apply();
    railUpdate();
  });

  return {
    content,
    statusRight,
    toastHost,
    themeButton,
    setTitle(title: string): void {
      // Перезапускаем вход заголовка: смена экрана должна читаться.
      titleEl.textContent = title;
      titleEl.style.animation = "none";
      void titleEl.offsetWidth;
      titleEl.style.animation = "";
    },
    setSubtitle(subtitle: string): void {
      subtitleEl.textContent = subtitle;
    },
    setStatuses(items: StatusItem[]): void {
      while (statusLeft.firstChild) statusLeft.removeChild(statusLeft.firstChild);

      for (const item of items) {
        const el = h("span", { class: "shell__status-item", text: item.text });
        if (item.state) el.dataset.state = item.state;
        statusLeft.appendChild(el);
      }
    },
    setAssistantState(state: OrbState, label?: string): void {
      orbEl.className = `orb orb--${state}`;
      if (label) {
        orbEl.title = label;
        orbEl.setAttribute("aria-label", label);
      }
    },
    setActive(path: string): void {
      for (const [itemPath, buttonEl] of navButtons) {
        const active = itemPath === path;
        buttonEl.classList.toggle("nav-item--active", active);
        if (active) activeButton = buttonEl;
      }
      railUpdate();
    },
    setNavVisible(path: string, visible: boolean): void {
      const buttonEl = navButtons.get(path);
      if (buttonEl) buttonEl.hidden = !visible;
      railUpdate();
    },
    setVersion(version: string): void {
      brandVersion.textContent = version ? `v${version}` : "";
    },
  };
}
