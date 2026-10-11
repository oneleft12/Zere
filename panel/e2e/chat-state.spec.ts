/**
 * Состояние чата при переходах по вкладкам (регрессия «чат сбрасывает
 * диалог»): роутер пересоздаёт экран на каждом переходе, поэтому диалог
 * и черновик обязаны жить вне фабрики экрана, а начатый стрим — не
 * обрываться при уходе с вкладки.
 *
 * Сервер — tests/e2e_server.py (фейки), запускается Playwright сам.
 */

import { expect, test, type Page } from "@playwright/test";

const TITLE = ".page-header__title";
const INPUT = 'input[placeholder="Спросите ZERE…"]';

function nav(page: Page, title: string) {
  return page.locator(`.nav-item[title="${title}"]`);
}

async function ask(page: Page, text: string): Promise<void> {
  await page.locator(INPUT).fill(text);
  await page.getByRole("button", { name: "Отправить" }).click();
}

test("чат: диалог переживает переход на другую вкладку и возврат", async ({ page }) => {
  await page.goto("/chat");
  await ask(page, "привет");

  await expect(page.locator(".msg--user")).toHaveText("привет");
  await expect(page.locator(".msg--assistant")).toContainText("ответ: привет", {
    timeout: 15_000,
  });

  // Уходим на «Подключение ИИ» и возвращаемся в чат.
  await nav(page, "Подключение ИИ").click();
  await expect(page.locator(TITLE)).toHaveText("Подключение ИИ");

  await nav(page, "Чат").click();
  await expect(page.locator(TITLE)).toHaveText("Чат");

  // Диалог на месте: ни пустого состояния, ни потерянных реплик.
  await expect(page.getByText("Начните диалог")).toHaveCount(0);
  await expect(page.locator(".msg")).toHaveCount(2);
  await expect(page.locator(".msg--user")).toHaveText("привет");
  await expect(page.locator(".msg--assistant")).toContainText("ответ: привет");
});

test("чат: диалог переживает возврат из настроек через историю переходов", async ({ page }) => {
  await page.goto("/chat");
  await ask(page, "второй вопрос");
  await expect(page.locator(".msg--assistant")).toContainText("ответ: второй вопрос", {
    timeout: 15_000,
  });

  await nav(page, "Настройки").click();
  await expect(page.locator(TITLE)).toHaveText("Настройки");

  // Кнопка «назад» браузера — тот же роутер (popstate), состояние то же.
  await page.goBack();
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator(".msg")).toHaveCount(2);
  await expect(page.locator(".msg--assistant")).toContainText("ответ: второй вопрос");
});

test("чат: набранный, но не отправленный текст переживает переход", async ({ page }) => {
  await page.goto("/chat");
  await page.locator(INPUT).fill("громкость 50");

  await nav(page, "Подключение ИИ").click();
  await expect(page.locator(TITLE)).toHaveText("Подключение ИИ");

  await nav(page, "Чат").click();
  await expect(page.locator(INPUT)).toHaveValue("громкость 50");
  await expect(page.locator(".msg")).toHaveCount(0);
});

test("чат: ответ, начатый до ухода с вкладки, дописывается и не теряется", async ({ page }) => {
  // Медленный поток: ответ приходит в тот момент, когда чат уже закрыт.
  await page.route("**/api/chat/stream**", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream; charset=utf-8" },
      body:
        'event: token\ndata: {"text":"медленный ответ"}\n\n' +
        'event: done\ndata: {"answer":"медленный ответ"}\n\n',
    });
  });

  await page.goto("/chat");
  await ask(page, "долгий вопрос");
  await expect(page.locator(".loading-row")).toBeVisible();

  await nav(page, "Подключение ИИ").click();
  await expect(page.locator(TITLE)).toHaveText("Подключение ИИ");

  // Пока пользователь на другой вкладке поток доехал до конца.
  await page.waitForTimeout(2000);

  await nav(page, "Чат").click();
  await expect(page.locator(".msg--assistant")).toContainText("медленный ответ", {
    timeout: 10_000,
  });

  // Стрим завершился в модуле: композер снова свободен, «Думаю…» нет.
  await expect(page.locator(INPUT)).toBeEnabled();
  await expect(page.locator(".loading-row")).toHaveCount(0);
});
