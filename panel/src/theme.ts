/** Темы: тёмная по умолчанию (§5.2), светлая — инверсия токенов. */

export type Theme = "dark" | "light";

const STORAGE_KEY = "jarvis-theme";

function apply(theme: Theme): void {
  document.documentElement.dataset.theme = theme;

  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // localStorage может быть недоступен — тема просто не запомнится
  }
}

export function initTheme(): Theme {
  let saved: string | null = null;

  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch {
    saved = null;
  }

  const theme: Theme = saved === "light" ? "light" : "dark";
  apply(theme);
  return theme;
}

export function setTheme(theme: Theme): void {
  apply(theme);
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  apply(next);
  return next;
}
