# MCP-плагины ZERE: браузер и заметки

**Что это:** два плагина-обработчика, которые дают ZERE инструменты внешних
MCP-серверов (Model Context Protocol) — управление браузером и работу с
заметками Obsidian. Плюс минимальный MCP-клиент в ядре, на котором они стоят.

**Дата:** 14 октября 2026. **Редакция:** Python. Паритет C# — не сделан, см. §8.

---

## 1. Что появилось

| Компонент | Где | Назначение |
|---|---|---|
| MCP-клиент | `zere/core/mcp/client.py` | stdio + JSON-RPC 2.0: `initialize` → `tools/list` → `tools/call` |
| Настройки MCP | `zere/core/mcp/config.py`, `config/mcp.json` | какие серверы запускать и с какими правами |
| Плагин браузера | `zere/core/plugins/builtin/mcp/playwright_plugin.py` | `@playwright/mcp` — 25 инструментов |
| Плагин заметок | `zere/core/plugins/builtin/mcp/obsidian_plugin.py` | `seekstone` — 25 инструментов |
| Общая основа | `zere/core/plugins/builtin/mcp/mcp_plugin_base.py` | ленивый запуск, разбор команд, ответы |
| Мост в конвейер | `zere/core/handlers/plugin_handler.py` | сообщение → плагины-обработчики |

**Попутно закрыт пункт P1-3 аудита** — плагины-обработчики вообще не работали:

- `PluginCommandHandler` встроен в конвейер (после локальных обработчиков,
  перед `AIHandler`): раньше `ICommandHandlerPlugin` загружался, попадал в
  счётчик панели и не получал ни одного сообщения;
- починен загрузчик внешних Python-плагинов: `obj.__module__ == module`
  сравнивал строку с объектом модуля и был всегда ложным
  (`zere/core/plugins/plugin_manager.py`);
- список встроенных модулей больше не привязан к модулю личности;
- `GET /api/plugins` → `handlersConnected` стал честным: он проверяет сам
  конвейер, а не факт загрузки плагинов.

---

## 2. Быстрый старт

**1. Node.js** (нужен для обоих серверов; проверено на Node 20 и 22):

```powershell
node --version   # если пусто — установите Node.js LTS
```

**2. Конфиг:** скопируйте образец и включите нужный сервер.

```powershell
copy config\mcp.example.json config\mcp.json
```

```json
{
  "servers": {
    "playwright": {
      "enabled": true,
      "command": "npx",
      "args": ["-y", "@playwright/mcp@0.0.83"],
      "startupTimeoutSeconds": 120
    },
    "obsidian": {
      "enabled": true,
      "command": "npx",
      "args": ["-y", "seekstone@0.22.1"],
      "env": { "SEEKSTONE_VAULT": "C:\\Users\\Вы\\Documents\\Obsidian" }
    }
  }
}
```

`config/mcp.json` в `.gitignore` — в нём локальные пути. Перезапустите ZERE.

**3. Браузер для Playwright** (один раз, ~150 МБ):

```powershell
npx playwright install chrome
```

**4. Проверка:** в чате панели или в консоли —

```
браузер инструменты
заметки инструменты
```

Сервер стартует лениво: до первой подходящей команды `npx` не запускается,
поэтому выключенный плагин не стоит ни памяти, ни времени на старте ZERE.

---

## 3. Команды

### Браузер (`браузер` / `browser`)

| Команда | Инструмент MCP |
|---|---|
| `браузер открой https://ya.ru` · `перейди на ya.ru` | `browser_navigate` |
| `браузер назад` | `browser_navigate_back` |
| `браузер снимок` · `что на странице` | `browser_snapshot` |
| `браузер найди Войти` | `browser_find` |
| `браузер клик e5` | `browser_click` |
| `браузер введи e3: привет` | `browser_type` |
| `браузер скриншот` | `browser_take_screenshot` |
| `браузер закрой` | `browser_close` |
| `браузер инструменты` | `tools/list` |
| `браузер: <инструмент> {json}` | любой инструмент напрямую |

**Клик и ввод работают в два шага.** Playwright MCP адресует элементы ссылками
из снимка (`e5`), а не текстом: сначала `браузер снимок` или `браузер найди
Войти` — сервер вернёт ссылки, затем `браузер клик e5`. Это ограничение
протокола, а не плагина; с tool calling шаг стал бы неявным.

### Заметки (`заметки` / `заметка` / `obsidian`)

| Команда | Инструмент MCP |
|---|---|
| `заметки найди покупки` · `найди в заметках покупки` | `search` |
| `заметки список` | `list_notes` |
| `заметки теги` | `list_tags` |
| `заметки прочитай ZERE.md` | `read_note` |
| `заметки создай Идеи.md: первый текст` | `create_note` |
| `заметки допиши Покупки.md: - сыр` | `append_note` |
| `заметки инструменты` | `tools/list` |
| `заметки: <инструмент> {json}` | любой инструмент напрямую |

Выдачу seekstone плагин переводит из JSON в читаемый текст: ответ читает
пользователь и озвучивает TTS, а не модель.

---

## 4. Как это работает без tool calling

Tool calling в ZERE нет, и делать его обязательным условием было бы ошибкой:
на модели 0.8b–2b и слабом CPU вызов инструментов ненадёжен. Поэтому плагин
разбирает фразу сам — тем же приёмом, что уже работает в роутере интентов Jev:
**интент определяет код, а не модель**.

Полный набор инструментов при этом доступен через форму
`<триггер>: <инструмент> {json}` — так не нужно придумывать русский синоним
под каждый из 25 инструментов.

Если tool calling когда-нибудь появится, эти же плагины можно будет
использовать как источник инструментов для модели: MCP-клиент уже отдаёт
`name`, `description` и `inputSchema` каждого инструмента.

---

## 5. Настройки `config/mcp.json`

| Поле | Смысл |
|---|---|
| `enabled` | включает сервер. По умолчанию `false` — установка плагина ничего не запускает |
| `command`, `args` | команда запуска. Пиньте версию (`@0.0.83`), а не `@latest` |
| `env` | переменные окружения сервера (например `SEEKSTONE_VAULT`) |
| `cwd` | рабочий каталог сервера |
| `requestTimeoutSeconds` | таймаут запроса (по умолчанию 60) |
| `startupTimeoutSeconds` | таймаут старта: `npx` в первый раз тянет пакет из сети (по умолчанию 60) |
| `allowedTools` | allowlist инструментов; пусто — разрешены все |

Читаются и snake_case-имена (`request_timeout_seconds`) — как в `config/ai.json`.

---

## 6. Безопасность

Плагин запускает **сторонний код** как подпроцесс с правами пользователя.
Официальная документация MCP прямо говорит, что это не песочница: сервер
наследует переменные окружения, видит файлы, доступные учётке, и может
открывать сетевые соединения. Поэтому:

- **по умолчанию всё выключено** — плагин инертен, пока сервер не включён в
  `config/mcp.json` явным `enabled: true`;
- **точная команда запуска** доступна для показа (`status()["command"]`,
  `McpStdioClient.argv`) — требование SEP-1024 для установки в один клик;
- **`allowedTools`** сужает набор инструментов сервера;
- **версии пиннятся** — `@latest` приносит чужой код в контекст без спроса;
- **ошибки не роняют конвейер**: сбой сервера превращается в текстовый ответ,
  а не в исключение (проверено тестами).

Чего пока нет и что стоит сделать перед маркетплейсом плагинов: подпись
пакетов, изоляция прав (ограничение каталога и сети), подтверждение
необратимых инструментов через `SafeActionManager`.

---

## 7. Тесты

```powershell
python -m pytest tests/test_mcp_client.py tests/test_mcp_plugins.py tests/test_plugin_pipeline.py -q
```

- `tests/fake_mcp_server.py` — фейковый MCP-сервер: обычная работа, ошибка
  инструмента, ошибка протокола, падение, таймаут, не-JSON в stdout,
  неподдерживаемая версия, запрос от сервера к клиенту;
- `tests/test_mcp_client.py` — handshake, `tools/list`, `tools/call`, все сбои,
  обёртка `cmd /c` для `npx.cmd` на Windows;
- `tests/test_mcp_plugins.py` — разбор фраз, инертность выключенного плагина,
  лазейка с JSON, allowlist, подсказки (браузер/хранилище не заданы);
- `tests/test_plugin_pipeline.py` — мост в конвейере, сбой плагина не заслоняет
  остальные, загрузка встроенных и внешних плагинов.

Живые серверы проверяются отдельно (нужны сеть и node):

```powershell
$env:ZERE_MCP_LIVE=1
$env:ZERE_MCP_LIVE_COMMAND="npx"
$env:ZERE_MCP_LIVE_ARGS="-y @playwright/mcp@0.0.83"
python -m pytest tests/test_mcp_client.py -q
```

**Проверено вживую:** `@playwright/mcp` 0.0.83 (25 инструментов,
`protocolVersion` 2025-11-25) и `seekstone` 0.22.1 (25 инструментов) —
handshake, список инструментов, вызов инструмента, ошибка отсутствующего
браузера. Отдельно проверена ветка Windows: `npx` → `npx.cmd` → `cmd /c`.

---

## 8. Ограничения и что дальше

1. **Паритета C# нет.** Плагины и MCP-клиент реализованы только в
   Python-редакции; C#-панель по-прежнему отдаёт `handlersConnected: false`.
   Для паритета нужны: MCP-клиент на `System.Diagnostics.Process`, мост
   `PluginCommandHandler` в `HandlerPipeline`, те же два плагина.
2. **Новая ревизия протокола (2026-07-28) не поддерживается** — она отказалась
   от handshake (версия в `_meta`, обязательный `server/discover`). Клиент
   работает с handshake-поколением, которое реализуют все существующие
   серверы; при несовместимости выдаётся понятная ошибка с версиями сервера.
3. **`browser_click`/`browser_type` требуют ссылку из снимка** — следствие
   отказа от tool calling.
4. **Нет управления серверами из панели**: включение — правкой
   `config/mcp.json`. Экран «Плагины» пока read-only.
5. **Озвучка длинных ответов**: снимок страницы может быть большим, поэтому
   ответы режутся (2000–2500 символов).

---

## 9. Источники

- [MCP: Lifecycle (ревизия 2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) — handshake `initialize` / `notifications/initialized`
- [MCP: Versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning) — «modern» и «legacy» поколения, `UnsupportedProtocolVersionError`
- [MCP: Local Server Security](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/local-server-security) — stdio не песочница, SEP-1024
- [Playwright MCP](https://playwright.dev/mcp/introduction) · npm `@playwright/mcp`
- [seekstone](https://www.npmjs.com/package/seekstone) — файловый Obsidian MCP без плагина и без запущенного приложения
- `docs/PLUGINS_RESEARCH.md` — почему выбран MCP и именно эти серверы
