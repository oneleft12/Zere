# JARVIS

Персональный AI-ассистент для Windows, работающий полностью локально.

## Возможности

- **Голосовой ввод/вывод** — Whisper (STT) + Piper (TTS)
- **Локальная LLM** — Ollama с моделью qwen3.5:2b
- **Управление компьютером** — запуск приложений, процессы, файлы, громкость
- **Память** — SQLite-хранилище фактов о пользователе
- **История диалогов** — сохранение и просмотр
- **Плагины** — загрузка внешних плагинов (.dll в C#-версии, .py в Python-версии)
- **Личности** — 6 стилей общения (Friendly, Formal, Sarcastic, Professional, Casual, Custom)

## Требования

- [Ollama](https://ollama.com/download) — запущенный локальный сервер
- Модель: `ollama pull qwen3.5:2b`
- **Для C#-версии:** [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0)
- **Для Python-версии:** Python 3.12+ и `pip install -r requirements.txt`
- **Опционально:** Whisper (модель ggml-base.bin), Piper (TTS)

## Установка (Windows)

```powershell
# полная установка: Python-окружение, Ollama + модель, Whisper/Piper, ярлыки
powershell -ExecutionPolicy Bypass -File installer\install.ps1

# только проверка, ничего не меняет
powershell -ExecutionPolicy Bypass -File installer\install.ps1 -CheckOnly
```

- Двойной клик: `installer\Install-Jarvis.bat`
- Готовый Setup.exe (Inno Setup 6): `installer\build-setup.ps1`
- Удаление: `installer\Uninstall-Jarvis.bat`
- Подробности, параметры и диагностика — [docs/INSTALL.md](docs/INSTALL.md)

## Запуск

### Python-версия (ветка `python-port`)

```bash
pip install -r requirements.txt
python main.py
```

Требуется Python 3.12+. Структура: пакет `jarvis/` (ai, core, memory, tools, voice), точка входа `main.py`. Спецификация порта: `docs/PYTHON_PORT_SPEC.md`.

### C#-версия (.NET 10)

```bash
dotnet run --project JARVIS.App
```

При первом запуске JARVIS проверит зависимости и предложит установить недостающие.

## Команды

| Команда | Описание |
|---|---|
| `запомни имя Dan` | Сохранить факт в память |
| `покажи память` | Показать все воспоминания |
| `как меня зовут` | Запрос к памяти |
| `открой дискорд` | Запуск приложения |
| `процессы` | Список процессов |
| `громкость 50` | Установить громкость |
| `выключи компьютер` | Выключение (с подтверждением) |
| `настройки` | Панель настроек |
| `голос` / `voice` | Голосовой режим |
| `exit` | Выход |

## Структура

```
main.py            — точка входа (Python)
jarvis/            — Python-порт: ai, core, memory, tools, voice
JARVIS.App         — точка входа (C#)
JARVIS.Core        — ядро: engine, обработчики, плагины
JARVIS.AI          — клиент Ollama
JARVIS.Memory      — SQLite-память
JARVIS.Tools       — инструменты: приложения, файлы, процессы
JARVIS.Voice       — голос: Whisper + Piper
```

## Конфигурация

- `config/config.json` — модель, язык, голос
- `config/plugins.json` — активная личность, настройки плагинов

## Лицензия

MIT
