# AGENTS.md

## Правила работы

1. **После каждой задачи — коммит и push в git.**
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

## Конфигурация (`config/config.json`)

- **Модель**: qwen3.5:2b (через Ollama)
- **Язык**: ru
- **Голос**: отключён по умолчанию (Whisper + Piper)
- **Память**: автоизвлечение фактов из диалога

---

## Цель проекта

Создание автономного AI-ассистента для Windows, который:
- Управляет приложениями, файлами, процессами, громкостью
- Запоминает факты о пользователе и контексте диалога
- Поддерживает голосовой ввод/вывод
- Работает полностью локально (без облачных API)
