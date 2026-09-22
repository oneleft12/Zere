# Спецификация порта JARVIS с C# на Python

**Ветка:** `python-port`. Код C# остаётся в репозитории (для сравнения и отката) — не удалять, не модифицировать. Новый код пишется только в пакет `jarvis/` + `main.py` + `requirements.txt`.

## Общие правила

1. **Python 3.12+**, синхронный код (**без asyncio** — C# `async`-методы становятся обычными функциями).
2. **Имена классов — 1:1 как в C#** (`OllamaClient`, `HandlerPipeline`, `VolumeService`...). Интерфейсы сохраняют имена с `I` (`IJarvisHandler`, `IPlugin`, `IPersonalityPlugin`, `ICommandHandlerPlugin`, `IAppScanner`) — это осознанно для сквозного маппинга.
3. **Методы — pythonic, snake_case:** `CanHandle` → `can_handle`, `HandleAsync` → `handle`, `LoadAll` → `load_all`, `ProcessAsync` → `process`, `TranscribeAsync` → `transcribe`, `SpeakAsync` → `speak`. Суффиксы `Async` не использовать.
4. **Enum** → `enum.Enum` / `enum.StrEnum`. Свойства (properties) → атрибуты dataclass или getter-методы.
5. **Интерфейсы/абстракции** → `abc.ABC` + `@abstractmethod`.
6. **DTO/модели** → `@dataclass`.
7. **Все русские строки консоли/логов — дословно как в C#** (сохранять эмодзи и форматирование).
8. Логика, форматирование строк, порядок проверок — максимально близко к исходнику. Это **порт**, а не редизайн: не добавлять фичи, не менять поведение.
9. **Типизация:** аннотации типов во всех публичных функциях; `typing.Optional`/`| None`.
10. **Запрещено:** использовать `backups/`, менять C#-файлы, выполнять git-команды, создавать файлы вне своей подсистемы, использовать asyncio, DI-фреймворки (порт Microsoft.Extensions.DI — свой мини-контейнер в `jarvis/core/services.py`).
11. **Бинарники не копировать.** Ресурсы берём по существующим путям через `jarvis.paths` (см. ниже): модели Whisper, Piper, `config/config.json`, `jarvis.db`, `logs/`.
12. Каждый записанный файл **обязательно проверить**: `python3 -m py_compile <файл>`.

## Целевая структура (модульный маппинг)

```
main.py                                  ← JARVIS.App/Program.cs (пишет интегратор, не ты)
requirements.txt                         ← интегратор
jarvis/paths.py                          ← интегратор (уже есть): PROJECT_ROOT, config_path(), db_path(),
                                            logs_dir(), plugins_dir(), voice_dir()
jarvis/ai/
  ollama_client.py        OllamaClient           (JARVIS.AI/OllamaClient.cs)
  ollama_url_resolver.py  OllamaUrlResolver
  system_prompt.py        SystemPrompt
  models/ollama_stream_chunk.py  OllamaStreamChunk
jarvis/memory/
  database/memory_database.py          MemoryDatabase
  database/memory_repository.py        MemoryRepository
  database/conversation_repository.py  ConversationRepository
  models/memory_item.py                MemoryItem
  models/conversation.py               Conversation
  gaming/game_stats_database.py        GameStatsDatabase
  gaming/game_stats_repository.py      GameStatsRepository
  gaming/game_stat.py                  GameStat
jarvis/core/
  engine.py                JarvisEngine
  services.py              ServiceContainer + create_services()   (порт ServiceRegistration.cs)
  configuration/jarvis_config.py   JarvisConfig
  logging/log_service.py   LogService
  dependencies/dependency_checker.py  DependencyChecker, DependencyResult, CheckStatus
  context/{context_type,context_item,context_memory,context_service}.py
  ai/context_builder.py    ContextBuilder
  ai/prompt_builder.py     PromptBuilder
  handlers/{i_jarvis_handler,handler_pipeline,memory_handler,memory_query_handler,
            conversation_handler,process_handler,windows_handler,file_handler,
            game_handler,volume_handler,ai_handler,memory_extractor}.py
  plugins/interfaces/{plugin,personality_plugin,command_handler_plugin}.py  (IPlugin, IPersonalityPlugin, ICommandHandlerPlugin)
  plugins/base_plugin.py   BasePlugin
  plugins/plugin_manager.py  PluginManager
  plugins/plugin_config.py   PluginConfig
  plugins/builtin/personality/personality_plugin.py  PersonalityPlugin
  plugins/settings/settings_menu.py  SettingsMenu
jarvis/tools/
  applications/{app_alias_provider,application_launcher,registry_scanner,
                start_menu_scanner,app_paths_scanner,local_app_data_scanner,
                installed_app_scanner}.py
  applications/indexing/{i_app_scanner,app_info,app_index,universal_app_indexer}.py
  files/{file_command_type,file_command_router,file_manager}.py
  gaming/{game_session,game_tracker,game_guardian,game_catalog}.py + gaming/models/game_stat.py
  system/{process_command_type,process_command_router,process_manager,
          system_info_service,power_controller}.py
  windows/{process_info,process_service,process_command_type,process_command_router,
           windows_command_type,windows_command_router,file_controller,
           screen_capture_service,audio_controller,safe_action_manager,pending_action}.py
  windows/volume/{volume_command_type,volume_command_router,volume_service}.py
jarvis/voice/
  voice_manager.py   VoiceManager
  voice_config.py    VoiceConfig
  whisper/whisper_service.py  WhisperService
  piper/piper_service.py      PiperService
  wakeword/wake_word_detector.py  WakeWordDetector
  audio/{audio_recorder,audio_player,audio_preprocessor,audio_processor,
         continuous_audio_recorder}.py
```

Если в C#-исходнике в одном файле несколько типов — в Python тоже можно несколько типов в одном модуле (соблюдать маппинг выше).

## Зависимости (замены библиотек)

| C# | Python |
|---|---|
| `HttpClient` (Ollama) | `requests` (синхронно, stream-итерация) |
| `Microsoft.Data.Sqlite` | `sqlite3` (stdlib) |
| `Microsoft.Win32` (реестр) | `winreg` (stdlib, Windows) |
| `System.Management` (WMI) | `psutil`; если нужен редкий WMI-класс — пакет `wmi` (ленный импорт в теле функции) |
| `System.Diagnostics.Process` | `psutil` |
| `NAudio` (запись/воспроизведение WAV) | `sounddevice` (запись/воспроизведение PCM) + stdlib `wave` (чтение/запись WAV) |
| P/Invoke CoreAudio (громкость) | `pycaw` (+ `comtypes` если нужен COM напрямую) |
| `System.Drawing` (скриншот) | `mss` (захват) + `Pillow` (сохранение PNG) |
| `Whisper.net` (ggml) | `faster-whisper`: `WhisperModel(размер_или_путь, device="cpu", compute_type="int8")`; по умолчанию `"base"`; путь к локальной CT2-модели — из конфига. В комментарии указать, что ggml-base.bin whisper.cpp формата и faster-whisper сам скачает/или модель конвертируется. |
| Запуск `piper.exe` | как в C#: `subprocess` с поиском исполняемого в `jarvis.paths.voice_dir()/Piper` (логику FindPiperExecutable повторить) |
| P/Invoke питание (ExitWindowsEx и т.п.) | повторить через `ctypes.windll` если в исходнике P/Invoke; иначе `subprocess` |
| `Microsoft.Extensions.DependencyInjection` | мини-контейнер в `jarvis/core/services.py` |

Импорты Windows-only (`winreg`, `pycaw`, `comtypes`, `ctypes.windll`) — **на верхнем уровне модуля** (цель — Windows; не усложнять guard'ами).

## Ключевые контракты (сквозная совместимость)

- `JarvisConfig.load()` — classmethod, читает `jarvis.paths.config_path()`; поля как в C# (dataclass).
- `PluginConfig.load()` — аналогично, `config/plugins.json`.
- `LogService`: `info(msg)`, `error(msg)` (и остальные уровни по исходнику); пишет в `jarvis.paths.logs_dir()`.
- `OllamaClient(model, timeout_minutes)`: метод `generate(...)` с сигнатурой/поведением из C#-исходника (стриминг — генератор или callback, как удобнее синхронно), `close()` = IDisposable.
- `IJarvisHandler`: методы **ровно по сигнатуре из C#-исходника** (snake_case, без Async).
- `HandlerPipeline(process_message)` — принимает порядок/handlers как в C#.
- `JarvisEngine.process(message: str) -> str`.
- `ServiceContainer` в `jarvis/core/services.py`:
  - `add_singleton(instance)` / `add_singleton_factory(factory)`,
  - `get(cls) -> instance` (кэширует, вызывает factory),
  - `create_services() -> ServiceContainer` — воспроизводит `ServiceRegistration.Create()` **в том же порядке, с теми же фабриками** (реестр IJarvisHandler'ов: Memory, MemoryQuery, Conversation, Process, Windows, File, Game, Volume, AI).
  - Память БД: `MemoryDatabase()` должна инициализироваться при первом get (как `GetRequiredService<MemoryDatabase>` в Program.cs).
- `VoiceManager`: `initialize(personality_style)`, `listen()`, `listen_command()`, `speak(text)`, `wait_for_wake_word(cancel_event) -> bool`, `enable_wake_word()`, `set_personality_voice(style)`, `set_voice(...)`, `close()` (IDisposable); `config` — атрибут. Отмена (CancellationToken) → `threading.Event`.
- Пути: **только через `jarvis.paths`** (PROJECT_ROOT — корень репо, где лежат `config/`, `jarvis.db`, `JARVIS.Voice/`, `logs/`, `plugins/`).

## Проверка качества

1. `python3 -m py_compile` — все записанные файлы, без ошибок.
2. Самопроверка: каждый публичный класс/функция из твоего списка исходников — присутствует в Python-файле; сигнатуры методов не «утеряны».
3. Не создавать дубликаты типов, уже определённых в другой подсистеме (см. маппинг).
