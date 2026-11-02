/**
 * Справочник команд во вкладке «Чат» (каталог `panel/src/commands.ts`).
 *
 * Проверяем пользовательский сценарий целиком: панель открыта по умолчанию
 * и показывает все группы, поиск фильтрует список, нажатие подставляет
 * команду в поле ввода (и НЕ отправляет её), а свёрнутое состояние
 * запоминается между заходами.
 *
 * Сервер — tests/e2e_server.py (фейки), запускается Playwright сам.
 */

import { expect, test } from "@playwright/test";

const PANEL = ".chat__commands";

test("команды: панель открыта и содержит весь каталог", async ({ page }) => {
  await page.goto("/chat");

  const panel = page.locator(PANEL);
  await expect(panel).toBeVisible();
  await expect(panel.locator(".chat__commands-title")).toHaveText("Команды ZERE");

  // 15 групп: память, история, приложения, процессы, файлы, папки, громкость,
  // игры, питание, рисование, браузер (MCP), заметки (MCP), конспектор,
  // вопросы к ИИ, консоль.
  await expect(panel.locator(".cmd-group")).toHaveCount(15);

  // Бейдж в шапке панели совпадает с числом показанных команд.
  const total = await panel.locator(".cmd").count();
  expect(total).toBeGreaterThan(40);
  await expect(panel.locator(".chat__commands-head .badge")).toHaveText(String(total));

  // Известные команды всех ключевых обработчиков на месте.
  for (const command of [
    "запомни имя Dan",
    "покажи историю",
    "открой дискорд",
    "закрой процесс notepad",
    "создай файл заметки.txt",
    "найди проекты",
    "громкость 50",
    "игровая статистика",
    "выключи компьютер",
    "нарисуй круг",
    "браузер выбери opera gx",
    "заметки найди проект",
    "что такое гравитация",
    "exit",
  ]) {
    await expect(panel.locator(".cmd__text", { hasText: command }).first()).toBeVisible();
  }

  // Сноски групп: рисование — только Python-редакция, консоль — не чат,
  // MCP-плагины — про config/mcp.json.
  await expect(panel.getByText("только Python-редакция")).toBeVisible();
  await expect(panel.getByText("только в окне консоли ZERE, не в чате")).toBeVisible();
  await expect(
    panel.getByText("плагин MCP; нужен Python-бэкенд и включение в config/mcp.json"),
  ).toBeVisible();

  // Лог и композер никуда не делись.
  await expect(page.getByText("Начните диалог")).toBeVisible();
  await expect(page.getByPlaceholder("Спросите ZERE…")).toBeVisible();
});

test("команды: нажатие подставляет команду в поле ввода, а не отправляет её", async ({
  page,
}) => {
  await page.goto("/chat");

  await page.locator(".cmd", { hasText: "громкость 50" }).click();

  const input = page.getByPlaceholder("Спросите ZERE…");
  await expect(input).toHaveValue("громкость 50");
  await expect(input).toBeFocused();
  await expect(page.locator(".msg")).toHaveCount(0);
});

test("команды: поиск фильтрует список и прячет пустые группы", async ({ page }) => {
  await page.goto("/chat");

  const panel = page.locator(PANEL);
  const search = panel.getByPlaceholder("Поиск команды…");

  await search.fill("громче");

  // Находится команда увеличения громкости из группы «Громкость».
  await expect(panel.locator(".cmd__text", { hasText: "сделай громче" })).toBeVisible();
  await expect(panel.locator(".cmd__text", { hasText: "покажи память" })).toHaveCount(0);

  const filtered = await panel.locator(".cmd").count();
  expect(filtered).toBeGreaterThan(0);
  expect(filtered).toBeLessThan(10);

  // Несуществующий запрос — честное пустое состояние вместо пустых групп.
  await search.fill("щщщ-нет-такой-команды");
  await expect(panel.locator(".cmd")).toHaveCount(0);
  await expect(panel.getByText("Ничего не найдено — попробуйте другой запрос")).toBeVisible();

  // Сброс поиска возвращает весь каталог.
  await search.fill("");
  await expect(panel.locator(".cmd")).toHaveCount(68);
});

test("команды: свёрнутая панель запоминается между заходами", async ({ page }) => {
  await page.goto("/chat");

  const panel = page.locator(PANEL);
  const body = panel.locator(".chat__commands-body");
  const head = panel.locator(".chat__commands-head");

  await expect(body).toBeVisible();
  await expect(head).toHaveAttribute("aria-expanded", "true");

  await head.click();
  await expect(body).toBeHidden();
  await expect(head).toHaveAttribute("aria-expanded", "false");

  // Сворачивание переживает перезагрузку (localStorage), заголовок виден.
  await page.reload();
  await expect(page.locator(`${PANEL} .chat__commands-body`)).toBeHidden();
  await expect(page.locator(`${PANEL} .chat__commands-title`)).toBeVisible();

  // Возвращаем развёрнутый вид — состояние по умолчанию для новых сессий.
  await page.locator(`${PANEL} .chat__commands-head`).click();
  await expect(page.locator(`${PANEL} .chat__commands-body`)).toBeVisible();
});

test("команды: английский интерфейс переводит пояснения, но не сами команды", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.setItem("zere-lang", "en"));
  await page.goto("/chat");

  const panel = page.locator(PANEL);
  await expect(panel.locator(".chat__commands-title")).toHaveText("ZERE commands");
  await expect(panel.getByText("Games", { exact: true })).toBeVisible();
  await expect(panel.getByText("Python edition only", { exact: true })).toBeVisible();
  await expect(panel.getByText("Mute the sound", { exact: true })).toBeVisible();

  // Пример команды остаётся русским: движок понимает именно эту формулировку.
  await expect(panel.locator(".cmd__text", { hasText: "выключи звук" })).toBeVisible();
});
