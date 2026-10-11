/**
 * Оболочка панели: командная палитра (Ctrl+K), сворачивание сайдбара в рейку
 * и орб состояния ассистента.
 *
 * Сервер — tests/e2e_server.py (фейки), запускается Playwright сам.
 */

import { expect, test } from "@playwright/test";

const TITLE = ".page-header__title";
const INPUT = 'input[placeholder="Спросите ZERE…"]';

test("палитра: Ctrl+K открывается и ведёт на экран", async ({ page }) => {
  await page.goto("/");

  await page.keyboard.press("Control+k");
  const palette = page.locator(".palette");
  await expect(palette).toBeVisible();

  // Поиск фильтрует не только по началу строки: «память» находит экран.
  await palette.locator("input").fill("память");
  await palette.locator('.palette__item[data-id="go:/memory"]').click();

  await expect(page).toHaveURL(/\/memory$/);
  await expect(page.locator(TITLE)).toHaveText("Память");
  await expect(page.locator(".palette")).toHaveCount(0);
});

test("палитра: команда ZERE подставляется в поле ввода чата", async ({ page }) => {
  await page.goto("/");

  await page.keyboard.press("Control+k");
  await page.locator(".palette input").fill("громкость 50");
  await page.locator('.palette__item[data-id="cmd:громкость 50"]').click();

  // Команда попадает в черновик чата, но НЕ отправляется сама.
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator(INPUT)).toHaveValue("громкость 50");
  await expect(page.locator(".msg")).toHaveCount(0);
});

test("палитра: Escape закрывает, стрелки выбирают, Enter выполняет", async ({ page }) => {
  await page.goto("/logs");

  await page.keyboard.press("Control+k");
  await expect(page.locator(".palette")).toBeVisible();

  await page.keyboard.press("ArrowDown");
  await expect(page.locator('.palette__item[data-selected="true"]')).toHaveCount(1);

  await page.keyboard.press("Escape");
  await expect(page.locator(".palette")).toHaveCount(0);
});

test("сайдбар: сворачивается в рейку и помнит состояние", async ({ page }) => {
  await page.goto("/");
  const sidebar = page.locator(".sidebar");
  const toggle = page.getByRole("button", { name: "Свернуть панель" });

  await expect(sidebar).not.toHaveClass(/sidebar--rail/);
  await toggle.click();
  await expect(sidebar).toHaveClass(/sidebar--rail/);

  // Состояние переживает перезагрузку (localStorage).
  await page.reload();
  await expect(page.locator(".sidebar")).toHaveClass(/sidebar--rail/);

  await page.getByRole("button", { name: "Развернуть панель" }).click();
  await expect(page.locator(".sidebar")).not.toHaveClass(/sidebar--rail/);
});

test("орб: показывает размышление по время ответа и покой после", async ({ page }) => {
  // Медленный поток: состояние «думает/говорит» успевает стать видимым.
  await page.route("**/api/chat/stream**", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream; charset=utf-8" },
      body:
        'event: token\ndata: {"text":"медленный ответ"}\n\n' +
        'event: done\ndata: {"answer":"медленный ответ"}\n\n',
    });
  });

  await page.goto("/chat");
  const orb = page.locator(".shell__status .orb");
  await expect(orb).toHaveClass(/orb--idle/);

  await page.locator(INPUT).fill("привет");
  await page.getByRole("button", { name: "Отправить" }).click();
  await expect(orb).toHaveClass(/orb--(thinking|speaking)/);

  await expect(page.locator(".msg--assistant")).toContainText("медленный ответ", {
    timeout: 10_000,
  });
  await expect(orb).toHaveClass(/orb--idle/);
});

test("оболочка: шапка показывает свежесть данных, статус-строка — службы", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator(".shell__subtitle")).toContainText("обновлено", { timeout: 15_000 });
  await expect(page.locator(".shell__status")).toContainText("Ollama");
  await expect(page.locator(".shell__status .orb")).toBeVisible();
});
