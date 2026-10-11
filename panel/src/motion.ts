/**
 * Движение ZERE: тонкий слой поверх CSS.
 *
 * Принцип: состояния и переходы описываются в CSS (там им место), а в JS
 * живёт только то, что CSS не умеет — реальные числа (счётчики метрик),
 * измеряемая высота раскрытия и разовая подсветка изменения.
 *
 * Весь модуль уважает `prefers-reduced-motion`: движение убирается,
 * а подтверждение действия (цвет, появление) остаётся — иначе интерфейс
 * теряет обратную связь, а не только украшение.
 */

const reducedQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

/** Системная настройка «уменьшить движение» прямо сейчас. */
export function reducedMotion(): boolean {
  return reducedQuery.matches;
}

/**
 * Ставит на <html> флаги для CSS: `data-reduced-motion` и `data-doc-hidden`.
 * Вторая галочка глушит необязательные циклы (орб, свечения), когда
 * вкладка не видна: фоновая панель не должна грешить анимацией.
 */
export function initMotionGuards(): void {
  const applyReduced = (): void => {
    document.documentElement.dataset.reducedMotion = reducedMotion() ? "1" : "0";
  };

  applyReduced();
  reducedQuery.addEventListener("change", applyReduced);

  const applyHidden = (): void => {
    document.documentElement.dataset.docHidden = document.hidden ? "1" : "0";
  };

  applyHidden();
  document.addEventListener("visibilitychange", applyHidden);
}

/** Ждёт ближайший кадр — чтобы стартовое значение успело примениться. */
function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

/**
 * Раскрывает/сворачивает блок по реальной высоте содержимого.
 * `height` — свойство раскладки, поэтому анимируется только на время
 * перехода и сразу снимается: после него блок живёт в `auto`.
 */
export async function slideToggle(el: HTMLElement, open: boolean, duration = 260): Promise<void> {
  if (reducedMotion() || duration <= 0) {
    el.style.height = "";
    return;
  }

  const from = el.getBoundingClientRect().height;
  el.style.height = open ? "auto" : `${from}px`;

  if (open) {
    await nextFrame();
    const to = el.getBoundingClientRect().height;
    el.style.height = `${from}px`;

    const animation = el.animate([{ height: `${from}px` }, { height: `${to}px` }], {
      duration,
      easing: "cubic-bezier(0.16, 1, 0.3, 1)",
    });
    await animation.finished.catch(() => undefined);
    el.style.height = "";
    return;
  }

  const animation = el.animate([{ height: `${from}px` }, { height: "0px" }], {
    duration: Math.round(duration * 0.8),
    easing: "cubic-bezier(0.65, 0, 0.35, 1)",
  });
  await animation.finished.catch(() => undefined);
  el.style.height = "";
}

/**
 * Плавно перебирает число в элементе: метрики дашборда приходят из API
 * мгновенно, и «досчёт» показывает, что значение изменилось, а не мигнуло.
 */
export function countUp(
  el: HTMLElement,
  to: number,
  opts: { from?: number; duration?: number; format?: (value: number) => string } = {},
): void {
  const format = opts.format ?? ((value: number) => String(Math.round(value)));
  const from = opts.from ?? 0;

  if (reducedMotion() || from === to) {
    el.textContent = format(to);
    return;
  }

  const duration = opts.duration ?? 520;
  const start = performance.now();

  const step = (now: number): void => {
    const progress = Math.min(1, (now - start) / duration);
    // Экспоненциальное затухание: быстрый старт, спокойное прибытие.
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = format(from + (to - from) * eased);
    if (progress < 1) requestAnimationFrame(step);
  };

  requestAnimationFrame(step);
}


/**
 * Разводит появление детей списка по времени.
 * Ставит `--i` каждому ребёнку: CSS берёт задержку из `--i` и `--stagger`.
 */
export function staggerChildren(parent: ParentNode, selector = ":scope > *", step = 24, max = 240): void {
  if (reducedMotion()) return;

  const items = Array.from(parent.querySelectorAll<HTMLElement>(selector)).slice(0, 12);
  items.forEach((item, index) => {
    item.style.setProperty("--i", String(index));
    item.style.setProperty("--stagger", `${step}ms`);
    item.classList.add("stagger-in");
    // Задержка ограничена: длинный список не должен «догонять» себя.
    if (index * step > max) item.style.animationDelay = `${max}ms`;
  });
}
