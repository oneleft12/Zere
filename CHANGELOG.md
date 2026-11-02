# Changelog

Все заметные изменения проекта. Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — [Semantic Versioning](https://semver.org/lang/ru/). Версия проекта
живёт в `config/config.json` и оттуда попадает в установщик.

## [Не выпущено]

### Добавлено

- **Плагин браузера (MCP) ставится установщиком** вместе с проектом: шаг
  «Плагин браузера (MCP)» в `installer/install.ps1` кладёт Node.js в
  `tools\node` (свой zip с SHA-256; системный Node 18+ тоже годится) и
  `npm install @playwright/mcp@0.0.83` в `tools\mcp` (браузеры Playwright не
  качаются — управляем системным Edge), затем `python -m zere.core.mcp.setup`
  включает сервер `playwright` в `config/mcp.json` с абсолютными путями к
  `node.exe` и `cli.js`. Раньше на свежей установке «браузер открой …» и
  музыка на YouTube просили поставить Node.js и `npx` тянул пакет из сети.
  Отключение — галочка мастера «Установить плагин браузера (Playwright MCP)»,
  `ZereSetup.exe /SKIPMCP` или `install.ps1 -SkipMcp`. Слияние конфига
  (`zere/core/mcp/setup.py`) сохраняет чужие серверы, выбранный браузер и
  `enabled`; деинсталлятор убирает `tools\node`, `tools\mcp` (`-RemoveAssets`)
  и `config\mcp.json` (`-PurgeData`).
- Документация — `docs/MCP_PLUGINS.md` (§2.1) и `docs/INSTALL.md`; тесты —
  `tests/test_mcp_setup.py` и проверки связности в `tests/test_installer.py`.
- **Автозапуск вместе с Windows** (Python-редакция): карточка «Запуск вместе
  с Windows» на экране «Настройки» — переключатель применяется сразу, без
  кнопки «Сохранить». Запись `ZERE` живёт в
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (только текущий
  пользователь, без прав администратора): при включении записывается
  `zere.exe` текущей установки, при отключении запись удаляется. После
  переноса папки панель видит устаревший путь и перезаписывает его.
  API — `GET|POST /api/autostart` (`zere/core/autostart.py`).
  Деинсталлятор (`installer/uninstall.ps1`) убирает запись автозапуска.
- Документация — `docs/DESKTOP_APP.md`; тесты — `tests/test_autostart.py`
  и контрактные `/api/autostart` в `tests/test_panel_api.py`.
- **YouTube и музыка** (Python-редакция): «включи музыку», «включи джаз на
  ютубе», «открой ютуб», «пауза», «продолжи», «следующий/предыдущий трек»,
  «что играет». Музыка включается по-настоящему: Playwright MCP (Edge)
  открывает поиск, первое видео и микс, кликает Play. Без плагина браузера
  YouTube открывается браузером по умолчанию, а ZERE честно говорит, что
  автовоспроизведение недоступно (`zere/tools/media/`,
  `zere/core/handlers/media_handler.py`; команды в панели).
- Документация — `docs/YOUTUBE_MUSIC.md`; тесты — `tests/test_youtube_music.py`.
- **Поиск папок по системе и открытие в проводнике** (Python-редакция):
  команды «найди папку …», «открой папку …», «открой её», «открой папку 2»;
  ограниченный BFS по стандартным папкам, профилю и локальным дискам с
  ранжированием, алиасами, транслитом и кэшем индекса
  (`zere/tools/files/folder_search.py`, `folder_opener.py`).
- **Экран панели «Папки»** (`/folders`): поиск, таблица совпадений и кнопка
  «Открыть»; API `GET /api/folders`, `POST /api/folders/open`.
- `найди <имя>` без слова «папку» сначала ищет приложение, а если его нет —
  папку (транслитерация работает).
- Неоднозначный запрос не открывает первую папку наугад: показывается
  нумерованный список и ожидается уточнение.
- Документация — `docs/FOLDERS.md`; тесты — `tests/test_folder_search.py`
  и контрактные `/api/folders*`.

### Изменено

- **Обновления идут из публичного репозитория
  [oneleft12/Zere](https://github.com/oneleft12/Zere)** (прежнее имя `Jarvis`,
  GitHub перенаправляет старые адреса). Адрес по умолчанию для установленной
  сборки без `.git` — `Zere`: GitHub API и codeload читаются без токена,
  git-копии достаточно HTTPS-адреса в `origin` (ключ и логин не нужны).
  Изменены `zere/core/update/updater.py` (`_DEFAULT_REPOSITORY`),
  `installer/build-installer.ps1` и `build-setup.ps1` (поле `repository`
  в `config/build-info.json`); документация — `docs/UPDATE.md`.

## [1.9.0] — 2026-10-29

Русская речь — один движок: Silero. ChatTTS удалён.

### Удалено

- **ChatTTS** целиком: `zere/voice/chattts/`, сайдкар
  `tools/zere_chattts_server.py`, `ZERE.Voice/ChatTts/ChatTtsService.cs`,
  проверки и установка в зависимостях/установщике, `tests/test_chattts.py`,
  `docs/TTS_CHATTTS.md`. Пакет `ChatTTS` больше не ставится (из
  `requirements.txt` убран; `soundfile` остался для Silero).
- Переключатель движков в панели: только `silero` (Python) и `pocket`
  (клонирование, C#). Старые значения `chattts`/`pocket` в общем
  `config.json` не роняют старт — Python-редакция трактует их как Silero.

### Изменено

- `ttsEngine` по умолчанию — `silero` (Python `ZereConfig`/`VoiceConfig`,
  C# `ZereConfig`), шаблон `install.ps1` и валидация API
  (`pocket`|`silero`; `chattts` теперь 400).
- Инициализация TTS в `VoiceManager` (Python/C#) упрощена до Silero;
  откат PocketTTS при сбое идёт на Silero.
- Установщик больше не проверяет ChatTTS и не упоминает его в отчёте;
  `uv` остаётся нужен для Silero (torch) и клонирования голоса.
- `THIRD-PARTY-NOTICES`, README, ARCHITECTURE, INSTALL, AGENTS обновлены;
  из OpenAPI убран `chattts` из перечня движков.
- Версия проекта — 1.9.0.

### Исправлено

- Типы панели (`panel/src/api.ts`) признали `silero`: раньше TypeScript
  разрешал только `pocket`/`chattts`, хотя Silero уже был движком по умолчанию.
- Валидация C#-панели принимала `chattts` и отвергала `silero` — приведена
  к общему контракту.

## [1.8.0] — 2026-10-29

Релиз приложения: ZERE запускается окном, ставится одним exe.

### Добавлено

- **Приложение `zere.exe`** — лаунчер (C# 5, `csc.exe`), окно pywebview поверх
  WebView2, журнал в `logs/desktop.log`, единственный экземпляр, откат на
  браузер, если WebView2 нет.
- **Установщик `ZereSetup.exe`** (WinForms, C# 5) со встроенным payload,
  галочкой «Установить без Ollama» и записью в «Установка и удаление программ».
  Собирается системным `csc.exe` — обходит блокировку Smart App Control,
  из-за которой блокировался Setup.exe от Inno Setup.
- **Подпись кода** — `installer/sign.ps1` (Thumbprint/PFX, метка времени,
  проверка статуса) и подпись обоих exe в сборке и CI.
- **Конспектор** — «законспектируй файл/ссылку/текст» → заметка в Obsidian
  (map-reduce под окно модели, честные сноски о сбоях частей).
- **MCP-плагины** — браузер (Playwright: Edge/Chrome/Opera GX/Chromium) и
  заметки Obsidian; сервер поднимается лениво и только если включён.
- **Роутер интентов Jev** — свободная фраза → каноническая команда с порогами
  уверенности и подтверждением необратимых действий.
- **Рисование** — Krita (родной API), Paint (картинка в буфер) и эмуляция
  курсора как откат.
- **Подключение ИИ** — свой ключ OpenAI-совместимого API или локальная Ollama;
  экран «Подключение ИИ», маска ключа, права 0600/`icacls`.
- **Русский TTS Silero v5** — нормализация чисел и латиницы (у модели нет
  цифр и латиницы в наборе символов), паритет разбивки предложений с C#.
- **Слово-триггер на KWS** — стриминговый ONNX-детектор вместо VAD+STT,
  тулчейн обучения в `tools/wake_word/`.
- **Обновление из GitHub** — проверка при старте, экран «Обновления»,
  `git pull --ff-only`, данные пользователя не трогаются.
- **Требования и линтер** — `requirements-dev.txt` (pytest, pytest-cov, ruff,
  numpy, PyYAML, requests, pillow, psutil), `ruff.toml`; в CI прогоняется
  **весь** набор тестов с порогом покрытия.
- **Лицензия MIT** (`LICENSE`), `THIRD-PARTY-NOTICES.md`, `PRIVACY.md`.

### Исправлено

- **`NameError` при сбое сборки роутера Jev**: `log_error` не был импортирован,
  и откат на обычный конвейер падал бы вместе со стартом. Добавлен
  regression-тест.
- **Настройка `language` теперь работает**: язык ответа (ru/en) берётся из
  конфига, меняет правило в системном промпте, заголовки блоков промпта и
  подсказку голосового режима — в обеих редакциях (Python и C#). Раньше
  значение только печаталось при старте.
- **Фабрики сервисов без аннотации** регистрировались под служебным ключом
  `inspect.Signature.empty`; теперь это ошибка, а строковые аннотации
  (`from __future__ import annotations`) разрешаются через `get_type_hints`.
- **`faster-whisper` больше не обязателен для старта**: импорт ленивый, без
  пакета работает GigaAM и честное сообщение вместо падения приложения.
- **Импорт на Linux/CI**: `winreg` и `pycaw` импортируются мягко — панель и
  сервисы собираются, сканеры реестра/громкость просто недоступны.
- **`FileManager.create_file`** создаёт промежуточные папки: «создай файл
  папка/note.txt» больше не падает `FileNotFoundError`.
- **Path traversal в FileManager** закрыт тестами (абсолютные пути, `..`,
  симлинк наружу).
- Мелкие дефекты линтера: неопределённый `Optional` в геометрии рисования,
  повторяющийся ключ `«км/ч»`, неиспользуемые импорты и переменные,
  замыкание над переменной цикла в голосовом режиме.

### Изменено

- CI: вместо 10 файлов поимённо — `pytest tests` целиком (было 459 из 753
  тестов, стало все), плюс `ruff` и `--cov-fail-under`.
- Тесты ядра: обработчики команд, `ZereEngine`, сборка сервисов,
  `SafeActionManager`, `ProcessService`, `FileManager` — раньше покрытие 0 %.

[1.9.0]: https://github.com/oneleft12/Zere/releases/tag/v1.9.0
[1.8.0]: https://github.com/oneleft12/Zere/releases/tag/v1.8.0
