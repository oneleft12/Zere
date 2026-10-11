/**
 * Голосовое в чате: кнопка «Записать голосовое» в композере.
 *
 * Запись идёт на сервере (`POST /api/voice/listen`), но проверяем две
 * вещи, которых сервер не показывает: состояние «идёт запись» и то, куда
 * попадает распознанный текст. Поэтому ответ STT подменяется через
 * `page.route` и держится открытым, пока тест не отпустит его сам: окно
 * записи не зависит от того, как быстро Playwright завершил клик.
 *
 * Селектор кнопки — её собственный класс `.chat__mic`: `aria-label` по
 * контракту меняется на «Идёт запись голосового…», и по подписи кнопку
 * в фазе записи не найти.
 *
 * Сервер — tests/e2e_server.py (фейки), запускается Playwright сам.
 */

import { expect, test, type Page } from "@playwright/test";

const INPUT = 'input[placeholder="Спросите ZERE…"]';
const MIC = ".chat__mic";

/** Шлюз ответа STT: отпускает распознанный текст, когда тест разрешит. */
interface Listen {
  release: () => void;
}

async function mockListen(page: Page, text: string): Promise<Listen> {
  let release = (): void => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });

  await page.route("**/api/voice/listen", async (route) => {
    await gate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ text }),
    });
  });

  return { release };
}

test("чат: запись голосового показывает фазу записи и кладёт текст в поле ввода", async ({
  page,
}) => {
  const listen = await mockListen(page, "открой дискорд");
  await page.goto("/chat");

  const mic = page.locator(MIC);
  await expect(mic).toBeEnabled({ timeout: 15_000 });
  await mic.click();

  // Микрофон пишет: кнопка краснеет, подпись и статус говорят то же самое.
  await expect(mic).toHaveClass(/btn--recording/);
  await expect(mic).toHaveAttribute("aria-label", "Идёт запись голосового…");
  await expect(page.locator(".chat__state")).toContainText("Слушаю микрофон…");

  listen.release();

  // Запись кончилась — распознанное стоит в поле ввода, фокус там же, и
  // само ничего не отправилось: решение остаётся за пользователем.
  await expect(page.locator(INPUT)).toHaveValue("открой дискорд", { timeout: 15_000 });
  await expect(page.locator(INPUT)).toBeFocused();
  await expect(mic).not.toHaveClass(/btn--recording/);
  await expect(page.locator(".msg")).toHaveCount(0);
});

test("чат: Shift+клик по микрофону отправляет распознанное сразу", async ({ page }) => {
  const listen = await mockListen(page, "сколько времени");
  await page.goto("/chat");

  const mic = page.locator(MIC);
  await expect(mic).toBeEnabled({ timeout: 15_000 });
  await mic.click({ modifiers: ["Shift"] });
  listen.release();

  await expect(page.locator(".msg--user")).toHaveText("сколько времени", { timeout: 15_000 });
  await expect(page.locator(".msg--assistant")).toContainText("ответ: сколько времени", {
    timeout: 15_000,
  });
  await expect(page.locator(INPUT)).toHaveValue("");
});

test("чат: без STT кнопка выключена и объясняет причину", async ({ page }) => {
  // Бэкенд без распознавания: capabilities.sttTest=false — кнопка молчит
  // не загадочно, а с причиной в подсказке.
  await page.route("**/api/voice", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        voiceEnabled: true,
        voiceVolume: 1,
        ttsEngine: "silero",
        voiceReferencePath: "",
        audioProcessing: false,
        capabilities: {
          recordReference: false,
          pocketCloning: false,
          speechSpeedConfig: false,
          liveVolumeApply: true,
          sttTest: false,
        },
      }),
    });
  });
  await page.goto("/chat");

  const mic = page.locator(MIC);
  await expect(mic).toBeDisabled({ timeout: 15_000 });
  await expect(mic).toHaveAttribute("aria-label", "Распознавание речи недоступно");
  await expect(mic).toHaveAttribute(
    "title",
    "STT недоступен (capabilities.sttTest=false) — кнопка выключена",
  );
});
