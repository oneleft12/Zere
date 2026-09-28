/**
 * Роутер SPA на History API: глубокие ссылки работают, потому что оба
 * бэкенда отдают index.html для путей без расширения (SPA-фоллбэк).
 */

import { t } from "./i18n";

export type Cleanup = () => void;
export type ScreenFactory = (container: HTMLElement) => void | Cleanup;

export interface Route {
  path: string;
  title: string;
  factory: ScreenFactory;
}

const routes = new Map<string, Route>();

let mountEl: HTMLElement | null = null;
let cleanup: Cleanup | null = null;
let onRoute: ((route: Route) => void) | null = null;

export function registerRoute(route: Route): void {
  routes.set(route.path, route);
}

export function navigate(path: string): void {
  if (window.location.pathname === path) {
    render();
    return;
  }

  history.pushState(null, "", path);
  render();
}

export function startRouter(mount: HTMLElement, onRouteChange: (route: Route) => void): void {
  mountEl = mount;
  onRoute = onRouteChange;

  window.addEventListener("popstate", render);
  render();
}

function render(): void {
  if (!mountEl) return;

  const path = window.location.pathname;
  const route = routes.get(path) ?? routes.get("/");

  if (!route) return;

  if (cleanup) {
    cleanup();
    cleanup = null;
  }

  while (mountEl.firstChild) mountEl.removeChild(mountEl.firstChild);

  document.title = `${t(route.title)} — JARVIS`;
  onRoute?.(route);

  const result = route.factory(mountEl);
  cleanup = typeof result === "function" ? result : null;
}
