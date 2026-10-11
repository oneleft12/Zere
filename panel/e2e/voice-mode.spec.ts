/**
 * Кнопка «Режим голоса» в шапке чата (`GET/POST /api/voice/mode`).
 *
 * Бэкенд режима подменяется целиком: тест держит состояние сам, поэтому
 * проверяются именно обещания панели — переключение, живая фаза цикла и
 * честное поведение там, где режима быть не может (нет STT, старый бэкенд).
 *
 * Сервер — tests/e2e_server.py (фейки), запускается Playwright сам.
 */

import { expect, test, type Page } from "@playwright/test";

const BUTTON = ".chat__mode";
const INPUT = 'input[placeholder="Спросите ZERE…"]';

/** Состояние режима в том виде, в каком его отдаёт контракт (openapi). */
interface ModeState {
  enabled: boolean;
  state: "idle" | "sleeping" | "listening" | "processing" | "speaking" | "error";
  available: boolean;
  wakeWordEnabled: boolean;
  wakeWord: string;
  lastUtterance: string;
  lastAnswer: string;
  lastError: string | null;
}

function modeState(patch: Partial<ModeState> = {}): ModeState {
  return {
    enabled: false,
    state: "idle",
    available: true,
    wakeWordEnabled: true,
    wakeWord: "зере",
    lastUtterance: "",
    lastAnswer: "",
    lastError: null,
    ...patch,
  };
}

/** Живой «сервер» режима: GET отдаёт состояние, POST его переключает. */
async function mockMode(page: Page, initial: ModeState): Promise<{ current: ModeState }> {
  const box = { current: initial };

  await page.route("**/api/voice/mode", async (route) => {
    if (route.request().method() === "POST") {
      const body = JSON.parse(route.request().postData() ?? "{}") as { enabled?: boolean };
      const enabled = Boolean(body.enabled);
      box.current = modeState({ ...box.current, enabled, state: enabled ? "sleeping" : "idle" });
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(box.current),
    });
  });

  return box;
}

test("чат: кнопка включает и выключает режим голоса", async ({ page }) => {
  const box = await mockMode(page, modeState());
  await page.goto("/chat");

  const button = page.locator(BUTTON);
  await expect(button).toBeVisible({ timeout: 15_000 });
  await expect(button).toContainText("Режим голоса");
  await expect(button).toHaveAttribute("aria-pressed", "false");

  await button.click();

  // Тост ищем по тексту, а не по «первому»: рядом живёт уведомление об
  // обновлении ZERE, и оно тоже `.toast` (тосты уходят через 4.2 с).
  await expect(
    page.locator(".toast").filter({ hasText: "Голосовой режим включён" }),
  ).toBeVisible({ timeout: 15_000 });
  await expect(button).toHaveAttribute("aria-pressed", "true", { timeout: 15_000 });
  await expect(button).toContainText("ждёт «зере»");
  expect(box.current.enabled).toBe(true);

  await button.click();

  await expect(button).toHaveAttribute("aria-pressed", "false", { timeout: 15_000 });
  await expect(button).toContainText("Режим голоса");
  await expect(button).not.toContainText("ждёт");
  expect(box.current.enabled).toBe(false);
});

test("чат: подпись кнопки догоняет фазу цикла", async ({ page }) => {
  const box = await mockMode(page, modeState({ enabled: true, state: "sleeping" }));
  await page.goto("/chat");

  const button = page.locator(BUTTON);
  await expect(button).toContainText("ждёт «зере»", { timeout: 15_000 });

  // Сервер перешёл к распознаванию команды: кнопка обновляется сама,
  // без нажатий — фаза и есть тот смысл, ради которого она в шапке.
  box.current = modeState({ enabled: true, state: "listening" });
  await expect(button).toContainText("слушает команду", { timeout: 15_000 });
});

test("чат: без STT кнопка режима выключена и объясняет причину", async ({ page }) => {
  await mockMode(page, modeState({ available: false }));
  await page.goto("/chat");

  const button = page.locator(BUTTON);
  await expect(button).toBeDisabled({ timeout: 15_000 });
  await expect(button).toHaveAttribute(
    "title",
    "Распознавание речи недоступно — режим голоса включить нельзя",
  );
});

test("чат: у старого бэкенда без /api/voice/mode кнопки нет", async ({ page }) => {
  await page.route("**/api/voice/mode", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ code: "NOT_FOUND", message: "Ресурс не найден." }),
    }),
  );
  await page.goto("/chat");

  // Чат работает как раньше: мёртвый переключатель хуже его отсутствия.
  await expect(page.locator(INPUT)).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(BUTTON)).toBeHidden();
});
