# Архитектура ZERE

Документ описывает **обе редакции** проекта — Python (`zere/`, `main.py`) и
C# (.NET 10, `ZERE.*`). Ведущая редакция — **Python**: в ней появляются новые
подсистемы (конспектор, рисование, MCP-плагины, роутер Jev, обновление,
голосовой режим), она же запускается приложением `zere.exe`. C#-редакция
поддерживается (сборка, контракт панели, ИИ, голос), новые подсистемы в неё не
портируются.

## Слои

```
App (zere.exe / main.py / ZERE.App)
 ├── Desktop (zere/desktop)                — окно pywebview, stdio, диалоги
 ├── API (zere/api, ZERE.App/Api)          — локальная панель, HTTP-контракт
 ├── Core (zere/core, ZERE.Core)           — engine, конвейер, плагины, MCP,
 │                                           конспектор, роутер Jev, обновление
 ├── AI (zere/ai, ZERE.AI)                 — облачный ключ или локальная модель
 ├── Memory (zere/memory, ZERE.Memory)     — SQLite: память и история
 ├── Tools (zere/tools, ZERE.Tools)        — приложения, файлы, процессы,
 │                                           громкость, игры, рисование
 └── Voice (zere/voice, ZERE.Voice)        — STT (GigaAM→Whisper), TTS
                                             (Silero/Pocket), KWS
```

## Конвейер обработчиков

Порядок важен: локальные команды обрабатывает код, и только неизвестное
уходит в LLM.

```
MemoryHandler → MemoryQueryHandler → ConversationHandler → ProcessHandler
→ WindowsHandler → FileHandler → ConspectHandler → GameHandler → VolumeHandler
→ DrawingHandler → [JevRouter] → PluginCommandHandler → AIHandler (fallback)
```

- Обработчик объявляет `can_handle()` и возвращает ответ из `handle()`;
  `None` означает «я не смог» → следующий обработчик (например, вопрос к
  памяти без ответа уходит в LLM).
- Сбой одного обработчика логируется и не останавливает конвейер
  (`HandlerPipeline`).
- Роутер Jev встаёт между локальными обработчиками и LLM и только при
  настроенном ключе (`docs/JEV_ROUTER.md`).
- `ZereEngine.process()` — единственная точка входа реплики: извлечение
  фактов, конвейер, сохранение истории. Вызывается из консоли, панели и
  голосового режима; доступ сериализован блокировкой.

## Панель

- HTTP только на `127.0.0.1`, проверка `Host`/`Origin`, заголовок
  `X-ZERE-Token` из `config/panel.token` (`hmac.compare_digest`).
- Контракт — `docs/api/openapi.yaml`, 32 маршрута Python-редакции.
  C#-редакция реализует 27 (без `/api/update*` и `/api/plugins/mcp*`).
- Необратимые действия (питание, kill, удаление файла) — двухшаговые:
  `SafeActionManager` с TTL 60 с и одноразовыми челленджами.
- Фронтенд — `panel/src` (Vite + TypeScript), сборка `panel/dist`
  коммитится, CI проверяет её свежесть. Фронтенд определяет возможности
  бэкенда на лету (старая сборка скрывает пункты меню).

## Данные

| Что | Где |
|---|---|
| Память и история | `zere.db` (SQLite; старая `jarvis.db` переименовывается) |
| Настройки | `config/config.json`, `config/plugins.json` |
| Секреты | `config/ai.json`, `config/router.json`, `config/panel.token` (0600/`icacls`, в API — только маска) |
| Журналы | `logs/` (ключи маскируются `redact_secrets`) |
| Модели и голос | `ZERE.Voice/Models`, `ZERE.Voice/Silero`, `voice/` |
| Данные приложения | `data/` (профиль WebView2 и т. п.) |

## Голос

- **STT:** GigaAM-v3 (sherpa-onnx, русский с пунктуацией) → откат Whisper
  (faster-whisper). Модель GigaAM качается при установке/первом запуске.
- **TTS:** Silero v5 (русский, единственный движок Python-редакции) и
  PocketTTS (клонирование голоса, C#). ChatTTS удалён в 1.9.0. C#-хелпер
  `ZERE.Speaker` делает DSP и вывод звука; при его отсутствии Python
  озвучивает сам.
- **Слово-триггер:** стриминговый KWS на ONNX (`wake_*.onnx`) → откат на
  прежний детектор (VAD + STT). `docs/WAKE_WORD.md`.
- Тяжёлая часть Silero вынесена в HTTP-сайдкар (`tools/zere_silero_server.py`)
  и поднимается через `uv`.

## ИИ

`AiService` выбирает провайдера на каждый запрос: облачный ключ пользователя
(любой OpenAI-совместимый API) или локальная модель (Ollama). Режимы —
`auto | cloud | local`. Ключ в панели показывается маской, права файла сужены,
секреты вычищаются из логов. Язык ответа (`ru|en`) берётся из
`config/config.json` и меняет правило системного промпта и заголовки блоков.
`docs/AI_PROVIDERS.md`.

## Безопасность

- Только loopback, токен панели, TTL-подтверждения, denylist системных
  процессов, path traversal закрыт в файловых операциях и статике.
- MCP-серверы — подпроцессы с правами пользователя (не песочница): allowlist
  инструментов и точная команда запуска в `docs/MCP_PLUGINS.md`.
- Обновление — только `git pull --ff-only` в чистой копии; данные не
  перезаписываются.

## Точки расширения

**Новый обработчик (Python):** класс с `can_handle`/`handle` в
`zere/core/handlers/`, регистрация в `zere/core/services.py`
(`_create_handler_pipeline`), тест в `tests/test_core_handlers.py`.

**Новый тип команды:** значение в `*CommandType`, разбор в `*CommandRouter`,
ветка в обработчике.

**Новый инструмент:** модуль в `zere/tools/<область>/`, вызов из обработчика,
тест без Windows-зависимостей (фейки вместо реестра/COM).

**Плагин:** `ICommandHandlerPlugin` — `.py` в `plugins/` (Python) или `.dll`
(C#); MCP-сервер — запись в `config/mcp.json` без правки кода.

**C#-паритет:** при изменении контракта панели обновите
`ZERE.App/Api/PanelServer.cs` и `docs/api/openapi.yaml`; контрактные тесты
гоняются против обеих редакций в CI.

## Тесты и CI

- `pytest tests` — 890+ тестов, тяжёлые пакеты подменяются фейками;
  достаточно `requirements-dev.txt`.
- Покрытие контролируется `--cov-fail-under` в CI.
- `scripts/check_port.py` — AST-контракт порта C# → Python.
- CI: панель (typecheck + сборка + свежесть `dist`), Playwright E2E, Python
  (ruff, compileall, check_port, весь pytest с покрытием), C# (сборка +
  контракт панели на фейковом провайдере).

Подробности по подсистемам — в `docs/` (`CONSPECT.md`, `MCP_PLUGINS.md`,
`JEV_ROUTER.md`, `DRAWING.md`, `TTS_SILERO.md`, `WAKE_WORD.md`, `UPDATE.md`,
`AI_PROVIDERS.md`, `DESKTOP_APP.md`, `INSTALL.md`).
