# AGENTS.md

## Правила работы

1. **После каждой задачи — коммит и обязательный `git push`.** Коммит без push считается незавершённой задачей.
2. Коммиты делать на русском языке, кратко описывая суть.

---

## Описание проекта

**ZERE** — персональный AI-ассистент для Windows, написанный на C# (.NET 10).  
Работает через консоль, подключается к локальной LLM (Ollama) и управляет компьютером голосом или текстом.

### Структура решения (ZERE.slnx)

| Проект | Назначение |
|---|---|
| **ZERE.App** | Точка входа — консольное приложение |
| **ZERE.Core** | Ядро: engine, обработчики, маршрутизация намерений, конфигурация, контекст |
| **ZERE.AI** | Клиент Ollama (HTTP) для генерации ответов |
| **ZERE.Memory** | SQLite-память: воспоминания + история разговоров |
| **ZERE.Tools** | Инструменты: приложения, файлы, игры, Windows, система |
| **ZERE.Voice** | Голосовой ввод (GigaAM-v3, откат на Whisper) и вывод (Silero — русский, ChatTTS, PocketTTS-клонирование) |
| **ZERE.Speaker** | C#-хелпер озвучки: DSP + вывод звука (NAudio/WASAPI) для Python-редакции |

---

## Tools (инструменты)

### Applications (`ZERE.Tools/Applications/`)
- **ApplicationLauncher** — запуск приложений по имени
- **UniversalAppIndexer** — индексация установленных приложений
- **AppAliasProvider** — алиасы (например, «дискорд» → Discord)
- **Сканеры**: RegistryScanner, StartMenuScanner, AppPathsScanner, LocalAppDataScanner, InstalledAppScanner

### Files (`ZERE.Tools/Files/`)
- **FileManager** — создание папок/файлов, поиск, удаление на рабочем столе
- **FileCommandRouter** — парсинг файловых команд

### Gaming (`ZERE.Tools/Gaming/`)
- **GameTracker** — отслеживание времени в играх
- **GameGuardian** — определение запущенных игр
- **GameCatalog** — каталог игр

### Windows (`ZERE.Tools/Windows/`)
- **ProcessService** — список, поиск, завершение процессов
- **VolumeService** — управление громкостью (установка, +/-, mute)
- **ScreenCaptureService** — захват экрана
- **AudioController** — аудио-контроллер
- **FileController** — файловые операции Windows

### System (`ZERE.Tools/System/`)
- **SystemInfoService** — системная информация
- **ProcessManager** — менеджер процессов
- **PowerController** — управление питанием (выключение, перезагрузка)

### Drawing (`zere/tools/drawing/`, только Python-редакция)
Три способа: плагин Krita (родной API), картинка для Paint (рендер + вставка/файл) и эмуляция мыши Win32 как откат.
- **DrawingService** — выбирает способ: Krita — плагин, Paint — картинка (Ctrl+V или файл, `ZERE_PAINT_MODE`), иначе курсор (поиск и фокус окна, канвас, штрихи, очистка)
- **DrawingCanvas** (`drawing_canvas.py`) — фигуры и текст в картинку (Pillow), DIB/PNG для буфера обмена, сохранение файла (чистые функции)
- **DrawingClipboard** (`drawing_clipboard.py`) — буфер обмена Windows: DIBV5 + PNG + DIB, чтобы вставить рисунок одним Ctrl+V
- **DrawingCommandRouter** — разбор команд: фигуры, текст, смена цели, очистка
- **DrawingGeometry** — чистые функции: фигуры в нормализованных координатах, канвас, растр → штрихи, поиск документа по снимку экрана
- **DrawingSvg** — фигуры и текст → SVG для плагина Krita (чистые функции)
- **KritaApi** (`krita_api.py`) — клиент плагина: JSON-строки по TCP на 127.0.0.1, порт из kritarc
- **KritaInstall** (`krita_install.py`) — установка плагина в `pykrita` и включение в `kritarc` (`python -m zere.tools.drawing.krita_install`)
- **DrawingFont** — текст через растеризацию шрифта Pillow в горизонтальные штрихи (любой язык, включая кириллицу)
- **DrawingTarget** — описания Krita и Paint: имена процессов (`krita.exe`, `mspaint.exe`/`PaintApp.exe`), заголовки окон, пути запуска, отступы холста
- Подробности: `docs/DRAWING.md`

### Voice (`ZERE.Voice/`)
- **VoiceManager** — оркестратор STT (роутинг `sttEngine`: `gigaam` — GigaAM-v3 основной, автоматический откат на `whisper`) + TTS (движок выбирается ключом `ttsEngine`: `silero` — русский, `chattts` — китайский/английский, `pocket` — клонирование голоса в C#)
- **VoiceBootstrap (Python, `voice_bootstrap.py`)** — политика старта голоса: доступность TTS поднимается всегда, в том числе при `voiceEnabled=false` (иначе панель на «Озвучить» отвечала 503 «Синтез речи недоступен: ChatTTS доступен…»), предзагрузка STT (качает модель) — только при включённом голосе; C#-паритет — `ZERE.App/Program.cs`
- **Озвучка ответов панели** — `VoiceManager.speak_background()` (Python) и `SpeakAsync` в `Task.Run` (C#): ответ чата читается голосом при `voiceEnabled=true`, новая реплика обрывает предыдущую, выключение голоса в панели гасит речь сразу
- **ISttService** — общий контракт STT-движков (`IsInstalled`/`Preload`/`TranscribeAsync`), за ним скрыт выбор активного движка
- **GigaAmService** — основной STT: sherpa-onnx + GigaAM-v3 punct (русский, с пунктуацией; модель ~163 МБ качается при установке или при `Preload`, SHA-256)
- **AudioRecorder** — запись с микрофона (и запись референса голоса для клонирования)
- **ContinuousAudioRecorder** — непрерывная запись с круговым буфером и адаптивным VAD (wake word)
- **AudioDevice (Python, `audio_device.py`)** — выбор устройства: WASAPI-аналог устройства по умолчанию (низкая задержка) + системный ресемплер (`auto_convert`), иначе откат на MME; `input_options`/`output_options` отдают готовые аргументы открытия потока и лечат `Invalid sample rate [PaErrorCode -9997]` (16 кГц против микшера 44.1/48 кГц)
- **CSharpSpeaker (Python, `csharp_speaker.py`)** — мост к C#-хелперу «ZERE.Speaker»: озвучка (DSP + вывод звука) идёт на C#, при отсутствии сборки/крахе — автоматический откат на Python (sounddevice); `ZERE_SPEAKER=python` — принудительный Python
- **AudioPlayer** — воспроизведение WAV
- **StreamPlayer** — потоковое воспроизведение PCM (играет, пока TTS ещё синтезирует)
- **WhisperService** — распознавание речи (откатный STT + wake word — детектор просыпания намеренно остаётся на Whisper)
- **ChatTtsService (C#)** — синтез речи ChatTTS (нейросетевой TTS, замена Piper): ленивая загрузка, тяжёлая часть — в Python-сайдкаре `tools/zere_chattts_server.py` (HTTP), попредложенное стримирование. Подробности: `docs/TTS_CHATTTS.md`
- **ChatTtsService (Python, `zere/voice/chattts/`)** — адаптер под прежний контракт PiperService (сам Piper заменён на ChatTTS): `is_loaded`/`initialize`/`speak`/`set_voice`/`set_inference_params`/`get_available_voices`/`close` + `ChatTTSManager` с ленивой загрузкой модели; профиль голоса — детерминированное зерно (crc32 имени)
- **SileroTtsService (C#, `ZERE.Voice/Silero/`)** — русский синтез Silero v5_5_ru через сайдкар `tools/zere_silero_server.py` (uv: torch + soundfile, порт 8473, PCM s16le 24 кГц): тот же контракт, что у ChatTtsService; темп речи не поддерживается. Подробности: `docs/TTS_SILERO.md`
- **SileroTtsService (Python, `zere/voice/silero/`)** — тот же контракт: `SileroManager` (ленивая загрузка `v5_5_ru.pt` из `ZERE.Voice/Silero`, голоса `baya`/`xenia`/`kseniya`/`aidar`/`eugene`, чужой профиль голоса → дефолт) + `SileroTtsService`; движок выбирается ключом `ttsEngine: chattts | silero`
- **PocketTtsService** — клиент к серверу xVibePocketTTS: клонирование голоса, PCM-поток, первый звук через ~150–700 мс
- **SpeechText** — чистка текста от TTS-мусора + разбивка на предложения
- **VoiceConfig** — конфигурация голоса (`sttEngine` и др.)

### Tools (`tools/`)
- **krita_plugin/** — плагин ZERE для Krita (PyKrita): локальный сервер и рисование родным API (`createVectorLayer` + `addShapesFromSvg`, `Node.paintLine`); ставится в пользовательскую `pykrita` установщиком `zere/tools/drawing/krita_install.py`
- **zere_tts_server.py** — HTTP-сервер TTS (`/health`, потоковый `/tts`), поднимается PocketTtsService автоматически
- **zere_chattts_server.py** — HTTP-сервер ChatTTS (`/health`, потоковый `/tts` → PCM s16le 24 кГц), поднимается C#-ChatTtsService через `tools/uv.exe` с `--python 3.12`
- **zere_silero_server.py** — HTTP-сервер Silero v5 (русский голос: `/health`, `/voices`, потоковый `/tts` → PCM s16le 24 кГц), поднимается C#-SileroTtsService через `tools/uv.exe` с `--python 3.12 --with torch --with soundfile`
- **uv.exe**, **xVibePocketTTS/** — менеджер Python и репозиторий движка (gitignored, ставятся отдельно)

---

## Обработчики (Handlers) — `ZERE.Core/Handlers/`

Pipeline обработки команд (порядок важен):

1. **MemoryHandler** — «запомни», «забудь», «покажи память»
2. **MemoryQueryHandler** — запросы к памяти
3. **ConversationHandler** — «покажи историю», «очисти историю»
4. **ProcessHandler** — «процессы», «найди процесс», «закрой процесс»
5. **WindowsHandler** — Windows-команды
6. **FileHandler** — «создай папку/файл», «найди файл», «удали файл»
7. **GameHandler** — игровые команды
8. **VolumeHandler** — «громкость», «сделай громче/тише», «выключи звук»
9. **DrawingHandler** — рисование в Krita/Paint: «нарисуй круг», «напиши на холсте привет», «рисуй в крите» *(только Python-редакция)*
10. **AIHandler** — fallback → генерация ответа через провайдера ИИ
    (облачный ключ пользователя или локальная Ollama — выбор в
    `zere/ai/ai_service.py` и `ZERE.AI/AiService.cs` через `IAiClient`)

---

## Плагинная система

### Интерфейсы плагинов (`ZERE.Core/Plugins/Interfaces/`)
- **IPlugin** — базовый интерфейс всех плагинов
- **IPersonalityPlugin** — плагины личности (System Prompt + параметры)
- **ICommandHandlerPlugin** — плагины обработчиков команд

### Менеджер плагинов (`PluginManager`)
- Загружает встроенные плагины из сборки
- Загружает внешние плагины из `./plugins/*.dll`
- Управляет активной личностью

### Встроенный плагин личности
| Стиль | Температура | Описание |
|---|---|---|
| **Friendly** | 0.7 | Дружелюбный, тёплый, с эмодзи |
| **Formal** | 0.3 | Официальный, строгий, профессиональный |
| **Sarcastic** | 0.9 | Саркастичный, с иронией и юмором |
| **Professional** | 0.4 | Деловой, без лишних слов |
| **Casual** | 0.8 | Неформальный, на "ты" |

### Конфигурация плагинов (`config/plugins.json`)
```json
{
  "ActivePersonalityId": "personality",
  "PluginSettings": {}
}
```

---

## Обновление из GitHub

**Только Python-редакция** (C#-панель эндпоинтов обновления не имеет).
Обновляется кодом `zere/core/update/updater.py` (`UpdateService`):
`git fetch` + `git pull --ff-only` текущей ветки, без слияний и force.

- Автопроверка при старте панели (фоновый поток, сбой не мешает работе).
- Экран панели «Обновления» (`/update`) + карточка на дашборде + отметка в
  статус-строке (`⬆ обновление: N`).
- API: `GET /api/update` (кэш, без сети), `POST /api/update/check` (fetch),
  `POST /api/update/apply` (`pull --ff-only` + `pip install -r requirements.txt`
  при изменении файла; `409 UPDATE_BUSY` при параллельной операции).
- CLI: `python -m zere.core.update [--check|--apply] [--no-deps]`.
- Данные не трогаются: `config/`, `zere.db`, `logs/`, голосовые модели.
  Грязная рабочая копия и расхождение веток — отказ с причиной, не pull.
- После применения нужен перезапуск ZERE (процесс не перезапускается сам).
- Подробности: `docs/UPDATE.md`; тесты — `tests/test_updater.py`
  и контрактные `/api/update*` в `tests/test_panel_api.py`.

## Подключение ИИ (ключ облачной модели / локальная модель)

**Обе редакции, контракт общий** (docs/api/openapi.yaml, раздел `ai`):

- Python: `zere/ai/ai_settings.py`, `cloud_client.py`, `local_model.py`,
  `ai_service.py`; маршруты — `zere/api/server.py`.
- C#: `ZERE.AI/AiSettings.cs`, `CloudClient.cs`, `LocalModelService.cs`,
  `AiService.cs`, `IAiClient.cs`, `AiError.cs`; маршруты —
  `ZERE.App/Api/PanelServer.cs`; прокси в `AIHandler` — через `IAiClient`.

- Режимы: `auto` — сначала облачный ключ, иначе локальная модель; `cloud` —
  только ключ; `local` — только локальная модель. `AiProviderProxy` встаёт
  в `AIHandler` вместо `OllamaClient` (интерфейс `generate/warmup/close`
  тот же), поэтому выбор провайдера работает на лету, без перезапуска.
- Ключ пользователя: `config/ai.json` (gitignored, права 0600). Наружу —
  только маска `sk-...abcd`; в логах секреты вычищает `redact_secrets`
  (`zere/core/logging/log_service.py`).
- Формат `config/ai.json` общий для двух редакций: ключи snake_case
  (`cloud_provider`, `cloud_model`, `cloud_api_key`), читается и camelCase
  (старые сборки C#) — иначе редакции молча сбрасывали чужие настройки
  («модель не сохраняется», «ключ не найден»). Пример и паритет:
  `docs/AI_PROVIDERS.md`, §6; тесты — `tests/test_ai_providers.py`.
- Модель и Base URL в панели сохраняются кнопкой «Сохранить адрес и модель»
  без повторного ввода ключа (пустое поле ключа при уже сохранённом ключе
  тоже сохраняет модель — раньше была ошибка «Введите API-ключ.»).
- Ключ владельца — только в переменных окружения сервера
  (`ZERE_CLOUD_API_KEY` и др.) и только для его аккаунта; из панели не
  удаляется. Пример: `.env.example`.
- API: `GET /api/ai` (состояние), `POST /api/ai/settings`, `POST|DELETE
  /api/ai/key` (проверка рабочим запросом + сохранение / удаление),
  `POST /api/ai/key/test`, `GET /api/ai/local`, `POST /api/ai/local/test`,
  `GET /api/ai/local/pull` (SSE-прогресс `ollama pull`).
- Панель: экран «Подключение ИИ» (`panel/src/screens/ai.ts`, маршрут `/ai`),
  карточка «ИИ и модель» на дашборде, бейдж и подсказка в чате, отметка
  `ИИ: облако|локально|не настроен` в статус-строке.
- `panel/dist` общий для двух редакций: фронтенд определяет возможности
  бэкенда (`aiSupport()` в `panel/src/api.ts`) — процесс старше `panel/dist`
  просит перезапуск (`ИИ: перезапустите ZERE`), а старая сборка без
  `/api/ai` скрывает пункт меню и показывает `ИИ: только локально` вместо
  «Маршрут не найден».
- Локальная модель: Ollama (`http://127.0.0.1:11434/v1`) или другой
  OpenAI-совместимый сервер; по умолчанию предлагаются лёгкие модели
  (`qwen3.5:2b`, 0.5B–3B) — тяжёлые для слабых ПК не предлагаются.
- Если настроен облачный ключ, Ollama перестаёт быть критической
  зависимостью (`zere/core/dependencies/dependency_checker.py`,
  `cloud_available=True`) — ZERE стартует и отвечает через облако.
- Сборка C#: `dotnet build ZERE.slnx`; панель только с API —
  `dotnet run --project ZERE.App --no-build -- --panel --port 8091`
  (порт нужен, если 8080 занят работающим ZERE); проверка контракта против
  уже запущенной панели — `python tests/check_ai_contract_external.py 8091`.
  CI (джоба `csharp` в `.github/workflows/ci.yml`) собирает C#-решение,
  поднимает панель, гоняет контрактные тесты и полный цикл ИИ на фейковом
  провайдере (`tests/fake_openai_server.py`) — без интернета и без
  настоящих API.
- Подробности: `docs/AI_PROVIDERS.md`; тесты — `tests/test_ai_providers.py`
  (юнит, фейковый HTTP `tests/fake_http.py`), контрактные `/api/ai*`
  в `tests/test_panel_api.py` (обе редакции: форма и валидация — всегда,
  живой провайдер — только внутрипроцессно).

## Карта структуры проекта

```
Zere/
├── AGENTS.md                     # Этот файл
├── ZERE.slnx                     # Решение (.NET 10)
├── config/
│   ├── config.json               # Конфигурация (модель, язык, голос)
│   └── ai.json                   # Настройки ИИ + ключ облачной модели (gitignored, 0600)
├── zere.db                       # SQLite база данных
├── ZERE.App/                     # Точка входа
│   └── Program.cs                # Консольный цикл
├── ZERE.Core/                    # Ядро
│   ├── ZereEngine.cs             # Главный engine
│   ├── ServiceRegistration.cs    # DI-контейнер
│   ├── Configuration/
│   │   └── ZereConfig.cs         # Загрузка config.json
│   ├── Dependencies/
│   │   └── DependencyChecker.cs
│   ├── Handlers/                 # Обработчики команд
│   │   ├── HandlerPipeline.cs    # Цепочка обработки
│   │   ├── IZereHandler.cs       # Интерфейс
│   │   ├── AIHandler.cs          # → Ollama
│   │   ├── MemoryHandler.cs      # Запоминание
│   │   ├── MemoryQueryHandler.cs
│   │   ├── ConversationHandler.cs
│   │   ├── ProcessHandler.cs
│   │   ├── WindowsHandler.cs
│   │   ├── FileHandler.cs
│   │   ├── GameHandler.cs
│   │   └── VolumeHandler.cs
│   ├── Logging/
│   │   └── LogService.cs
│   └── Plugins/                  # Плагинная система
│       ├── Interfaces/
│       │   ├── IPlugin.cs
│       │   ├── IPersonalityPlugin.cs
│       │   └── ICommandHandlerPlugin.cs
│       ├── BasePlugin.cs
│       ├── PluginManager.cs
│       ├── PluginConfig.cs
│       ├── BuiltIn/
│       │   └── Personality/
│       │       └── PersonalityPlugin.cs
│       └── Settings/
│           └── SettingsMenu.cs
├── ZERE.AI/                      # AI-клиент
│   ├── OllamaClient.cs           # HTTP → Ollama API (IAiClient)
│   ├── OllamaUrlResolver.cs      # Общий резолвер URL Ollama
│   ├── SystemPrompt.cs           # Системный промпт
│   ├── IAiClient.cs              # Контракт генерации для AIHandler
│   ├── AiSettings.cs             # config/ai.json: режим, ключ (маска), env владельца
│   ├── CloudClient.cs            # OpenAI-совместимый API: проверка ключа, генерация
│   ├── LocalModelService.cs      # Проверка Ollama/локального сервера, ollama pull
│   ├── AiService.cs              # Приоритет провайдеров + AiProviderProxy
│   ├── AiError.cs                # Коды/тексты ошибок ИИ + SecretRedactor
│   └── Models/                   # DTO для ответов
│                                 # Python-редакция (zere/ai/): ollama_client +
│                                 # ai_settings/cloud_client/local_model/ai_service
│                                 # (облачный ключ или локальная модель)
├── ZERE.Memory/                  # Память
│   └── Database/
│       ├── MemoryDatabase.cs     # Инициализация SQLite
│       ├── MemoryRepository.cs   # CRUD воспоминаний
│       └── ConversationRepository.cs
├── ZERE.Tools/                   # Инструменты
│   ├── Applications/
│   │   ├── ApplicationLauncher.cs
│   │   ├── AppAliasProvider.cs
│   │   └── Indexing/             # Сканеры приложений
│   ├── Files/
│   │   ├── FileManager.cs
│   │   └── FileCommandRouter.cs
│   ├── Gaming/
│   │   ├── GameTracker.cs
│   │   ├── GameGuardian.cs
│   │   └── GameCatalog.cs
│   ├── Windows/
│   │   ├── ProcessService.cs
│   │   ├── Volume/VolumeService.cs
│   │   ├── ScreenCaptureService.cs
│   │   ├── AudioController.cs
│   │   └── FileController.cs
│   └── System/
│       ├── SystemInfoService.cs
│       ├── ProcessManager.cs
│       └── PowerController.cs
├── ZERE.Voice/                   # Голос
│   ├── VoiceManager.cs           # Оркестратор STT (gigaam→whisper) + TTS (silero/chattts/pocket)
│   ├── VoiceConfig.cs            # Конфигурация голоса (sttEngine, ttsEngine, ...)
│   ├── ISttService.cs            # Контракт STT-движков (распознавание)
│   ├── Sherpa/
│   │   └── GigaAmService.cs      # Основной STT: sherpa-onnx + GigaAM-v3 punct (модель качается сама)
│   ├── Whisper/
│   │   └── WhisperService.cs     # STT-откат + wake word (speech-to-text)
│   ├── ChatTts/
│   │   └── ChatTtsService.cs     # TTS ChatTTS через сайдкар (попредложенное стримирование)
│   ├── Silero/
│   │   └── SileroTtsService.cs   # Русский TTS Silero v5 через сайдкар (ленивая загрузка модели)
│   ├── Pocket/
│   │   └── PocketTtsService.cs   # TTS с клонированием голоса (HTTP → xVibePocketTTS)
│   ├── Text/
│   │   └── SpeechText.cs         # Чистка текста + разбивка на предложения
│   ├── Audio/
│   │   ├── AudioRecorder.cs      # Запись с микрофона
│   │   ├── AudioPlayer.cs        # Воспроизведение WAV
│   │   └── StreamPlayer.cs       # Потоковое воспроизведение PCM
│   └── Models/                   # Модели STT (gitignored): ggml-base.bin + пакет GigaAM
├── ZERE.Speaker/                 # C#-хелпер озвучки (DSP + вывод звука)
│   ├── ZERE.Speaker.csproj       # NAudio + исходники DSP/плеера ссылкой из ZERE.Voice
│   └── Program.cs                # режим host (JSON-строки): speak/stop/ping/quit
├── tools/                        # TTS-инструментарий
│   ├── zere_tts_server.py        # HTTP-сервер клонирования (uv.exe, xVibePocketTTS — gitignored)
│   ├── zere_chattts_server.py    # HTTP-сервер ChatTTS (uv.exe, PCM s16le 24 кГц)
│   └── zere_silero_server.py     # HTTP-сервер Silero v5, русский голос (uv.exe: torch + soundfile)
├── panel/                        # Web-панель (SPA, Vite + vanilla TS)
│   ├── src/                      # main/shell/router/ui/i18n + 13 экранов (screens/)
│   │   └── commands.ts           # каталог команд ZERE (панель на вкладке «Чат»)
│   ├── e2e/                      # Playwright-смоук (npm run test:e2e)
│   └── dist/                     # Сборка — коммитится, раздаётся сервером
├── installer/                    # Установщик Windows (PowerShell + Inno Setup)
│   ├── install.ps1               # Установка: Python/Ollama/голос/ярлыки, SHA-256, -CheckOnly
│   ├── uninstall.ps1             # Деинсталляция (-RemoveAssets, -PurgeData)
│   ├── ZereLauncher.bat          # Шаблон лаунчера ZERE.bat
│   ├── Install-Zere.bat          # Двойной клик → install.ps1
│   ├── Uninstall-Zere.bat        # Двойной клик → uninstall.ps1
│   ├── Zere.iss                  # Inno Setup: готовый Setup.exe
│   └── build-setup.ps1           # Сборка Setup.exe (git archive + ISCC)
├── tests/
│   ├── test_panel_api.py         # Контрактные тесты панели (123, по OpenAPI)
│   ├── test_installer.py         # Тесты установщика (BOM, CRLF, SHA-256, связность)
│   ├── test_stt_engine.py        # Тесты STT GigaAM (константы, роутинг, живое распознавание)
│   ├── test_audio_device.py      # Тесты звуковых устройств (WASAPI+auto_convert, откат, регрессия -9997, живой микрофон)
│   ├── test_voice_mode.py        # Тесты голосового режима (сбой записи/озвучки не убивает цикл)
│   ├── test_wake_word.py         # Тесты слова-триггера «зере» (варианты имени, ложные срабатывания)
│   ├── test_chattts.py           # Тесты ChatTTS (ленивая загрузка, профили голоса, [speed_N], контракт сайдкара)
│   ├── test_silero.py            # Тесты Silero v5 (русский голос: ленивая загрузка модели, голоса, маршрутизация, сайдкар)
│   ├── test_db_compat.py         # Тесты совместимости базы (старая колонка JarvisResponse, переименование jarvis.db)
│   ├── test_csharp_speaker.py    # Тесты C#-озвучки (протокол хелпера, stop, откат на Python; без устройств)
│   ├── fake_speaker.py           # Фейковый C#-хелпер для тестов озвучки (звук не играет)
│   ├── test_system_prompt.py     # Тесты P1-2
│   ├── test_drawing.py           # Тесты рисования (49: роутер, геометрия, документ, текст, Win32)
│   ├── test_krita_plugin.py      # Тесты плагина Krita (32: SVG, протокол, kritarc, установка, выбор способа)
│   ├── test_drawing_canvas.py    # Тесты рисования картинкой (27: рендер, DIB, буфер, доставка в Paint)
│   ├── test_updater.py           # Тесты обновления из GitHub (git в temp: fetch/pull, отказы, зависимости)
│   ├── test_ai_providers.py      # Тесты ИИ (приоритет облако/локально, проверка ключа, Ollama, маскирование)
│   ├── fake_http.py              # Фейковый requests.Session для тестов ИИ (без сети)
│   ├── check_ai_contract_external.py  # /api/ai* против запущенной панели (C# и Python)
│   └── e2e_server.py             # Раннер панели с фейками для E2E
├── docs/                         # Планы, отчёты, openapi.yaml (UPDATE.md, AI_PROVIDERS.md, TTS_SILERO.md)
├── logs/                         # Логи
└── backups/                      # Бэкапы версий
```

---

## Цель проекта

Создание автономного AI-ассистента для Windows, который:
- Управляет приложениями, файлами, процессами, громкостью
- Запоминает факты о пользователе и контексте диалога
- Поддерживает голосовой ввод/вывод
- Работает полностью локально (без облачных API — облачный ключ
  пользователя подключается опционально, см. `docs/AI_PROVIDERS.md`)
