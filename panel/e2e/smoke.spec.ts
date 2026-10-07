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

  await page.getByPlaceholder("Спросите ZERE…").fill("привет");
  await page.getByRole("button", { name: "Отправить" }).click();

  await expect(page.locator(".msg--assistant")).toContainText("ответ: привет", {
    timeout: 15_000,
  });
});

test("настройки: правка конфига сохраняется через API", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.locator(TITLE)).toHaveText("Настройки");

  // Уникальное значение — иначе повторный прогон не сделает черновик «грязным».
  const name = `ZERE E2E ${Date.now()}`;
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

test("ИИ: экран подключения показывает рабочую локальную модель", async ({ page }) => {
  await page.goto("/ai");
  await expect(page.locator(TITLE)).toHaveText("Подключение ИИ");

  // Фейк-сервер: ключа нет, Ollama «запущена» с моделью qwen3.5:2b.
  const status = page.locator(".card", { hasText: "Состояние подключения" });
  await expect(status).toContainText("Подключено: локальная модель", { timeout: 15_000 });

  const local = page.locator(".card", { hasText: "Локальная модель (Ollama" });
  await expect(local).toContainText("Локальная модель доступна");
  await expect(local).toContainText("запущен");
  await expect(local).toContainText("загружена");
});

test("ИИ: ключ проверяется, показывается маской и удаляется", async ({ page }) => {
  await page.goto("/ai");
  await expect(page.locator(TITLE)).toHaveText("Подключение ИИ");

  const cloud = page.locator(".card", { hasText: "Свой API-ключ (облачная модель)" });
  const keyInput = cloud.locator('input[type="password"]');

  // Полного ключа в интерфейсе нет и поле всегда пустое.
  await expect(keyInput).toHaveValue("");

  await keyInput.fill("sk-live-e2e-abcdefghijklmnop");

  await cloud.getByRole("button", { name: "Проверить ключ" }).click();
  await expect(page.locator(".toast").last()).toContainText("Ключ рабочий", { timeout: 15_000 });

  await cloud.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.locator(".toast").last()).toContainText("API-ключ сохранён", {
    timeout: 15_000,
  });

  // Наружу — только маска, поле ввода остаётся пустым.
  await expect(cloud).toContainText("sk-...mnop");
  await expect(cloud.locator('input[type="password"]')).toHaveValue("");

  // Убираем ключ: смоук идемпотентен на переиспользуемом сервере E2E.
  await cloud.getByRole("button", { name: "Удалить ключ" }).click();
  await expect(page.locator(".toast").last()).toContainText("API-ключ удалён", { timeout: 15_000 });
  await expect(cloud).toContainText("ключ не найден");
});

test("ИИ: сервер старее панели — просим перезапустить ZERE, а не ошибку", async ({ page }) => {
  // Ситуация «dist обновился, процесс ZERE — старый»: /api/ai ещё нет,
  // /api/update уже есть. Панель обязана объяснить, что делать.
  await page.route("**/api/ai", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ code: "NOT_FOUND", message: "Маршрут не найден." }),
    }),
  );

  await page.goto("/ai");
  await expect(page.getByText("Нужен перезапуск ZERE")).toBeVisible();
  await expect(page.getByText("Маршрут не найден")).toHaveCount(0);

  // Пункт меню не прячем: после перезапуска экран заработает.
  await expect(page.locator('.nav-item[title="Подключение ИИ"]')).toBeVisible();
});

test("ИИ: C#-редакция — пункт меню скрыт и понятное объяснение", async ({ page }) => {
  // C#-панель отдаёт тот же panel/dist, но не умеет ни /api/ai, ни /api/update.
  const notFound = (route: import("@playwright/test").Route): Promise<void> =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ code: "NOT_FOUND", message: "Маршрут не найден." }),
    });

  await page.route("**/api/ai", notFound);
  await page.route("**/api/update", notFound);

  await page.goto("/");
  await expect(page.locator('.nav-item[title="Подключение ИИ"]')).toBeHidden();

  // Дашборд показывает фактическое состояние локальной модели (в фейке E2E
  // Ollama «недоступна») и объясняет разницу редакций.
  const card = page.locator(".card", { hasText: "ИИ и модель" });
  await expect(card).toContainText("только локальная модель");
  await expect(card).toContainText("Python-редакции");
  await expect(card).toContainText("Локальная модель недоступна");
  await expect(page.locator(".shell__status")).toContainText("ИИ: только локально");

  // Прямой заход по URL — тоже понятный текст, без «Маршрут не найден».
  await page.goto("/ai");
  await expect(page.getByText("В этой редакции настраивается только локальная модель")).toBeVisible();
  await expect(page.getByText("Маршрут не найден")).toHaveCount(0);
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

test("голос: режим включается и выключается тумблером (POST /api/voice/mode)", async ({ page }) => {
  await page.goto("/voice");
  await expect(page.locator(TITLE)).toHaveText("Голос");

  const card = page.locator(".card", { hasText: "Режим голоса" });
  await expect(card.getByText("Состояние режима")).toBeVisible();

  const toggle = card.locator("label.toggle input");
  const pill = card.locator(".status-pill__value");

  // Фейк-сервер: wake word включён → сразу «ждёт слова-триггера».
  // Кликаем по label (input перекрыт toggle__track — check() не дойдёт).
  await expect(pill).toHaveText("выключен");
  await card.locator("label.toggle").click();
  await expect(toggle).toBeChecked({ timeout: 10_000 });
  await expect(pill).toHaveText("ждёт «зере»", { timeout: 10_000 });

  await card.locator("label.toggle").click();
  await expect(toggle).not.toBeChecked({ timeout: 10_000 });
  await expect(pill).toHaveText("выключен", { timeout: 10_000 });
  await expect(page.locator(".toast").last()).toContainText("Голосовой режим выключен");
});

test("дашборд: карточка «Обновления» и переход на экран", async ({ page }) => {
  await page.goto("/");

  const card = page.locator(".card", { hasText: "Обновления" });
  await expect(card).toBeVisible();

  // Значение зависит от состояния фейка («есть коммит» / «уже обновлено»):
  // сервер E2E переиспользуется между прогонами (reuseExistingServer).
  await expect(card.locator(".status-pill__value").first()).toHaveText(
    /\+1 коммитов|актуальная версия/,
  );

  await card.getByRole("button", { name: "Открыть обновления" }).click();
  await expect(page).toHaveURL(/\/update$/);
});

test("обновления: состояние ветки из /api/update", async ({ page }) => {
  await page.goto("/update");
  await expect(page.locator(TITLE)).toHaveText("Обновления");

  // Фейк-сервер: ветка python-port, локальный и удалённый коммит различны.
  const status = page.locator(".card", { hasText: "Состояние" });
  await expect(status).toContainText("origin/python-port");
  await expect(status).toContainText("aaaaaaa · Текущий коммит (фейк)");
  await expect(status).toContainText("bbbbbbb · Новый коммит (фейк)");
  await expect(page.locator(".card", { hasText: "Новые коммиты" })).toBeVisible();
});

test("обновления: кнопка применяет обновление и требует перезапуск", async ({ page }) => {
  // Идёт последним в файле: применение меняет состояние фейка на сервере,
  // общем для всех тестов (fullyParallel: false — порядок объявления).
  await page.goto("/update");

  const apply = page.getByRole("button", { name: "Обновить сейчас" });
  if (!(await apply.isEnabled())) {
    test.skip(true, "обновление уже применено на переиспользованном сервере E2E");
  }

  await apply.click();

  await expect(page.locator(".toast").first()).toContainText("Обновление применено", {
    timeout: 15_000,
  });

  // После применения обновлений нет, показан результат с требованием перезапуска.
  await expect(page.locator(".card", { hasText: "Последнее обновление" })).toContainText(
    "закройте и снова запустите ZERE",
    { timeout: 15_000 },
  );
  await expect(page.getByRole("button", { name: "Обновить сейчас" })).toBeDisabled();
});
