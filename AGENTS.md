# AGENTS.md

## Правила работы

1. **После каждой задачи — коммит и обязательный `git push`.** Коммит без push считается незавершённой задачей.
2. Коммиты делать на русском языке, кратко описывая суть.

---

## Описание проекта

**JARVIS** — персональный AI-ассистент для Windows, написанный на C# (.NET 10).  
Работает через консоль, подключается к локальной LLM (Ollama) и управляет компьютером голосом или текстом.

### Структура решения (JARVIS.slnx)

| Проект | Назначение |
|---|---|
| **JARVIS.App** | Точка входа — консольное приложение |
| **JARVIS.Core** | Ядро: engine, обработчики, маршрутизация намерений, конфигурация, контекст |
| **JARVIS.AI** | Клиент Ollama (HTTP) для генерации ответов |
| **JARVIS.Memory** | SQLite-память: воспоминания + история разговоров |
| **JARVIS.Tools** | Инструменты: приложения, файлы, игры, Windows, система |
| **JARVIS.Voice** | Голосовой ввод (Whisper) и вывод (Piper / PocketTTS-клонирование) |

---

## Tools (инструменты)

### Applications (`JARVIS.Tools/Applications/`)
- **ApplicationLauncher** — запуск приложений по имени
- **UniversalAppIndexer** — индексация установленных приложений
- **AppAliasProvider** — алиасы (например, «дискорд» → Discord)
- **Сканеры**: RegistryScanner, StartMenuScanner, AppPathsScanner, LocalAppDataScanner, InstalledAppScanner

### Files (`JARVIS.Tools/Files/`)
- **FileManager** — создание папок/файлов, поиск, удаление на рабочем столе
- **FileCommandRouter** — парсинг файловых команд

### Gaming (`JARVIS.Tools/Gaming/`)
- **GameTracker** — отслеживание времени в играх
- **GameGuardian** — определение запущенных игр
- **GameCatalog** — каталог игр

### Windows (`JARVIS.Tools/Windows/`)
- **ProcessService** — список, поиск, завершение процессов
- **VolumeService** — управление громкостью (установка, +/-, mute)
- **ScreenCaptureService** — захват экрана
- **AudioController** — аудио-контроллер
- **FileController** — файловые операции Windows

### System (`JARVIS.Tools/System/`)
- **SystemInfoService** — системная информация
- **ProcessManager** — менеджер процессов
- **PowerController** — управление питанием (выключение, перезагрузка)

### Voice (`JARVIS.Voice/`)
- **VoiceManager** — оркестратор STT (Whisper) + TTS (движок выбирается: PocketTTS с клонированием, откат на Piper)
- **AudioRecorder** — запись с микрофона (и запись референса голоса для клонирования)
- **AudioPlayer** — воспроизведение WAV
- **StreamPlayer** — потоковое воспроизведение PCM (играет, пока TTS ещё синтезирует)
- **WhisperService** — распознавание речи (speech-to-text)
- **PiperService** — синтез речи (text-to-speech), попредложенное стримирование
- **PocketTtsService** — клиент к серверу xVibePocketTTS: клонирование голоса, PCM-поток, первый звук через ~150–700 мс
- **SpeechText** — чистка текста от TTS-мусора + разбивка на предложения
- **VoiceConfig** — конфигурация голоса

### Tools (`tools/`, в git входит только сервер)
- **jarvis_tts_server.py** — HTTP-сервер TTS (`/health`, потоковый `/tts`), поднимается PocketTtsService автоматически
- **uv.exe**, **xVibePocketTTS/** — менеджер Python и репозиторий движка (gitignored, ставятся отдельно)

---

## Обработчики (Handlers) — `JARVIS.Core/Handlers/`

Pipeline обработки команд (порядок важен):

1. **MemoryHandler** — «запомни», «забудь», «покажи память»
2. **MemoryQueryHandler** — запросы к памяти
3. **ConversationHandler** — «покажи историю», «очисти историю»
4. **ProcessHandler** — «процессы», «найди процесс», «закрой процесс»
5. **WindowsHandler** — Windows-команды
6. **FileHandler** — «создай папку/файл», «найди файл», «удали файл»
7. **GameHandler** — игровые команды
8. **VolumeHandler** — «громкость», «сделай громче/тише», «выключи звук»
9. **AIHandler** — fallback → генерация ответа через Ollama

---

## Плагинная система

### Интерфейсы плагинов (`JARVIS.Core/Plugins/Interfaces/`)
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

## Настройки

### Консольная панель
Команда `настройки` или `settings` в консоли:
- Выбор личности/стиля
- Управление плагинами
- Просмотр конфигурации

### Web-панель (реализована, этапы 1–5 GUI-плана)
- `http://127.0.0.1:8080` — локальный сервер + SPA (11 экранов); при старте открывается **отдельным окном приложения** (WebView2 + трей, сворачивание вместо закрытия; без WebView2 Runtime — фолбэк в браузер); команда `панель` / `panel` в консоли выводит окно на передний план
- Стек: C# `JARVIS.App/Api/PanelServer.cs` + `PanelWindow.cs` (окно) и Python `jarvis/api/server.py` (Python: окно через pywebview, если установлен, иначе браузер) + SPA `panel/` (Vite + vanilla TS)
- Контракт: `docs/api/openapi.yaml` (20 путей), токен в `config/panel.token`
- Тесты: `python3 tests/test_panel_api.py` (91 контрактный) и `cd panel && npm run test:e2e` (Playwright, 6 смоуков)
- Документация: `docs/WEB_PANEL_PLAN.md`, план и статус этапов — `docs/GUI_DEVELOPMENT_PLAN.md`

### Установщик (`installer/`)

- `install.ps1` — полная установка на Windows: Python 3.12+ (winget), `.venv` + `requirements.txt`, Ollama + модель из конфига, голосовые артефакты (Whisper/Piper/голос — все скачивания проверяются по SHA-256), веб-панель, ярлыки, лаунчер `JARVIS.bat`, манифест, smoke-тест
- `install.ps1 -CheckOnly` — dry-run (ничего не меняет; коды возврата: 0 — готово, 1 — требуются действия)
- Параметры: `-Edition python|dotnet|both`, `-Yes`, `-NoLaunch`, `-SkipOllama`, `-SkipVoice`, `-SkipShortcuts`, `-Model`, `-Prefix`
- `uninstall.ps1` — удаление (ярлыки, `.venv`, `publish`, манифест; `-RemoveAssets` — голосовые артефакты; `-PurgeData` — `jarvis.db`, логи, референс голоса); исходный код не трогает
- `build-setup.ps1` + `Jarvis.iss` — сборка `installer\Output\JarvisInstaller.exe` (Inno Setup 6; stage из `git archive HEAD`, установка per-user в `%LOCALAPPDATA%\Programs\JARVIS`)
- Двойной клик: `Install-Jarvis.bat` / `Uninstall-Jarvis.bat`
- Тесты: `python3 tests/test_installer.py` (+ парсер PowerShell на Windows)
- Документация: `docs/INSTALL.md`

---

## Конфигурация (`config/config.json`)

- **Модель**: qwen3.5:2b (через Ollama)
- **Язык**: ru
- **Голос**: Whisper (STT) + TTS: `ttsEngine` = `pocket` (xVibePocketTTS, клонирование голоса; при сбоях — автоматический откат на `piper`), `voiceReferencePath` — WAV-референс (записывается командой «записать голос»)
- **Память**: автоизвлечение фактов из диалога

---

## Карта структуры проекта

```
Jarvis/
├── AGENTS.md                   # Этот файл
├── JARVIS.slnx                 # Решение (.NET 10)
├── config/
│   └── config.json             # Конфигурация (модель, язык, голос)
├── jarvis.db                   # SQLite база данных
│
├── JARVIS.App/                 # Точка входа
│   └── Program.cs              # Консольный цикл
│
├── JARVIS.Core/                # Ядро
│   ├── JarvisEngine.cs         # Главный engine
│   ├── ServiceRegistration.cs  # DI-контейнер
│   ├── Configuration/
│   │   └── JarvisConfig.cs     # Загрузка config.json
│   ├── Dependencies/
│   │   └── DependencyChecker.cs
│   ├── Handlers/               # Обработчики команд
│   │   ├── HandlerPipeline.cs  # Цепочка обработки
│   │   ├── IJarvisHandler.cs   # Интерфейс
│   │   ├── AIHandler.cs        # → Ollama
│   │   ├── MemoryHandler.cs    # Запоминание
│   │   ├── MemoryQueryHandler.cs
│   │   ├── ConversationHandler.cs
│   │   ├── ProcessHandler.cs
│   │   ├── WindowsHandler.cs
│   │   ├── FileHandler.cs
│   │   ├── GameHandler.cs
│   │   └── VolumeHandler.cs
│   ├── Logging/
│   │   └── LogService.cs
│   └── Plugins/                # Плагинная система
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
│
├── JARVIS.AI/                  # AI-клиент
│   ├── OllamaClient.cs         # HTTP → Ollama API
│   ├── OllamaUrlResolver.cs    # Общий резолвер URL Ollama
│   ├── SystemPrompt.cs         # Системный промпт
│   └── Models/                 # DTO для ответов
│
├── JARVIS.Memory/              # Память
│   └── Database/
│       ├── MemoryDatabase.cs   # Инициализация SQLite
│       ├── MemoryRepository.cs # CRUD воспоминаний
│       └── ConversationRepository.cs
│
├── JARVIS.Tools/               # Инструменты
│   ├── Applications/
│   │   ├── ApplicationLauncher.cs
│   │   ├── AppAliasProvider.cs
│   │   └── Indexing/           # Сканеры приложений
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
│
├── JARVIS.Voice/               # Голос
│   ├── VoiceManager.cs        # Оркестратор STT + TTS (роутинг pocket/piper)
│   ├── VoiceConfig.cs         # Конфигурация голоса
│   ├── Whisper/
│   │   └── WhisperService.cs  # STT (speech-to-text)
│   ├── Piper/
│   │   └── PiperService.cs    # TTS (попредложенное стримирование)
│   ├── Pocket/
│   │   └── PocketTtsService.cs # TTS с клонированием голоса (HTTP → xVibePocketTTS)
│   ├── Text/
│   │   └── SpeechText.cs      # Чистка текста + разбивка на предложения
│   ├── Audio/
│   │   ├── AudioRecorder.cs   # Запись с микрофона
│   │   ├── AudioPlayer.cs     # Воспроизведение WAV
│   │   └── StreamPlayer.cs    # Потоковое воспроизведение PCM
│   └── Models/ggml-base.bin   # Модель Whisper
│
├── tools/                      # TTS-инструментарий
│   └── jarvis_tts_server.py    # HTTP-сервер клонирования (uv.exe, xVibePocketTTS — gitignored)
│
├── panel/                      # Web-панель (SPA, Vite + vanilla TS)
│   ├── src/                    # main/shell/router/ui/i18n + 11 экранов (screens/)
│   ├── e2e/                    # Playwright-смоук (npm run test:e2e)
│   └── dist/                   # Сборка — коммитится, раздаётся сервером
│
├── installer/                  # Установщик Windows (PowerShell + Inno Setup)
│   ├── install.ps1             # Установка: Python/Ollama/голос/ярлыки, SHA-256, -CheckOnly
│   ├── uninstall.ps1           # Деинсталляция (-RemoveAssets, -PurgeData)
│   ├── JarvisLauncher.bat      # Шаблон лаунчера JARVIS.bat
│   ├── Install-Jarvis.bat      # Двойной клик → install.ps1
│   ├── Uninstall-Jarvis.bat    # Двойной клик → uninstall.ps1
│   ├── Jarvis.iss              # Inno Setup: готовый Setup.exe
│   └── build-setup.ps1         # Сборка Setup.exe (git archive + ISCC)
│
├── tests/
│   ├── test_panel_api.py       # Контрактные тесты панели (91, по OpenAPI)
│   ├── test_installer.py       # Тесты установщика (BOM, CRLF, SHA-256, связность)
│   ├── test_system_prompt.py   # Тесты P1-2
│   └── e2e_server.py           # Раннер панели с фейками для E2E
│
├── docs/                       # Планы, отчёты, openapi.yaml
│
├── logs/                       # Логи
└── backups/                    # Бэкапы версий
```

---

## Цель проекта

Создание автономного AI-ассистента для Windows, который:
- Управляет приложениями, файлами, процессами, громкостью
- Запоминает факты о пользователе и контексте диалога
- Поддерживает голосовой ввод/вывод
- Работает полностью локально (без облачных API)
