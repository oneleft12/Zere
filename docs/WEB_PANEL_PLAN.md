# Web-панель ZERE

## Статус: РЕАЛИЗОВАНО (этапы 1–5 плана разработки GUI)

Документ описывает **фактическую** реализацию локальной веб-панели. План и статус
этапов — в `docs/GUI_DEVELOPMENT_PLAN.md`; контракт API — в `docs/api/openapi.yaml`.

## Обзор

Локальный HTTP-сервер + SPA в браузере/окне: `http://127.0.0.1:<port>` (порт из
конфигурации, обычно 8080). Панель запускается автоматически вместе с консолью
и открывается **отдельным окном приложения** (вариант B этапа 6: WebView2
поверх той же SPA, сворачивание в трей вместо закрытия; если WebView2 Runtime
недоступен — фолбэк в браузер). Команда `панель` / `panel` в консоли выводит
окно на передний план. Управление: диалог, память, история, голос, процессы,
приложения, плагины, личности, логи, настройки — 11 экранов.

**Защита** (урок TTS-сервера из отчёта-анализа):
- слушает только `127.0.0.1` (loopback-only);
- каждый API-запрос требует заголовок `X-ZERE-Token`
  (токен генерируется при старте, лежит в `config/panel.token`,
  UI читает его из `<meta name="zere-token">` при загрузке HTML);
- проверка заголовков `Origin` / `Host`;
- необратимые действия (kill, питание, очистка истории) — двойная защита:
  ConfirmDialog в UI **и** серверная проверка TTL-токена;
- пути статики нормализуются внутри `panel/dist` (path traversal невозможен).

## Архитектура (один контракт, две реализации)

| Слой | C# | Python |
|---|---|---|
| HTTP-сервер панели | `ZERE.App/Api/PanelServer.cs` | `zere/api/server.py` |
| Окно панели (этап 6) | `ZERE.App/Api/PanelWindow.cs` (WebView2 + трей) | pywebview (опционально), иначе браузер |
| Токен | `ZERE.App/Api/PanelToken.cs` | `zere/api/token.py` |
| Точка входа | `ZERE.App/Program.cs` (`--panel` — режим CI) | `main.py` |
| Статика SPA | `panel/dist` (общая для обеих) | та же |

Фронтенд **один** на обе реализации, поэтому контракт один на обе:
`docs/api/openapi.yaml` (20 путей), контрактные тесты гоняются против каждой
реализации одним и тем же набором.

## Фронтенд (`panel/`)

- **Стек:** Vite + vanilla TypeScript, без фреймворков; `npm run build` →
  `panel/dist` (коммитится — раздаётся сервером без Node).
- **Экраны:** Дашборд, Чат (SSE-стрим), История, Память, Голос, Процессы,
  Приложения, Плагины, Логи, Настройки, Личности.
- **Дизайн-система:** `src/ui.ts` (~17 компонентов), токены и темы в
  `src/styles/`; тёмная тема `#0A0E14` + cyan `#00E5FF`, светлая —
  переключателем; `prefers-reduced-motion`; только `textContent`
  (защита от XSS).
- **Доступность:** полная клавиатурная навигация, ловушка Tab и Escape
  в модалках, возврат фокуса.
- **i18n ru→en:** `src/i18n.ts` (ядро) + словари `src/i18n/<экран>.ts`,
  315 ключей; язык выбирается в «Настройках» (`localStorage`),
  применяется без перезагрузки.
- **Dev-режим:** `npm run dev` — Vite на 5173 проксирует `/api` на бэкенд,
  подставляя токен из `config/panel.token`.

## Запуск и сборка

```bash
# C#: консоль + панель (открывается окном приложения)
dotnet run --project ZERE.App

# Python
python main.py

# Режим CI (только API-ядро, без голоса/зависимостей)
dotnet run --project ZERE.App -- --panel     # C#
ZERE_PANEL_EXTERNAL=1 python tests/test_panel_api.py

# Фронтенд
cd panel
npm ci
npm run build      # typecheck + vite build → panel/dist
npm run dev        # dev-сервер с прокси на 8080
npm run test:e2e   # Playwright-смок (сервер стартует сам)
```

## Тесты и CI (`.github/workflows/ci.yml`)

| Джоба | Что делает |
|---|---|
| **panel** | `npm run build` (typecheck + сборка) + проверка, что `dist` в git свежий |
| **e2e** | Playwright-смок: дашборд → чат → настройки → i18n (5 тестов), сервер — `tests/e2e_server.py` (фейки, без Ollama/сети) |
| **python** | компиляция, AST-контракт порта (`scripts/check_port.py`), контрактные тесты (91), тесты P1-2 |
| **csharp** | `dotnet build ZERE.slnx` + те же 91 контрактный тест против C#-панели (`--panel`) |

Локальный прогон контрактных тестов: `python3 tests/test_panel_api.py`
(нужен только `pyyaml`).

## Структура

```
panel/
├── index.html            # meta zere-token → подставляется сервером
├── vite.config.ts        # dev-прокси /api → 127.0.0.1:8080 + токен
├── playwright.config.ts  # E2E (webServer: tests/e2e_server.py)
├── e2e/smoke.spec.ts     # смоук-сценарий приёмки
├── dist/                 # собранный SPA (коммитится, раздаётся сервером)
└── src/
    ├── main.ts           # точка входа: тема, язык, маршруты, статус-строка
    ├── shell.ts          # сайдбар, шапка, статус-строка
    ├── router.ts         # SPA-роутер (History API)
    ├── api.ts            # клиент API + SSE через fetch/ReadableStream
    ├── ui.ts             # дизайн-система (17 компонентов)
    ├── i18n.ts           # ядро локализации + CORE_EN
    ├── i18n/*.ts         # словари по экранам (315 ключей)
    ├── theme.ts, events.ts, styles/
    └── screens/*.ts      # 11 экранов
```
