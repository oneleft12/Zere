/**
 * Библиотека компонентов дизайн-системы ZERE (§5.3 плана).
 * Только textContent — никакой HTML-интерполяции (защита от XSS, P1-6).
 */

import { t } from "./i18n";
import { icon, type IconName } from "./icons";
import { countUp, reducedMotion } from "./motion";

export type Child = Node | string | number | null | undefined | Child[];

export interface Attrs {
  class?: string;
  text?: string;
  title?: string;
  type?: string;
  value?: string;
  placeholder?: string;
  min?: string | number;
  max?: string | number;
  step?: string | number;
  disabled?: boolean;
  checked?: boolean;
  hidden?: boolean;
  href?: string;
  role?: string;
  ariaLabel?: string;
  onclick?: (event: MouseEvent) => void;
  oninput?: (event: Event) => void;
  onchange?: (event: Event) => void;
  onkeydown?: (event: KeyboardEvent) => void;
  onsubmit?: (event: Event) => void;
}

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);

  if (attrs.class) el.className = attrs.class;
  if (attrs.text !== undefined) el.textContent = attrs.text;
  if (attrs.title) el.title = attrs.title;
  if (attrs.type) el.setAttribute("type", attrs.type);
  if (attrs.value !== undefined) (el as HTMLInputElement).value = attrs.value;
  if (attrs.placeholder) (el as HTMLInputElement).placeholder = attrs.placeholder;
  if (attrs.min !== undefined) (el as HTMLInputElement).min = String(attrs.min);
  if (attrs.max !== undefined) (el as HTMLInputElement).max = String(attrs.max);
  if (attrs.step !== undefined) (el as HTMLInputElement).step = String(attrs.step);
  if (attrs.disabled) (el as HTMLInputElement).disabled = true;
  if (attrs.checked) (el as HTMLInputElement).checked = true;
  if (attrs.hidden) el.hidden = true;
  if (attrs.href) el.setAttribute("href", attrs.href);
  if (attrs.role) el.setAttribute("role", attrs.role);
  if (attrs.ariaLabel) el.setAttribute("aria-label", attrs.ariaLabel);
  if (attrs.onclick) el.addEventListener("click", attrs.onclick as EventListener);
  if (attrs.oninput) el.addEventListener("input", attrs.oninput);
  if (attrs.onchange) el.addEventListener("change", attrs.onchange);
  if (attrs.onkeydown) el.addEventListener("keydown", attrs.onkeydown as EventListener);
  if (attrs.onsubmit) el.addEventListener("submit", attrs.onsubmit);

  append(el, children);
  return el;
}

function append(parent: Node, children: Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined) continue;
    if (Array.isArray(child)) {
      append(parent, child);
    } else if (child instanceof Node) {
      parent.appendChild(child);
    } else {
      parent.appendChild(document.createTextNode(String(child)));
    }
  }
}

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

// ── 1. Кнопка ────────────────────────────────────────────────────

export type ButtonVariant = "primary" | "ghost" | "danger" | "default";

export function button(
  label: string,
  onClick?: () => void,
  variant: ButtonVariant = "default",
  iconName?: IconName,
): HTMLButtonElement {
  const cls = variant === "default" ? "btn" : `btn btn--${variant}`;
  const el = h("button", {
    class: cls,
    text: iconName ? undefined : label,
    type: "button",
    onclick: onClick ? () => onClick() : undefined,
  });

  if (iconName) {
    el.appendChild(icon(iconName, { size: 16 }));
    el.appendChild(h("span", { text: label }));
  }

  return el;
}

/** Кнопка-иконка: подпись обязательна — она уходит в aria-label и title. */
export function iconButton(
  iconName: IconName,
  label: string,
  onClick?: () => void,
  variant: ButtonVariant = "ghost",
): HTMLButtonElement {
  const el = h("button", {
    class: `btn btn--${variant} btn--icon`,
    type: "button",
    title: label,
    ariaLabel: label,
    onclick: onClick ? () => onClick() : undefined,
  });
  el.appendChild(icon(iconName, { size: 17 }));
  return el;
}

/**
 * Дополняет готовую кнопку иконкой: направление («назад», «дальше») несёт
 * фигура, а не стрелка внутри подписи — подпись остаётся словом.
 */
export function withIcon(
  btn: HTMLButtonElement,
  iconName: IconName,
  flip = false,
): HTMLButtonElement {
  btn.insertBefore(icon(iconName, { size: 15, class: flip ? "icon--flip" : undefined }), btn.firstChild);
  return btn;
}

// ── 2. Карточка ──────────────────────────────────────────────────

export function card(title?: string, ...children: Child[]): HTMLElement {
  const el = h("section", { class: "card" });
  if (title) el.appendChild(h("h3", { class: "card__title", text: title }));
  append(el, children);
  return el;
}

// ── 3. StatusPill (§5.4) ─────────────────────────────────────────

export type PillState = "ok" | "warn" | "danger" | "idle";

export function statusPill(opts: {
  label: string;
  value: string;
  state: PillState;
  live?: boolean;
}): HTMLElement {
  const cls = ["status-pill", `status-pill--${opts.state}`];
  if (opts.live) cls.push("status-pill--live");

  return h(
    "div",
    { class: cls.join(" ") },
    h("span", { class: "status-pill__dot" }),
    h("span", { class: "status-pill__label", text: opts.label }),
    h("span", { class: "status-pill__value", text: opts.value }),
  );
}

// ── 4. Badge ─────────────────────────────────────────────────────

export function badge(text: string, tone: "plain" | "accent" | "ok" | "warn" | "danger" = "plain"): HTMLElement {
  const cls = tone === "plain" ? "badge" : `badge badge--${tone}`;
  return h("span", { class: cls, text });
}

// ── 5. Метрика ───────────────────────────────────────────────────

export function metric(value: string, label: string, hint?: string): HTMLElement {
  return h(
    "div",
    { class: "metric" },
    h("div", { class: "metric__value", text: value }),
    h("div", { class: "metric__label", text: label }),
    hint ? h("div", { class: "metric__hint", text: hint }) : undefined,
  );
}

/**
 * Метрика с досчётом: значение приходит из API готовым, поэтому переход
 * от нуля показывает, что цифра обновилась, а не мигнула подменой.
 */
export function metricAnimated(opts: {
  value: number;
  label: string;
  hint?: string;
  /** Как показать число (проценты, минуты, разряды). */
  format?: (value: number) => string;
}): HTMLElement {
  const format = opts.format ?? ((value: number) => String(Math.round(value)));
  const valueEl = h("div", { class: "metric__value", text: format(0) });

  const el = h(
    "div",
    { class: "metric" },
    valueEl,
    h("div", { class: "metric__label", text: opts.label }),
    opts.hint ? h("div", { class: "metric__hint", text: opts.hint }) : undefined,
  );

  // Досчёт запускаем, когда элемент уже в документе: иначе кадры уходят в пустоту.
  requestAnimationFrame(() => countUp(valueEl, opts.value, { format }));

  return el;
}

// ── 5a. Скелетон загрузки ────────────────────────────────────────

/** Форма будущих данных вместо пустоты: строки повторяют их силуэт. */
export function skeleton(kind: "card" | "table" | "list" = "list", rows = 4): HTMLElement {
  const stack = h("div", { class: "skeleton-stack" });

  if (kind === "card") {
    stack.appendChild(h("div", { class: "skeleton skeleton--title" }));
    for (let i = 0; i < rows; i += 1) stack.appendChild(h("div", { class: "skeleton" }));
    return stack;
  }

  if (kind === "table") {
    for (let i = 0; i < rows; i += 1) stack.appendChild(h("div", { class: "skeleton skeleton--row" }));
    return stack;
  }

  for (let i = 0; i < rows; i += 1) {
    const line = h("div", { class: "skeleton" });
    line.style.width = `${88 - i * 9}%`;
    stack.appendChild(line);
  }
  return stack;
}

// ── 5b. Орб ассистента ───────────────────────────────────────────

export type OrbState = "idle" | "listening" | "thinking" | "speaking" | "offline" | "error";

/** Состояние ассистента одной фигурой: кольца — это состояние, не декор. */
export function orb(state: OrbState, opts: { large?: boolean; label?: string } = {}): HTMLElement {
  const title = opts.label ?? t("Состояние ассистента");
  const el = h(
    "span",
    {
      class: `orb orb--${state}${opts.large ? " orb--lg" : ""}`,
      role: "img",
      ariaLabel: title,
      title,
    },
    h("span", { class: "orb__ring" }),
    h("span", { class: "orb__ring orb__ring--2" }),
    h("span", { class: "orb__core" }),
  );

  return el;
}

/** Меняет состояние уже смонтированного орба без перерисовки. */
export function setOrbState(el: HTMLElement, state: OrbState): void {
  el.className = el.className.replace(/orb--(idle|listening|thinking|speaking|offline|error)/, `orb--${state}`);
}



// ── 6. Поле формы ────────────────────────────────────────────────

export function field(label: string, control: Node, hint?: string): HTMLElement {
  const el = h(
    "label",
    { class: "field" },
    h("span", { class: "field__label", text: label }),
    control,
    hint ? h("span", { class: "field__hint", text: hint }) : null,
  );
  return el;
}

// ── 7. Текстовый ввод ────────────────────────────────────────────

export function textInput(opts: {
  value: string;
  onInput?: (value: string) => void;
  placeholder?: string;
  mono?: boolean;
  type?: string;
}): HTMLInputElement {
  const cls = opts.mono ? "input input--mono" : "input";
  return h("input", {
    class: cls,
    type: opts.type ?? "text",
    value: opts.value,
    placeholder: opts.placeholder ?? "",
    oninput: opts.onInput ? (e) => opts.onInput!((e.target as HTMLInputElement).value) : undefined,
  });
}

// ── 8. Селект ────────────────────────────────────────────────────

export function select(opts: {
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange?: (value: string) => void;
}): HTMLSelectElement {
  const el = h("select", {
    class: "select",
    onchange: opts.onChange ? (e) => opts.onChange!((e.target as HTMLSelectElement).value) : undefined,
  });

  for (const option of opts.options) {
    const opt = h("option", { value: option.value, text: option.label });
    if (option.value === opts.value) opt.selected = true;
    el.appendChild(opt);
  }

  return el;
}

// ── 9. Toggle ────────────────────────────────────────────────────

export function toggle(opts: {
  label: string;
  checked: boolean;
  onChange?: (checked: boolean) => void;
}): HTMLElement {
  const input = h("input", {
    type: "checkbox",
    checked: opts.checked,
    onchange: opts.onChange ? (e) => opts.onChange!((e.target as HTMLInputElement).checked) : undefined,
  });

  return h(
    "label",
    { class: "toggle" },
    input,
    h("span", { class: "toggle__track" }),
    h("span", { text: opts.label }),
  );
}

// ── 10. Slider ───────────────────────────────────────────────────

export function slider(opts: {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange?: (value: number) => void;
}): HTMLElement {
  const valueLabel = h("span", { class: "slider__value", text: format(opts.value) });

  const input = h("input", {
    class: "slider",
    type: "range",
    min: opts.min,
    max: opts.max,
    step: opts.step,
    value: String(opts.value),
    oninput: (e) => {
      const next = Number((e.target as HTMLInputElement).value);
      valueLabel.textContent = format(next);
      applyFill(input, next);
      opts.onChange?.(next);
    },
  });

  function format(v: number): string {
    return opts.step < 1 ? v.toFixed(2) : String(v);
  }

  /** Заливка трека до ползунка: доля видна без наведения на цифру. */
  function applyFill(el: HTMLInputElement, value: number): void {
    const ratio = (value - opts.min) / Math.max(opts.max - opts.min, Number.EPSILON);
    el.style.setProperty("--fill", `${Math.min(100, Math.max(0, ratio * 100))}%`);
  }

  applyFill(input, opts.value);

  return h("div", { class: "slider-row" }, input, valueLabel);
}

// ── 11. EmptyState ───────────────────────────────────────────────

export function emptyState(opts: {
  icon: IconName;
  title: string;
  hint?: string;
  action?: { label: string; onClick: () => void };
}): HTMLElement {
  const iconEl = h("div", { class: "empty-state__icon" });
  iconEl.appendChild(icon(opts.icon, { size: 26 }));

  return h(
    "div",
    { class: "empty-state" },
    iconEl,
    h("h3", { class: "empty-state__title", text: opts.title }),
    opts.hint ? h("p", { class: "empty-state__hint", text: opts.hint }) : undefined,
    opts.action
      ? h(
          "div",
          { class: "empty-state__action" },
          button(opts.action.label, opts.action.onClick, "primary"),
        )
      : undefined,
  );
}

// ── 12. Spinner / загрузка ───────────────────────────────────────

export function loadingRow(label = t("Загрузка…")): HTMLElement {
  return h(
    "div",
    { class: "loading-row" },
    h("span", { class: "spinner" }),
    h("span", { text: label }),
  );
}

// ── 13. Таблица ──────────────────────────────────────────────────

export interface Column<K extends string> {
  key: K;
  label: string;
}

export function table<K extends string>(
  columns: Array<Column<K>>,
  rows: Array<Record<K, string>>,
  opts: { mono?: boolean } = {},
): HTMLElement {
  const thead = h(
    "thead",
    {},
    h(
      "tr",
      {},
      ...columns.map((c) => h("th", { text: c.label })),
    ),
  );

  const tbody = h(
    "tbody",
    {},
    ...rows.map((row) =>
      h(
        "tr",
        {},
        ...columns.map((c) => h("td", { text: row[c.key] ?? "" })),
      ),
    ),
  );

  const cls = opts.mono ? "table table--mono" : "table";
  return h("table", { class: cls }, thead, tbody);
}

// ── 14. Модалка + ConfirmDialog ──────────────────────────────────

export function modal(opts: {
  title: string;
  body: Child;
  actions: Array<{ label: string; variant?: ButtonVariant; onClick: () => void }>;
  onClose: () => void;
}): HTMLElement {
  const previouslyFocused =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;

  const backdrop = h("div", {
    class: "modal-backdrop",
    onclick: (e) => {
      if (e.target === backdrop) opts.onClose();
    },
  });

  const dialog = h(
    "div",
    { class: "modal", role: "dialog", ariaLabel: opts.title },
    h("h2", { class: "modal__title", text: opts.title }),
    h("div", { class: "modal__body" }, opts.body),
    h(
      "div",
      { class: "modal__actions" },
      ...opts.actions.map((a) => button(a.label, a.onClick, a.variant ?? "default")),
    ),
  );
  dialog.setAttribute("aria-modal", "true");

  backdrop.appendChild(dialog);

  // ── Клавиатура (этап 5, §9 п.5): Escape закрывает, Tab ходит только
  // по модалке, фокус возвращается на элемент-источник после закрытия.

  const onKey = (event: KeyboardEvent): void => {
    if (!backdrop.isConnected) return;

    if (event.key === "Escape") {
      event.preventDefault();
      opts.onClose();
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), ' +
          'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );
    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    const inside = active instanceof Node && dialog.contains(active);

    if (event.shiftKey) {
      if (!inside || active === first) {
        event.preventDefault();
        last.focus();
      }
    } else if (!inside || active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  document.addEventListener("keydown", onKey, true);

  // Начальный фокус — только после вставки в DOM: вызывающий добавляет
  // модалку синхронно, поэтому кадр рисования достаточно.
  requestAnimationFrame(() => {
    if (!backdrop.isConnected || dialog.contains(document.activeElement)) return;
    const focusable = dialog.querySelector<HTMLElement>("button, input, select, textarea");
    focusable?.focus();
  });

  // Снятие слушателей и возврат фокуса, когда модалку удалили из DOM.
  const observer = new MutationObserver(() => {
    if (backdrop.isConnected) return;
    observer.disconnect();
    document.removeEventListener("keydown", onKey, true);
    previouslyFocused?.focus();
  });
  observer.observe(document.body, { childList: true, subtree: true });

  return backdrop;
}

/** ConfirmDialog: promise-обёртка над модалкой (этап 4 — необратимые действия). */
export function confirmDialog(opts: {
  title: string;
  message: string;
  confirmLabel?: string;
}): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;

    const finish = (result: boolean) => {
      if (settled) return;
      settled = true;
      backdrop.remove();
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish(false);
    };

    const backdrop = modal({
      title: opts.title,
      body: opts.message,
      actions: [
        { label: t("Отмена"), onClick: () => finish(false) },
        { label: opts.confirmLabel ?? t("Подтвердить"), variant: "danger", onClick: () => finish(true) },
      ],
      onClose: () => finish(false),
    });

    document.addEventListener("keydown", onKey);
    document.body.appendChild(backdrop);
  });
}

// ── 15. Toast ────────────────────────────────────────────────────

let toastHost: HTMLElement | null = null;

export function initToasts(host: HTMLElement): void {
  toastHost = host;
}

const TOAST_ICON = {
  plain: "info",
  ok: "check",
  warn: "alert",
  danger: "alert",
} satisfies Record<string, IconName>;

export function toast(message: string, tone: "plain" | "ok" | "warn" | "danger" = "plain"): void {
  if (!toastHost) return;

  const cls = tone === "plain" ? "toast" : `toast toast--${tone}`;
  const iconEl = h("span", { class: "toast__icon" });
  iconEl.appendChild(icon(TOAST_ICON[tone], { size: 16 }));

  const el = h(
    "div",
    { class: cls },
    iconEl,
    h("span", { class: "toast__text", text: message }),
  );

  toastHost.appendChild(el);

  // На экране живут последние четыре сообщения: остальные не копятся стеной.
  const overflow = Array.from(toastHost.children).slice(0, -4);
  for (const old of overflow) old.remove();

  const dismiss = (): void => {
    if (reducedMotion()) {
      el.remove();
      return;
    }

    el.classList.add("toast--leaving");
    el.addEventListener("animationend", () => el.remove(), { once: true });
    // Страховка: если анимация не доехала (вкладка была скрыта), убираем сами.
    window.setTimeout(() => el.remove(), 600);
  };

  window.setTimeout(dismiss, 4200);
}

// ── 16. Заголовок страницы ───────────────────────────────────────

export function pageHeader(
  title: string,
  subtitle?: string,
  actions?: Node[],
): HTMLElement {
  return h(
    "header",
    { class: "page-header" },
    h(
      "div",
      {},
      h("h1", { class: "page-header__title", text: title }),
      subtitle ? h("p", { class: "page-header__subtitle", text: subtitle }) : null,
    ),
    actions && actions.length > 0
      ? h("div", { class: "page-header__actions" }, ...actions)
      : null,
  );
}

// ── 17. Список «ключ-значение» ───────────────────────────────────

export function keyValue(entries: Array<{ key: string; value: string }>): HTMLElement {
  return h(
    "div",
    { class: "kv" },
    ...entries.flatMap((e) => [
      h("span", { class: "kv__k", text: e.key }),
      h("span", { class: "kv__v", text: e.value }),
    ]),
  );
}
