# ZERE

Персональный AI-ассистент для Windows, работающий полностью локально.

## Возможности

- **Голосовой ввод/вывод** — GigaAM-v3 (STT, откат на Whisper) + TTS: Silero v5 (русский, ударения и омографы) + PocketTTS (клонирование голоса, C#-версия)
- **Локальная LLM** — Ollama с русско-ориентированной моделью T-lite 2.1 (8B, Apache-2.0): отвечает только по-русски, умеет tool calling; на слабом ПК можно переключиться на qwen3.5:4b/2b — [docs/LOCAL_MODELS_RESEARCH.md](docs/LOCAL_MODELS_RESEARCH.md)
- **Свой API-ключ** — облачная модель через любой OpenAI-совместимый API (OpenAI, DeepSeek, OpenRouter, Groq): режим «Авто» использует ключ, если он есть, иначе локальную модель — [docs/AI_PROVIDERS.md](docs/AI_PROVIDERS.md)
- **Управление компьютером** — запуск приложений, процессы, файлы, громкость
- **Память** — SQLite-хранилище фактов о пользователе
- **История диалогов** — сохранение и просмотр
- **Плагины** — загрузка внешних плагинов (.dll в C#-версии, .py в Python-версии); MCP-плагины «браузер» (Playwright) и «заметки Obsidian»
- **Конспектор** — «законспектируй файл/ссылку/текст» → заметка в хранилище Obsidian (только Python-редакция)
- **Роутер интентов Jev** — свободная фраза → каноническая команда с порогом уверенности (опционально, по ключу)
- **Рисование** — фигуры и текст в Krita (родной API) или Paint (картинка в буфер)
- **Личности** — 6 стилей общения (Friendly, Formal, Sarcastic, Professional, Casual, Custom)
- **Язык ответов** — `ru`/`en` в настройках: меняет правило промпта и язык ответа (обе редакции)
- **Слово-триггер** — «Зере»: ассистент ждёт имя, затем слушает команду
- **Совместимость данных** — база прошлой версии (`jarvis.db`) подхватывается автоматически
- **Автообновление** — проверка GitHub при старте и кнопка «Обновить» в панели (`git pull --ff-only`)

## Требования

- [Ollama](https://ollama.com/download) — запущенный локальный сервер
- Модель: `ollama pull t-tech/T-lite-it-2.1:q4_K_M` (русский; на слабом ПК — `ollama pull qwen3.5:4b-q4_K_M`)
- **Вместо Ollama** можно указать свой API-ключ облачной модели: панель →
  «Подключение ИИ» (ключ живёт только на бэкенде, в интерфейсе — маска).
  Переменные окружения и примеры запросов — `.env.example` и
  [docs/AI_PROVIDERS.md](docs/AI_PROVIDERS.md)
- **Для C#-версии:** [.NET 10 SDK](https://dotnet.microsoft.com/download/dotnet/10.0)
- **Для Python-версии:** Python 3.12+ и `pip install -r requirements.txt`
- **Опционально:** Whisper (модель ggml-base.bin); TTS — Silero v5 (русский, модель 145 МБ качается сама; для C#-редакции нужен `tools/uv.exe`) или PocketTTS (клонирование голоса)

## Установка (Windows)

**Установщик в одном exe:** `installer\Output\ZereSetup.exe` — двойной клик,
права администратора не нужны. Ставит Python-окружение, Ollama с моделью,
голосовые модели, ярлыки (ведут на `zere.exe` — окно приложения), пишет
деинсталлятор в «Установка и удаление программ». Галочка **«Установить без
Ollama»** ставит ZERE без локальной модели (нужен облачный ключ в панели →
«ИИ»): без Ollama приложение запускается и работает, чат просит подключить
ключ или поставить модель. Сборка:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
```

Установщик собирается системным `csc.exe` — так его запускает и Windows 11 со
включённым Smart App Control (готовый `Setup.exe` от Inno Setup в этом режиме
блокируется как неизвестный exe).

```powershell
# полная установка: Python-окружение, Ollama + модель, Whisper + uv (для Silero), ярлыки
powershell -ExecutionPolicy Bypass -File installer\install.ps1

# только проверка, ничего не меняет
powershell -ExecutionPolicy Bypass -File installer\install.ps1 -CheckOnly
```

- Двойной клик: `installer\Install-Zere.bat`
- Запасной Setup.exe (Inno Setup 6): `installer\build-setup.ps1`
- Удаление: `installer\Uninstall-Zere.bat`
- Подробности, параметры и диагностика — [docs/INSTALL.md](docs/INSTALL.md)

## Запуск

### Приложение — `zere.exe`

Двойной клик по `zere.exe` (или ярлык «ZERE»): открывается окно ассистента,
консоли и вкладки браузера нет. Тот же exe — единственная видимая точка
входа; внутри он запускает Python-редакцию в фоне (`main.py --desktop`) и
держит журнал запуска.

```powershell
.\zere.exe                 # приложение (окно)
.\zere.exe --console       # отладка: обычная консоль Python
```

Окно рисует pywebview поверх WebView2 (Edge). Если WebView2 Runtime нет,
панель откроется в браузере, а причина будет показана окном. Пересобрать
`zere.exe` после правок лаунчера — `scripts\build-zere-exe.ps1`.

На Windows 11 со включённым **Smart App Control** новый неподписанный
`zere.exe` блокируется («заблокирован политикой Device Guard»); ярлык ZERE в
этом режиме запускает подписанный `pythonw.exe main.py --desktop` — окно и
поведение те же. Подробности и обход — [docs/DESKTOP_APP.md](docs/DESKTOP_APP.md).
Подробности: [docs/DESKTOP_APP.md](docs/DESKTOP_APP.md).

### Python-редакция (консоль, отладка)

```bash
pip install -r requirements.txt
python main.py            # консоль + панель в браузере
python main.py --desktop  # тот же режим приложения, без лаунчера
```

Требуется Python 3.12+. TTS — Silero v5: модель (145 МБ) качается сама, а
torch ставится в отдельное окружение `uv` при первом синтезе (~2 ГБ). Если
torch/модели нет, ZERE работает в текстовом режиме без ошибок. C#-редакция
поднимает движок в отдельном окружении через `tools/uv.exe` с `--python 3.12`.
Структура: пакет `zere/` (ai, core, memory, tools, voice), точка входа `main.py`.
Спецификация порта: `docs/PYTHON_PORT_SPEC.md`. TTS: [docs/TTS_SILERO.md](docs/TTS_SILERO.md). ChatTTS удалён в версии 1.9.0.

### C#-версия (.NET 10)

```bash
dotnet run --project ZERE.App
```

При первом запуске ZERE проверит зависимости и предложит установить недостающие.

## Разработка и тесты

```bash
python -m pip install -r requirements-dev.txt   # pytest, pytest-cov, ruff (без torch)
python -m pytest tests -q                        # весь набор, ~2 минуты
ruff check zere main.py tests                    # линтер (правила — ruff.toml)
```

CI (`.github/workflows/ci.yml`) прогоняет тот же набор целиком с отчётом о
покрытии (`--cov-fail-under`), проверяет `panel/dist` и контракт панели.
Полный рантайм (`requirements.txt`) для тестов не нужен: тяжёлые пакеты
подменяются фейками.

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
| `найди папку проекты` | Поиск папок по профилю и дискам |
| `найди проекты` | Приложение, а если не найдено — папка |
| `открой папку загрузки` | Открыть папку в проводнике |
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
zere.exe             — приложение: лаунчер (окно, без консоли)
zere/desktop/        — окно pywebview, stdio без консоли, диалоги, лаунчер (C#)
assets/zere.ico      — иконка приложения и ярлыков
scripts/             — сборка zere.exe и иконки, проверки порта
main.py              — точка входа (Python)
zere/                — Python-порт: ai, core, memory, tools, voice
ZERE.App             — точка входа (C#)
ZERE.Core            — ядро: engine, обработчики, плагины
ZERE.AI              — клиент Ollama
ZERE.Memory          — SQLite-память
ZERE.Tools           — инструменты: приложения, файлы, процессы
ZERE.Voice           — голос: GigaAM/Whisper (STT) + Silero/PocketTTS (TTS)
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

Обновляется только код: `config/`, `zere.db`, `logs/`, `data/` и голосовые
модели не перезаписываются. Локальные правки и расхождение веток обновление
не трогает — оно отменяется с причиной.

Установленная сборка (`ZereSetup.exe`) не имеет `.git` — для неё работает
второй канал: метка коммита в `config/build-info.json` сравнивается с HEAD
ветки через GitHub API, а обновление накладывается архивом (zipball). После
обновления нужен перезапуск ZERE. Подробности — [docs/UPDATE.md](docs/UPDATE.md).

## Конфигурация

- `config/config.json` — модель, язык, голос
- `config/plugins.json` — активная личность, настройки плагинов

## Лицензия

MIT — полный текст в [LICENSE](LICENSE), краткое соглашение — [EULA.txt](EULA.txt).
Список сторонних компонентов и их лицензий — [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md);
какие данные хранятся локально и что уходит в сеть — [PRIVACY.md](PRIVACY.md).

История версий — [CHANGELOG.md](CHANGELOG.md).
