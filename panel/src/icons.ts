/**
 * Иконочный набор ZERE: только авторские SVG, без эмодзи и символьных
 * подстановок (у них разная толщина и своя метрика в каждой системе).
 *
 * Правила набора — один чертёж на весь продукт:
 *  - сетка 24×24, поле 3px, толщина штриха 1.6, скругления round;
 *  - цвет наследуется (`currentColor`), заливка только у точек-маркеров;
 *  - размер по умолчанию 18px, кратен шагу строки.
 *
 * Собирается через DOM (`createElementNS`), а не строками HTML: набор
 * статический, но правило «никакой интерполяции в разметку» остаётся общим.
 */

const NS = "http://www.w3.org/2000/svg";

type Shape =
  | { t: "path"; d: string }
  | { t: "circle"; cx: number; cy: number; r: number; fill?: boolean }
  | { t: "line"; x1: number; y1: number; x2: number; y2: number }
  | { t: "poly"; points: string }
  | { t: "rect"; x: number; y: number; w: number; h: number; rx?: number; fill?: boolean };

const ICONS = {
  /** Знак ZERE: ядро в оболочке — ассистент внутри системы. */
  brand: [
    { t: "path", d: "M12 3.4l7.4 4.3v8.6L12 20.6 4.6 16.3V7.7z" },
    { t: "circle", cx: 12, cy: 12, r: 2.3, fill: true },
  ],
  dashboard: [
    { t: "path", d: "M3.5 18.5a8.5 8.5 0 1 1 17 0" },
    { t: "path", d: "M12 18.5l4.3-6" },
    { t: "circle", cx: 12, cy: 18.5, r: 1.3, fill: true },
  ],
  ai: [
    { t: "path", d: "M11 4.2l1.7 4.9 4.9 1.7-4.9 1.7L11 17.4l-1.7-4.9-4.9-1.7 4.9-1.7z" },
    { t: "path", d: "M17.8 15.4l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" },
  ],
  chat: [
    {
      t: "path",
      d: "M20 12.2c0 3.5-3.6 6.3-8 6.3-1 0-2-.14-2.9-.4L5 20.4l1.2-3.2A6.3 6.3 0 0 1 4 12.2C4 8.7 7.6 6 12 6s8 2.7 8 6.2z",
    },
  ],
  history: [
    { t: "path", d: "M3.4 12a8.6 8.6 0 1 1 2.7 6.3" },
    { t: "poly", points: "3.2 5 3.2 9.2 7.4 9.2" },
    { t: "path", d: "M12 7.9v4.4l3 1.8" },
  ],
  memory: [
    { t: "circle", cx: 6, cy: 8, r: 2.2 },
    { t: "circle", cx: 18, cy: 8, r: 2.2 },
    { t: "circle", cx: 12, cy: 17, r: 2.2 },
    { t: "line", x1: 8.2, y1: 8, x2: 15.8, y2: 8 },
    { t: "line", x1: 7.3, y1: 9.7, x2: 10.9, y2: 15.2 },
    { t: "line", x1: 16.7, y1: 9.7, x2: 13.1, y2: 15.2 },
  ],
  voice: [
    { t: "path", d: "M12 4.6a2.6 2.6 0 0 1 2.6 2.6v4.9a2.6 2.6 0 0 1-5.2 0V7.2A2.6 2.6 0 0 1 12 4.6z" },
    { t: "path", d: "M6.6 11.6a5.4 5.4 0 0 0 10.8 0" },
    { t: "line", x1: 12, y1: 17, x2: 12, y2: 20 },
    { t: "line", x1: 9, y1: 20, x2: 15, y2: 20 },
  ],
  voiceOff: [
    { t: "path", d: "M12 4.6a2.6 2.6 0 0 1 2.6 2.6v4.9a2.6 2.6 0 0 1-5.2 0V7.2A2.6 2.6 0 0 1 12 4.6z" },
    { t: "path", d: "M6.6 11.6a5.4 5.4 0 0 0 10.8 0" },
    { t: "line", x1: 12, y1: 17, x2: 12, y2: 20 },
    { t: "line", x1: 9, y1: 20, x2: 15, y2: 20 },
    { t: "line", x1: 4.5, y1: 4.5, x2: 19.5, y2: 19.5 },
  ],
  processes: [{ t: "poly", points: "3 12.5 7.5 12.5 10 6.5 14 18 16.5 12.5 21 12.5" }],
  folders: [
    {
      t: "path",
      d: "M3.5 7.4c0-1.1.9-2 2-2h4.1l2 2h6.9c1.1 0 2 .9 2 2v7.2c0 1.1-.9 2-2 2h-13c-1.1 0-2-.9-2-2z",
    },
    { t: "path", d: "M3.5 10.2h17" },
  ],
  apps: [
    { t: "rect", x: 4, y: 4, w: 6.6, h: 6.6, rx: 2 },
    { t: "rect", x: 13.4, y: 4, w: 6.6, h: 6.6, rx: 2 },
    { t: "rect", x: 4, y: 13.4, w: 6.6, h: 6.6, rx: 2 },
    { t: "rect", x: 13.4, y: 13.4, w: 6.6, h: 6.6, rx: 2 },
  ],
  plugins: [
    {
      t: "path",
      d: "M5 9.6V6.9c0-1 .8-1.9 1.9-1.9h2.7a1.9 1.9 0 1 0 3.8 0h2.5c1 0 1.9.8 1.9 1.9v2.6a1.9 1.9 0 1 1 0 3.8v2.8c0 1-.9 1.9-1.9 1.9h-2.8a1.9 1.9 0 1 0-3.8 0H6.9c-1 0-1.9-.8-1.9-1.9v-2.7a1.9 1.9 0 1 1 0-3.8z",
    },
  ],
  logs: [
    { t: "rect", x: 3.5, y: 4.5, w: 17, h: 15, rx: 2.5 },
    { t: "poly", points: "7.4 10 9.9 12.5 7.4 15" },
    { t: "line", x1: 12.2, y1: 15.2, x2: 16.4, y2: 15.2 },
  ],
  settings: [
    { t: "line", x1: 3.5, y1: 8.5, x2: 20.5, y2: 8.5 },
    { t: "rect", x: 7.6, y: 6.2, w: 5.8, h: 4.6, rx: 1.7 },
    { t: "line", x1: 3.5, y1: 15.5, x2: 20.5, y2: 15.5 },
    { t: "rect", x: 11.4, y: 13.2, w: 5.8, h: 4.6, rx: 1.7 },
  ],
  update: [
    { t: "line", x1: 12, y1: 4, x2: 12, y2: 15 },
    { t: "poly", points: "7.2 10.2 12 15 16.8 10.2" },
    { t: "path", d: "M4.5 19.5h15" },
  ],
  personalities: [
    { t: "circle", cx: 9.4, cy: 8.6, r: 3.2 },
    { t: "path", d: "M3.8 19.6c0-3.1 2.5-5.2 5.6-5.2s5.6 2.1 5.6 5.2" },
    { t: "path", d: "M16 6.2a3.2 3.2 0 0 1 0 6.2" },
    { t: "path", d: "M17.6 14.6c1.7.7 2.8 2.4 2.8 5" },
  ],
  search: [
    { t: "circle", cx: 10.6, cy: 10.6, r: 6 },
    { t: "line", x1: 15.2, y1: 15.2, x2: 20.4, y2: 20.4 },
  ],
  close: [
    { t: "line", x1: 6.2, y1: 6.2, x2: 17.8, y2: 17.8 },
    { t: "line", x1: 17.8, y1: 6.2, x2: 6.2, y2: 17.8 },
  ],
  check: [{ t: "poly", points: "5 12.6 9.8 17.4 19 8.2" }],
  chevronRight: [{ t: "poly", points: "9.5 6 15.5 12 9.5 18" }],
  chevronDown: [{ t: "poly", points: "6 9.5 12 15.5 18 9.5" }],
  sun: [
    { t: "circle", cx: 12, cy: 12, r: 4 },
    { t: "line", x1: 12, y1: 2.6, x2: 12, y2: 5 },
    { t: "line", x1: 12, y1: 19, x2: 12, y2: 21.4 },
    { t: "line", x1: 2.6, y1: 12, x2: 5, y2: 12 },
    { t: "line", x1: 19, y1: 12, x2: 21.4, y2: 12 },
    { t: "line", x1: 5.4, y1: 5.4, x2: 7.1, y2: 7.1 },
    { t: "line", x1: 16.9, y1: 16.9, x2: 18.6, y2: 18.6 },
    { t: "line", x1: 18.6, y1: 5.4, x2: 16.9, y2: 7.1 },
    { t: "line", x1: 7.1, y1: 16.9, x2: 5.4, y2: 18.6 },
  ],
  moon: [{ t: "path", d: "M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8a8.6 8.6 0 1 0 10.8 10.8z" }],
  sidebar: [
    { t: "rect", x: 3.5, y: 4.5, w: 17, h: 15, rx: 2.5 },
    { t: "line", x1: 9.6, y1: 4.5, x2: 9.6, y2: 19.5 },
  ],
  send: [
    { t: "line", x1: 12, y1: 19.6, x2: 12, y2: 5 },
    { t: "poly", points: "5.6 11.4 12 5 18.4 11.4" },
  ],
  refresh: [
    { t: "path", d: "M20.4 12a8.4 8.4 0 1 1-2.6-6.1" },
    { t: "poly", points: "20.6 4.4 20.6 9.4 15.6 9.4" },
  ],
  trash: [
    { t: "line", x1: 4.5, y1: 7, x2: 19.5, y2: 7 },
    { t: "path", d: "M6.6 7l.9 11.4c.1.9.8 1.6 1.7 1.6h5.6c.9 0 1.6-.7 1.7-1.6L17.4 7" },
    { t: "path", d: "M9.6 7V5.4c0-.8.6-1.4 1.4-1.4h2c.8 0 1.4.6 1.4 1.4V7" },
    { t: "line", x1: 10.6, y1: 10.8, x2: 10.6, y2: 16.2 },
    { t: "line", x1: 13.4, y1: 10.8, x2: 13.4, y2: 16.2 },
  ],
  copy: [
    { t: "rect", x: 8.8, y: 8.8, w: 11.2, h: 11.2, rx: 2.5 },
    { t: "path", d: "M15.2 6.4V5.6c0-.9-.7-1.6-1.6-1.6H5.6C4.7 4 4 4.7 4 5.6v8c0 .9.7 1.6 1.6 1.6h.9" },
  ],
  external: [
    { t: "path", d: "M14 4.5h5.5V10" },
    { t: "path", d: "M19.5 4.5L12.2 11.8" },
    { t: "path", d: "M18 14v4.4c0 .9-.7 1.6-1.6 1.6H5.6c-.9 0-1.6-.7-1.6-1.6V7.6C4 6.7 4.7 6 5.6 6H10" },
  ],
  alert: [
    { t: "path", d: "M12 4.4l9 15.2H3z" },
    { t: "line", x1: 12, y1: 9.8, x2: 12, y2: 14.4 },
    { t: "circle", cx: 12, cy: 17.1, r: 0.9, fill: true },
  ],
  info: [
    { t: "circle", cx: 12, cy: 12, r: 8.4 },
    { t: "line", x1: 12, y1: 11, x2: 12, y2: 16.4 },
    { t: "circle", cx: 12, cy: 7.9, r: 0.9, fill: true },
  ],
  plus: [
    { t: "line", x1: 12, y1: 5, x2: 12, y2: 19 },
    { t: "line", x1: 5, y1: 12, x2: 19, y2: 12 },
  ],
  keyboard: [
    { t: "rect", x: 3, y: 6.2, w: 18, h: 11.6, rx: 2.5 },
    { t: "line", x1: 8, y1: 14.6, x2: 16, y2: 14.6 },
    { t: "circle", cx: 7, cy: 10, r: 0.85, fill: true },
    { t: "circle", cx: 11, cy: 10, r: 0.85, fill: true },
    { t: "circle", cx: 15, cy: 10, r: 0.85, fill: true },
  ],
  stop: [{ t: "rect", x: 7.4, y: 7.4, w: 9.2, h: 9.2, rx: 2.2, fill: true }],
  play: [{ t: "path", d: "M8 5.6L18.4 12 8 18.4z" }],
  power: [
    { t: "line", x1: 12, y1: 4, x2: 12, y2: 11.4 },
    { t: "path", d: "M7.6 7.2a6.5 6.5 0 1 0 8.8 0" },
  ],
  volume: [
    { t: "path", d: "M4.4 9.4h3l4-3.5v12.2l-4-3.5h-3z" },
    { t: "path", d: "M14.9 9.5a3.6 3.6 0 0 1 0 5" },
    { t: "path", d: "M17.4 7a7 7 0 0 1 0 10" },
  ],
  eye: [
    { t: "path", d: "M2.8 12S6.6 5.9 12 5.9 21.2 12 21.2 12 17.4 18.1 12 18.1 2.8 12 2.8 12z" },
    { t: "circle", cx: 12, cy: 12, r: 2.8 },
  ],
  bolt: [{ t: "path", d: "M13.6 3.2L5.4 13.6h5.1L10.2 20.8l8.4-10.4h-5.2z" }],
  branch: [
    { t: "circle", cx: 7, cy: 6.4, r: 2.2 },
    { t: "circle", cx: 7, cy: 17.6, r: 2.2 },
    { t: "circle", cx: 16.6, cy: 10.2, r: 2.2 },
    { t: "line", x1: 7, y1: 8.6, x2: 7, y2: 15.4 },
    { t: "path", d: "M9.2 6.4h2.9a4.5 4.5 0 0 1 4.5 4.3" },
  ],
  filter: [
    { t: "path", d: "M4 6.6h16" },
    { t: "path", d: "M7.2 12h9.6" },
    { t: "path", d: "M10.4 17.4h3.2" },
  ],
  more: [
    { t: "circle", cx: 6, cy: 12, r: 1.4, fill: true },
    { t: "circle", cx: 12, cy: 12, r: 1.4, fill: true },
    { t: "circle", cx: 18, cy: 12, r: 1.4, fill: true },
  ],
  list: [
    { t: "line", x1: 8.4, y1: 7, x2: 20, y2: 7 },
    { t: "line", x1: 8.4, y1: 12, x2: 20, y2: 12 },
    { t: "line", x1: 8.4, y1: 17, x2: 20, y2: 17 },
    { t: "circle", cx: 4.6, cy: 7, r: 1, fill: true },
    { t: "circle", cx: 4.6, cy: 12, r: 1, fill: true },
    { t: "circle", cx: 4.6, cy: 17, r: 1, fill: true },
  ],
  undo: [
    { t: "poly", points: "9 6.4 4.4 11 9 15.6" },
    { t: "path", d: "M4.4 11h9.2a5.4 5.4 0 1 1 0 10.8H10" },
  ],
  shield: [
    { t: "path", d: "M12 3.6l7 2.6v6c0 4-3 7.2-7 8.2-4-1-7-4.2-7-8.2v-6z" },
    { t: "poly", points: "9 12 11.4 14.4 15.4 10" },
  ],
} satisfies Record<string, Shape[]>;

export type IconName = keyof typeof ICONS;

export const ICON_NAMES = Object.keys(ICONS) as IconName[];

export interface IconOptions {
  /** Размер стороны, px. По умолчанию 18 — шаг строки интерфейса. */
  size?: number;
  /** Дополнительный класс (например, для поворота шеврона). */
  class?: string;
  /** Подпись для скринридера; без неё иконка декоративна и скрыта. */
  label?: string;
  /** Толщина штриха; 1.6 — базовый вес набора. */
  stroke?: number;
}

/** Собирает SVG-иконку набора. Разметка статическая, данные не подставляются. */
export function icon(name: IconName, opts: IconOptions = {}): SVGSVGElement {
  const size = opts.size ?? 18;

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", String(opts.stroke ?? 1.6));
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("class", opts.class ? `icon ${opts.class}` : "icon");
  svg.setAttribute("aria-hidden", opts.label ? "false" : "true");

  if (opts.label) {
    svg.setAttribute("role", "img");
    const title = document.createElementNS(NS, "title");
    title.textContent = opts.label;
    svg.appendChild(title);
  }

  for (const shape of ICONS[name]) {
    switch (shape.t) {
      case "path": {
        const path = document.createElementNS(NS, "path");
        path.setAttribute("d", shape.d);
        svg.appendChild(path);
        break;
      }
      case "circle": {
        const circle = document.createElementNS(NS, "circle");
        circle.setAttribute("cx", String(shape.cx));
        circle.setAttribute("cy", String(shape.cy));
        circle.setAttribute("r", String(shape.r));
        if ("fill" in shape && shape.fill) {
          circle.setAttribute("fill", "currentColor");
          circle.setAttribute("stroke", "none");
        }
        svg.appendChild(circle);
        break;
      }
      case "line": {
        const line = document.createElementNS(NS, "line");
        line.setAttribute("x1", String(shape.x1));
        line.setAttribute("y1", String(shape.y1));
        line.setAttribute("x2", String(shape.x2));
        line.setAttribute("y2", String(shape.y2));
        svg.appendChild(line);
        break;
      }
      case "poly": {
        const poly = document.createElementNS(NS, "polyline");
        poly.setAttribute("points", shape.points);
        svg.appendChild(poly);
        break;
      }
      case "rect": {
        const rect = document.createElementNS(NS, "rect");
        rect.setAttribute("x", String(shape.x));
        rect.setAttribute("y", String(shape.y));
        rect.setAttribute("width", String(shape.w));
        rect.setAttribute("height", String(shape.h));
        if ("rx" in shape && shape.rx !== undefined) rect.setAttribute("rx", String(shape.rx));
        if ("fill" in shape && shape.fill) {
          rect.setAttribute("fill", "currentColor");
          rect.setAttribute("stroke", "none");
        }
        svg.appendChild(rect);
        break;
      }
    }
  }

  return svg;
}
