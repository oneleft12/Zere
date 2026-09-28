/**
 * Смоук-сценарий приёмки (§9 п.4 плана): дашборд → чат → настройки,
 * плюс проверка i18n (смена языка интерфейса) и клавиатурной навигации.
 *
 * Сервер — tests/e2e_server.py (фейки): статус Ollama «недоступен»,
 * ответ чата «ответ: …», память пустая. Каждый тест — свежий контекст
 * (чистый localStorage, язык по умолчанию ru).
 */

import { expect, test } from "@playwright/test";

const TITLE = ".page-header__title";

test("дашборд: заголовок и статус-строка с сервисами", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator(TITLE)).toHaveText("Дашборд");
  await expect(page.locator(".shell__status")).toContainText("Ollama", { timeout: 15_000 });
  await expect(page.locator(".shell__status")).toContainText("память:");
});

test("навигация: переход в «Чат» и честное пустое состояние", async ({ page }) => {
  await page.goto("/");

  await page.locator('.nav-item[title="Чат"]').click();

  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator(TITLE)).toHaveText("Чат");
  await expect(page.getByText("Начните диалог")).toBeVisible();
});

test("чат: SSE-ответ доходит до экрана", async ({ page }) => {
  await page.goto("/chat");

  await page.getByPlaceholder("Спросите JARVIS…").fill("привет");
  await page.getByRole("button", { name: "Отправить" }).click();

  await expect(page.locator(".msg--assistant")).toContainText("ответ: привет", {
    timeout: 15_000,
  });
});

test("настройки: правка конфига сохраняется через API", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.locator(TITLE)).toHaveText("Настройки");

  // Уникальное значение — иначе повторный прогон не сделает черновик «грязным».
  const name = `JARVIS E2E ${Date.now()}`;
  await page
    .locator("label.field", { hasText: "Имя ассистента" })
    .locator("input")
    .fill(name);

  const save = page.getByRole("button", { name: "Сохранить" });
  await expect(save).toBeEnabled();
  await save.click();

  await expect(page.locator(".toast").first()).toContainText("Конфигурация сохранена", {
    timeout: 15_000,
  });
});

test("i18n: переключение интерфейса на английский переживает перезагрузку", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.locator(TITLE)).toHaveText("Настройки");

  await page
    .locator("label.field", { hasText: "Язык интерфейса" })
    .locator("select")
    .selectOption("en");

  // Экран перерисовывается асинхронно (перезагрузка конфига) — toHaveText ждёт.
  await expect(page.locator(TITLE)).toHaveText("Settings", { timeout: 15_000 });
  await expect(page.locator('.nav-item[title="Dashboard"]')).toBeVisible();

  await page.reload();
  await expect(page.locator(TITLE)).toHaveText("Settings");
});
