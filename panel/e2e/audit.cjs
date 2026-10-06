/**
 * Расширенный аудит панели ZERE в реальном браузере (ручной прогон, вне CI).
 *
 * Дополняет e2e/smoke.spec.ts: 11 экранов, XSS-инъекции, пустой/длинный ввод,
 * UTF-8 и эмодзи, две вкладки, тема, i18n, мобильное разрешение 390x844,
 * обрыв связи (SIGKILL сервера) и автовосстановление статус-строки.
 *
 * Запуск (сервер поднимает и перезапускает сам скрипт на порту 8101):
 *   cd panel
 *   NODE_PATH=$PWD/node_modules node e2e/audit.cjs
 *
 * На Linux браузеру нужны libnspr4/libnss3/libasound2 (см. playwright.config.ts);
 * при отсутствии прав root их можно распаковать в каталог и передать
 * LD_LIBRARY_PATH=<каталог>/usr/lib/x86_64-linux-gnu.
 *
 * В CI не включён осознанно: сценарий убивает и поднимает сервер (Playwright
 * webServer этого не переживёт) и ждёт два цикла опроса статуса по 20 с.
 */
/**
 * Проверка панели ZERE в реальном браузере (Chromium):
 * экраны, XSS, пустой/длинный ввод, кодировка, две вкладки, мобильное
 * разрешение, тема, i18n, обрыв связи и автовосстановление.
 *
 * Запуск: cd panel && LD_LIBRARY_PATH=... node /tmp/ui_check.cjs
 */
const { chromium } = require("@playwright/test");
const { spawn } = require("child_process");
const http = require("http");

const PORT = 8101;
const BASE = `http://127.0.0.1:${PORT}`;
const REPO = "/mnt/c/Projects/Jarvis";
const results = [];

function check(name, ok, detail = "") {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} | ${name}${detail ? " | " + detail : ""}`);
}

function spawnServer() {
  return spawn("python3", ["tests/e2e_server.py"], {
    cwd: REPO,
    env: { ...process.env, E2E_PORT: String(PORT) },
    stdio: "ignore",
  });
}

function ping() {
  return new Promise((resolve) => {
    const req = http.get(BASE + "/", (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function waitReady(ms = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (await ping()) return true;
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}

async function waitContains(locator, needle, ms = 15000) {
  const t0 = Date.now();
  let last = "";
  while (Date.now() - t0 < ms) {
    last = await locator.innerText().catch(() => "");
    if (last.includes(needle)) return true;
    await new Promise((r) => setTimeout(r, 200));
  }
  return last;
}

async function waitStatus(page, needle, ms = 30000) {
  const t0 = Date.now();
  let text = "";
  while (Date.now() - t0 < ms) {
    text = await page.locator(".shell__status").innerText();
    if (text.includes(needle)) return true;
    await new Promise((r) => setTimeout(r, 700));
  }
  return `не дождались «${needle}», статус: ${text}`;
}

async function main() {
  let server = spawnServer();
  if (!(await waitReady())) throw new Error("сервер не поднялся");

  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: "ru-RU" });
  const page = await ctx.newPage();

  const consoleErrors = [];
  const pageErrors = [];
  let dialogFired = null;
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  page.on("dialog", async (d) => {
    dialogFired = d.message();
    await d.dismiss();
  });

  // --- 1. Открытие панели и статус подключения -------------------------
  await page.goto(BASE + "/");
  await page.waitForSelector(".shell__title");
  check("панель открылась, заголовок есть", (await page.locator(".shell__title").innerText()) === "Дашборд");

  const statusOk = await waitStatus(page, "Ollama", 20000);
  check("статус-строка: связь с сервером (health)", statusOk === true, statusOk === true ? "" : String(statusOk));

  const metas = await page.evaluate(() => ({
    token: document.querySelector('meta[name="zere-token"]')?.content || "",
    title: document.title,
  }));
  check("токен подставлен сервером в HTML", metas.token.length === 64);
  check("заголовок вкладки задан", metas.title.length > 0, metas.title);

  // --- 2. Все экраны ---------------------------------------------------
  const screens = [
    ["/", "Дашборд"], ["/chat", "Чат"], ["/history", "История"], ["/memory", "Память"],
    ["/voice", "Голос"], ["/processes", "Процессы"], ["/apps", "Приложения"],
    ["/plugins", "Плагины"], ["/logs", "Логи"], ["/settings", "Настройки"],
    ["/personalities", "Личности"],
  ];
  let screensOk = 0;
  for (const [path, title] of screens) {
    await page.goto(BASE + path);
    try {
      await page.waitForSelector(".page-header__title", { timeout: 8000 });
      const got = await page.locator(".page-header__title").innerText();
      if (got.trim() === title) screensOk++;
      else console.log(`  экран ${path}: заголовок «${got}» вместо «${title}»`);
    } catch (e) {
      console.log(`  экран ${path}: ошибка ${e.message.split("\n")[0]}`);
    }
  }
  check(`все 11 экранов открываются (${screensOk}/11)`, screensOk === 11);

  // --- 3. Чат: ответ, XSS, пустой ввод, кодировка ----------------------
  const bubbles = () => page.locator(".msg--assistant");
  async function send(text) {
    await page.getByPlaceholder("Спросите ZERE…").fill(text);
    await page.getByRole("button", { name: "Отправить" }).click();
  }

  await page.goto(BASE + "/chat");
  await send("Привет, Зере!");
  const firstAns = await waitContains(bubbles().first(), "ответ: Привет, Зере!");
  check("ответ агента отображается в панели", firstAns === true, firstAns === true ? "" : String(firstAns));

  const before = await page.locator(".msg").count();
  await page.getByRole("button", { name: "Отправить" }).click(); // пустое поле
  await page.waitForTimeout(800);
  check("пустой ввод не отправляется", (await page.locator(".msg").count()) === before);

  await send("<script>alert(1)</script>");
  await page.waitForTimeout(1500);
  const xssText = await bubbles().last().innerText();
  check("XSS: диалог alert не вызван", dialogFired === null, dialogFired || "");
  check("XSS: payload показан как текст", xssText.includes("<script>alert(1)</script>"));
  const scriptsInDom = await page.evaluate(() => document.querySelectorAll(".msg script").length);
  check("XSS: тег script не попал в DOM", scriptsInDom === 0);

  await send("<img src=x onerror=alert(2)>");
  await page.waitForTimeout(1200);
  const imgsInDom = await page.evaluate(() => document.querySelectorAll(".msg img").length);
  check("XSS: img из ввода не создан в DOM", imgsInDom === 0 && dialogFired === null);

  const tricky = "Привет, Зере! ёЁйЦукен «кавычки» ‘апостроф’ 🚀";
  await send(tricky);
  await page.waitForTimeout(1500);
  const trickyEcho = await bubbles().last().innerText();
  check("UTF-8/эмодзи/кавычки не искажаются", trickyEcho.includes(tricky), trickyEcho.slice(0, 60));

  const sql = "' OR 1=1; DROP TABLE memories; --";
  await send(sql);
  await page.waitForTimeout(1500);
  check("SQL-подобный ввод не ломает панель", (await bubbles().last().innerText()).includes("OR 1=1"));

  const longText = "д".repeat(4000);
  await send(longText);
  await page.waitForTimeout(4000);
  const longOk = (await bubbles().last().innerText()).length >= 4000;
  const noOverflow = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  check("длинный текст (4000) обработан", longOk);
  check("длинный текст не рвёт вёрстку (нет горизонтального скролла)", noOverflow);

  const dup = await page.locator(".msg--assistant").count();
  const uniq = await page.evaluate(() => new Set([...document.querySelectorAll(".msg--assistant")].map((e) => e.textContent)).size);
  check("нет дублирования сообщений", dup === uniq, `бабблов=${dup}, уникальных=${uniq}`);

  // --- 4. Две вкладки --------------------------------------------------
  const page2 = await ctx.newPage();
  await page2.goto(BASE + "/chat");
  await page2.getByPlaceholder("Спросите ZERE…").fill("вторая вкладка");
  await page2.getByRole("button", { name: "Отправить" }).click();
  await page2.locator(".msg--assistant").first().waitFor({ timeout: 15000 });
  const tabAns = await waitContains(page2.locator(".msg--assistant").first(), "ответ: вторая вкладка");
  check("несколько вкладок работают одновременно", tabAns === true, tabAns === true ? "" : String(tabAns));
  await page2.close();

  // --- 5. Тема ---------------------------------------------------------
  await page.goto(BASE + "/");
  const themeBefore = await page.evaluate(() => document.documentElement.dataset.theme);
  await page.locator('button[aria-label="Переключить тему"]').click();
  const themeAfter = await page.evaluate(() => document.documentElement.dataset.theme);
  await page.reload();
  const themeReload = await page.evaluate(() => document.documentElement.dataset.theme);
  check("переключение темы работает и переживает перезагрузку", themeBefore !== themeAfter && themeReload === themeAfter, `${themeBefore}→${themeAfter}→${themeReload}`);
  await page.locator('button[aria-label="Переключить тему"]').click(); // обратно

  // --- 6. i18n ---------------------------------------------------------
  await page.goto(BASE + "/settings");
  const langSelect = page.locator('select:has(option[value="en"])');
  await langSelect.selectOption("en");
  await page.reload();
  await page.goto(BASE + "/chat");
  const enTitle = await page.locator(".page-header__title").innerText();
  check("переключение языка на английский работает", enTitle === "Chat", enTitle);
  await page.goto(BASE + "/settings");
  await page.locator('select:has(option[value="ru"])').selectOption("ru");
  await page.reload();

  // --- 7. Обрыв связи и автовосстановление -----------------------------
  const errorsBeforeOutage = consoleErrors.length;
  server.kill("SIGKILL");
  await new Promise((r) => setTimeout(r, 500));
  const offline = await waitStatus(page, "не отвечает", 30000);
  check("при падении сервера панель показывает «не отвечает»", offline === true, offline === true ? "" : String(offline));

  server = spawnServer();
  if (!(await waitReady())) throw new Error("сервер не перезапустился");
  const online = await waitStatus(page, "Ollama", 30000);
  check("после перезапуска сервера панель восстанавливается сама", online === true, online === true ? "" : String(online));

  await page.goto(BASE + "/chat");
  await send("после перезапуска");
  await page.locator(".msg--assistant").first().waitFor({ timeout: 15000 });
  const afterAns = await waitContains(page.locator(".msg--assistant").first(), "ответ: после перезапуска");
  check("после восстановления команды снова работают", afterAns === true, afterAns === true ? "" : String(afterAns));

  // --- 8. Мобильное разрешение ----------------------------------------
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "ru-RU" });
  const mpage = await mobile.newPage();
  await mpage.goto(BASE + "/chat");
  await mpage.waitForSelector(".shell__title");
  const mobileOverflow = await mpage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const inputVisible = await mpage.getByPlaceholder("Спросите ZERE…").isVisible();
  check("мобильное разрешение 390x844: без горизонтального переполнения", mobileOverflow <= 1, `overflow=${mobileOverflow}px`);
  check("мобильное разрешение: поле ввода доступно", inputVisible);
  await mpage.getByPlaceholder("Спросите ZERE…").fill("мобильный ввод");
  await mpage.getByRole("button", { name: "Отправить" }).click();
  const mobileAns = await waitContains(mpage.locator(".msg--assistant").first(), "ответ: мобильный ввод");
  check("мобильное разрешение: отправка работает", mobileAns === true, mobileAns === true ? "" : String(mobileAns));
  await mobile.close();

  // --- 9. Консоль браузера --------------------------------------------
  const errorsAfter = consoleErrors.filter((t) => !t.includes("Failed to load resource"));
  check("нет ошибок JS в консоли (без учёта ожидаемого обрыва сети)", errorsAfter.length === 0, errorsAfter.slice(0, 3).join(" | "));
  check("нет необработанных исключений страницы", pageErrors.length === 0, pageErrors.slice(0, 2).join(" | "));
  console.log(`  (всего console.error, включая ошибки сети во время имитации обрыва: ${consoleErrors.length}; до обрыва: ${errorsBeforeOutage})`);

  await browser.close();
  server.kill("SIGKILL");

  const failed = results.filter((r) => !r.ok);
  console.log(`\nИТОГО: ${results.length - failed.length}/${results.length} пройдено`);
  if (failed.length) console.log("ПРОВАЛЫ:\n" + failed.map((f) => ` - ${f.name} ${f.detail}`).join("\n"));
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error("ОШИБКА ПРОВЕРКИ:", e);
  process.exit(2);
});
