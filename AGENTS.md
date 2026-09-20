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
| **JARVIS.Voice** | Голосовой ввод (Whisper) и вывод (Piper) |

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
- **VoiceManager** — оркестратор STT (Whisper) + TTS (Piper)
- **AudioRecorder** — запись с микрофона
- **AudioPlayer** — воспроизведение WAV
- **WhisperService** — распознавание речи (speech-to-text)
- **PiperService** — синтез речи (text-to-speech)
- **VoiceConfig** — конфигурация голоса

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

### Web-панель (планируется)
- `http://localhost:8080`
- REST API для настроек
- План: `docs/WEB_PANEL_PLAN.md`

---

## Конфигурация (`config/config.json`)

- **Модель**: qwen3.5:2b (через Ollama)
- **Язык**: ru
- **Голос**: Whisper (STT) + Piper (TTS), привязка к личности
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
│   ├── VoiceManager.cs        # Оркестратор STT + TTS
│   ├── VoiceConfig.cs         # Конфигурация голоса
│   ├── Whisper/
│   │   └── WhisperService.cs  # STT (speech-to-text)
│   ├── Piper/
│   │   └── PiperService.cs    # TTS (text-to-speech)
│   ├── Audio/
│   │   ├── AudioRecorder.cs   # Запись с микрофона
│   │   └── AudioPlayer.cs     # Воспроизведение WAV
│   └── Models/ggml-base.bin   # Модель Whisper
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
