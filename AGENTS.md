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
| **ZERE.Voice** | Голосовой ввод (GigaAM-v3, откат на Whisper) и вывод (ChatTTS / PocketTTS-клонирование) |
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
- **DrawingService** — рисование в Krita/Paint эмуляцией мыши Win32: поиск и фокус окна, канвас, штрихи, очистка холста (Ctrl+A, Del)
- **DrawingCommandRouter** — разбор команд: фигуры, текст, смена цели, очистка
- **DrawingGeometry** — чистые функции: фигуры в нормализованных координатах, канвас, растр → штрихи
- **DrawingFont** — текст через растеризацию шрифта Pillow в горизонтальные штрихи (любой язык, включая кириллицу)
- **DrawingTarget** — описания Krita и Paint: имена процессов (`krita.exe`, `mspaint.exe`/`PaintApp.exe`), заголовки окон, пути запуска, отступы холста
- Подробности: `docs/DRAWING.md`

### Voice (`ZERE.Voice/`)
- **VoiceManager** — оркестратор STT (роутинг `sttEngine`: `gigaam` — GigaAM-v3 основной, автоматический откат на `whisper`) + TTS (движок выбирается: PocketTTS с клонированием, откат на ChatTTS)
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
- **PocketTtsService** — клиент к серверу xVibePocketTTS: клонирование голоса, PCM-поток, первый звук через ~150–700 мс
- **SpeechText** — чистка текста от TTS-мусора + разбивка на предложения
- **VoiceConfig** — конфигурация голоса (`sttEngine` и др.)

### Tools (`tools/`, в git входит только сервер)
- **zere_tts_server.py** — HTTP-сервер TTS (`/health`, потоковый `/tts`), поднимается PocketTtsService автоматически
- **zere_chattts_server.py** — HTTP-сервер ChatTTS (`/health`, потоковый `/tts` → PCM s16le 24 кГц), поднимается C#-ChatTtsService через `tools/uv.exe` с `--python 3.12`
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
10. **AIHandler** — fallback → генерация ответа через Ollama

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

## Карта структуры проекта

```
Zere/
├── AGENTS.md                     # Этот файл
├── ZERE.slnx                     # Решение (.NET 10)
├── config/
│   └── config.json               # Конфигурация (модель, язык, голос)
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
│   ├── OllamaClient.cs           # HTTP → Ollama API
│   ├── OllamaUrlResolver.cs      # Общий резолвер URL Ollama
│   ├── SystemPrompt.cs           # Системный промпт
│   └── Models/                   # DTO для ответов
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
│   ├── VoiceManager.cs           # Оркестратор STT (gigaam→whisper) + TTS (pocket→chattts)
│   ├── VoiceConfig.cs            # Конфигурация голоса (sttEngine, ttsEngine, ...)
│   ├── ISttService.cs            # Контракт STT-движков (распознавание)
│   ├── Sherpa/
│   │   └── GigaAmService.cs      # Основной STT: sherpa-onnx + GigaAM-v3 punct (модель качается сама)
│   ├── Whisper/
│   │   └── WhisperService.cs     # STT-откат + wake word (speech-to-text)
│   ├── ChatTts/
│   │   └── ChatTtsService.cs     # TTS ChatTTS через сайдкар (попредложенное стримирование)
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
│   └── zere_chattts_server.py    # HTTP-сервер ChatTTS (uv.exe, PCM s16le 24 кГц)
├── panel/                        # Web-панель (SPA, Vite + vanilla TS)
│   ├── src/                      # main/shell/router/ui/i18n + 12 экранов (screens/)
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
│   ├── test_panel_api.py         # Контрактные тесты панели (102, по OpenAPI)
│   ├── test_installer.py         # Тесты установщика (BOM, CRLF, SHA-256, связность)
│   ├── test_stt_engine.py        # Тесты STT GigaAM (константы, роутинг, живое распознавание)
│   ├── test_audio_device.py      # Тесты звуковых устройств (WASAPI+auto_convert, откат, регрессия -9997, живой микрофон)
│   ├── test_voice_mode.py        # Тесты голосового режима (сбой записи/озвучки не убивает цикл)
│   ├── test_wake_word.py         # Тесты слова-триггера «зере» (варианты имени, ложные срабатывания)
│   ├── test_chattts.py           # Тесты ChatTTS (ленивая загрузка, профили голоса, [speed_N], контракт сайдкара)
│   ├── test_db_compat.py         # Тесты совместимости базы (старая колонка JarvisResponse, переименование jarvis.db)
│   ├── test_csharp_speaker.py    # Тесты C#-озвучки (протокол хелпера, stop, откат на Python; без устройств)
│   ├── fake_speaker.py           # Фейковый C#-хелпер для тестов озвучки (звук не играет)
│   ├── test_system_prompt.py     # Тесты P1-2
│   ├── test_drawing.py           # Тесты рисования (36: роутер, геометрия, текст, обработчик, Win32)
│   ├── test_updater.py           # Тесты обновления из GitHub (git в temp: fetch/pull, отказы, зависимости)
│   └── e2e_server.py             # Раннер панели с фейками для E2E
├── docs/                         # Планы, отчёты, openapi.yaml (UPDATE.md — обновление из GitHub)
├── logs/                         # Логи
└── backups/                      # Бэкапы версий
```

---

## Цель проекта

Создание автономного AI-ассистента для Windows, который:
- Управляет приложениями, файлами, процессами, громкостью
- Запоминает факты о пользователе и контексте диалога
- Поддерживает голосовой ввод/вывод
- Работает полностью локально (без облачных API)
