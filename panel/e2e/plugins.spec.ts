/**
 * Экран «Плагины»: выбор браузера для MCP-плагина.
 *
 * Пользовательский сценарий целиком: вкладка «Плагины» показывает список
 * браузеров от бэкенда, выбор уходит на сервер тем же путём, что команда
 * «браузер выбери opera gx» в чате, ответ показывается тостом, а карточка
 * обновляется без перезагрузки страницы. Отказ (браузер не найден) не
 * меняет настройку — селект возвращается к реальному выбору.
 *
 * Сервер — tests/e2e_server.py: фейковые MCP-плагины вместо npx/Playwright,
 * у плагина браузера соглашается только Edge.
 */

import { expect, test } from "@playwright/test";

const CARD = "Браузер для плагина MCP";
const CHOOSE = "Выбрать браузер";

test("плагины: браузер MCP выбирается из вкладки и сохраняется", async ({ page }) => {
  await page.goto("/plugins");

  // Карточка появилась: маршрут /api/plugins/mcp есть, плагин браузера загружен.
  await expect(page.getByText(CARD, { exact: true })).toBeVisible();

  // Список браузеров приходит с бэкенда (включая недоступные — с отметкой).
  const browser = page.getByRole("combobox");
  await expect(browser.locator("option")).toHaveCount(4);
  await expect(browser.locator("option[value=opera-gx]")).toHaveText("Opera GX — не найден");
  await expect(browser).toHaveValue("chrome");

  await browser.selectOption("edge");
  await page.getByRole("button", { name: CHOOSE }).click();

  // Текст ответа — тот же, что у команды из чата.
  await expect(page.locator(".toast").last()).toContainText(
    "Браузер переключён на Microsoft Edge.",
    { timeout: 10_000 },
  );

  // Карточка перерисовалась: селект и подпись показывают новый выбор.
  await expect(page.getByRole("combobox")).toHaveValue("edge");
  await expect(page.locator(".kv", { hasText: "Сейчас" })).toContainText("Microsoft Edge");
  await expect(page.getByText("канал Playwright: msedge")).toBeVisible();

  // Состояние MCP-серверов видно рядом: команда запуска — для согласия.
  await expect(page.getByText("MCP-серверы")).toBeVisible();
  await expect(page.getByText("npx -y @playwright/mcp@0.0.83").first()).toBeVisible();
  await expect(page.locator(".kv", { hasText: "obsidian" })).toBeVisible();
});

test("плагины: отказ показывается текстом бэкенда и не меняет выбор", async ({ page }) => {
  await page.goto("/plugins");

  const browser = page.getByRole("combobox");
  await browser.selectOption("edge");
  await page.getByRole("button", { name: CHOOSE }).click();
  await expect(page.locator(".toast").last()).toContainText("Microsoft Edge", {
    timeout: 10_000,
  });

  // Opera GX фейковый плагин отклоняет — как настоящий, когда его нет на диске.
  await browser.selectOption("opera-gx");
  await page.getByRole("button", { name: CHOOSE }).click();

  await expect(page.locator(".toast").last()).toContainText("Opera GX не найден.", {
    timeout: 10_000,
  });

  // Настройка не изменилась: селект вернулся к текущему браузеру.
  await expect(page.getByRole("combobox")).toHaveValue("edge");
  await expect(page.locator(".kv", { hasText: "Сейчас" })).toContainText("Microsoft Edge");
});
