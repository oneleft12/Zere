import { defineConfig } from "@playwright/test";

/**
 * E2E-смок (этап 5 плана): сервер поднимает tests/e2e_server.py —
 * фейковые сервисы и детерминированные данные из контрактных тестов,
 * без Ollama/микрофона/сети. Статика — собранный panel/dist.
 *
 * Запуск: `npm run test:e2e` в panel/ (сервер стартует сам).
 *
 * Linux без root: браузеру нужны libnspr4/libnss3/libasound2. Если
 * `npx playwright install-deps` недоступен (нужен sudo) — распакуйте
 * соответствующие .deb локально и запустите с
 * LD_LIBRARY_PATH=<каталог>/usr/lib/x86_64-linux-gnu.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:8099",
    locale: "ru-RU",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python3 ../tests/e2e_server.py",
    url: "http://127.0.0.1:8099/",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
