# ZERE

Персональный AI-ассистент для Windows, работающий полностью локально.

## Возможности

- **Голосовой ввод/вывод** — GigaAM-v3 (STT, откат на Whisper) + ChatTTS/PocketTTS (TTS)
- **Локальная LLM** — Ollama с моделью qwen3.5:2b
- **Свой API-ключ** — облачная модель через любой OpenAI-совместимый API (OpenAI, DeepSeek, OpenRouter, Groq): режим «Авто» использует ключ, если он есть, иначе локальную модель — [docs/AI_PROVIDERS.md](docs/AI_PROVIDERS.md)
- **Управление компьютером** — запуск приложений, процессы, файлы, громкость
- **Память** — SQLite-хранилище фактов о пользователе
- **История диалогов** — сохранение и просмотр
- **Плагины** — загрузка внешних плагинов (.dll в C#-версии, .py в Python-версии)
- **Личности** — 6 стилей общения (Friendly, Formal, Sarcastic, Professional, Casual, Custom)
- **Слово-триггер** — «Зере»: ассистент ждёт имя, затем слушает команду
- **Совместимость данных** — база прошлой версии (`jarvis.db`) подхватывается автоматически
- **Автообновление** — проверка GitHub при старте и кнопка «Обновить» в панели (`git pull --ff-only`)

## Требования

- [Ollama](https://ollama.com/download) — запущенный локальный сервер
- Модель: `ollama pull qwen3.5:2b`
- **Вместо Ollama** можно указать свой API-ключ облачной модели: панель →
  «Подключение ИИ» (ключ живёт только на бэкенде, в интерфейсе — маска).
  Переменные окружения и примеры запросов — `.env.example` и
  [docs/AI_PROVIDERS.md](docs/AI_PROVIDERS.md)
- **Для C#-версии:** [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0)
- **Для Python-версии:** Python 3.12+ и `pip install -r requirements.txt`
- **Опционально:** Whisper (модель ggml-base.bin); TTS — PocketTTS (клонирование голоса) или ChatTTS (офлайн-откат; нужен `tools/uv.exe`)

## Установка (Windows)

```powershell
# полная установка: Python-окружение, Ollama + модель, Whisper + uv (для ChatTTS), ярлыки
powershell -ExecutionPolicy Bypass -File installer\install.ps1

# только проверка, ничего не меняет
powershell -ExecutionPolicy Bypass -File installer\install.ps1 -CheckOnly
```

- Двойной клик: `installer\Install-Zere.bat`
- Готовый Setup.exe (Inno Setup 6): `installer\build-setup.ps1`
- Удаление: `installer\Uninstall-Zere.bat`
- Подробности, параметры и диагностика — [docs/INSTALL.md](docs/INSTALL.md)

## Запуск

### Python-версия (ветка `python-port`)

```bash
pip install -r requirements.txt
python main.py
```

Требуется Python 3.12+. Пакет ChatTTS ставится из исходников (sdist) и тянет
`torch`/`torchaudio`/`numba` — это ~2–3 ГБ и несколько минут; колёса этих
зависимостей есть для Python 3.10–3.14. Если ChatTTS не установлен, ZERE
работает в текстовом режиме без ошибок. C#-редакция поднимает движок в
отдельном окружении через `tools/uv.exe` с `--python 3.12`.
Структура: пакет `zere/` (ai, core, memory, tools, voice), точка входа `main.py`.
Спецификация порта: `docs/PYTHON_PORT_SPEC.md`. Движок TTS: `docs/TTS_CHATTTS.md`.

### C#-версия (.NET 10)

```bash
dotnet run --project ZERE.App
```

При первом запуске ZERE проверит зависимости и предложит установить недостающие.

## Команды

Полный справочник — в панели на вкладке **«Чат»**: панель «Команды ZERE»
(сгруппированы по обработчикам, с поиском; нажатие подставляет команду в
поле ввода). Каталог — `panel/src/commands.ts`.

Ниже — короткая выжимка:

| Команда | Описание |
|---|---|
| `запомни имя Dan` | Сохранить факт в память |
| `покажи память` | Показать все воспоминания |
| `как меня зовут` | Запрос к памяти |
| `открой дискорд` | Запуск приложения |
| `процессы` | Список процессов |
| `громкость 50` | Установить громкость |
| `нарисуй круг` | Рисование фигур в Krita/Paint (Python-версия) |
| `напиши на холсте привет` | Нарисовать текст на холсте |
| `рисуй в крите` | Переключить рисование на Krita |
| `выключи компьютер` | Выключение (с подтверждением) |
| `настройки` | Панель настроек |
| `голос` / `voice` | Голосовой режим (слово-триггер «Зере») |
| `exit` | Выход |

## Структура

```
main.py              — точка входа (Python)
zere/                — Python-порт: ai, core, memory, tools, voice
ZERE.App             — точка входа (C#)
ZERE.Core            — ядро: engine, обработчики, плагины
ZERE.AI              — клиент Ollama
ZERE.Memory          — SQLite-память
ZERE.Tools           — инструменты: приложения, файлы, процессы
ZERE.Voice           — голос: GigaAM/Whisper (STT) + ChatTTS/PocketTTS (TTS)
ZERE.Speaker         — C#-хелпер озвучки (DSP + вывод звука)
panel/               — web-панель (Vite + TypeScript)
docs/UPDATE.md       — обновление из GitHub (проверка, применение, откат)
installer/           — установщик Windows (PowerShell + Inno Setup)
```

## Обновление

ZERE проверяет свою ветку на GitHub при старте панели (фоном) и умеет
обновиться кнопкой — экран **«Обновления»** в панели:

```bash
python -m zere.core.update --check   # проверка из консоли
python -m zere.core.update --apply   # применить (git pull --ff-only + зависимости)
```

Обновляется только код: `config/`, `zere.db`, `logs/` и голосовые модели не
перезаписываются. Локальные правки и расхождение веток обновление не
трогает — оно отменяется с причиной. После обновления нужен перезапуск
ZERE. Подробности — [docs/UPDATE.md](docs/UPDATE.md).

## Конфигурация

- `config/config.json` — модель, язык, голос
- `config/plugins.json` — активная личность, настройки плагинов

## Лицензия

MIT
