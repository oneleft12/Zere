# Отчёт по аудиту проекта ZERE

**Дата:** 2026-09-23  
**Ветка:** `python-port` (HEAD `0c66026`, в синхронизации с `origin/python-port`)  
**Область:** весь трек-код репозитория — C#-решение (6 проектов, .NET 10) и Python-порт (`zere/`, `main.py`), конфигурация, документация, гигиена репозитория.  
**Метод:** статический аудит всех активных файлов с указанием `файл:строка`, динамические проверки отдельных подсистем в изолированном окружении, сборка `dotnet build -c Release`, `python3 -m compileall`, `scripts/check_port.py`, интроспекция `zere.db`, анализ git-истории и отслеживаемых файлов.

---

## 1. Резюме

Проект впечатляет прежде всего **архитектурной дисциплиной**: чистая слойность (App → Core → AI/Memory/Tools/Voice), DI-контейнер, единый конвейер из 9 обработчиков, паттерны Repository/Router/Plugin, параметризованный SQL везде без исключений, продуманные фолбэки и таймауты (reconnect Whisper/Piper, retry Ollama, кэш ответов, `errors.log`), обширная русскоязычная документация. Сборка C# проходит с одной предупреждением, Python-порт структурно соответствует спецификации.

Однако аудит выявил **системные проблемы в трёх зонах**:

1. **Функциональность, заявленная в документации, но не работающая вовсе:** история диалогов нигде не сохраняется (обе реализации), команды плагинов-обработчиков не подключены к конвейеру, обнаружение внешних Python-плагинов сломано сравнением строки с объектом модуля, `ttsEngine: pocket` и `voiceVolume` из `config.json` игнорируются, команда «удали его» парсится, но не обрабатывается, файловый поиск через документированную команду «найди файл» перехватывается другим обработчиком.
2. **Безопасность и надёжность:** path traversal в файловых операциях (динамически доказан), удаление файлов и kill процессов без реального подтверждения, подтверждение power-действий одним словом «да» без срока действия, срабатывание на отрицания («не выключай компьютер»), произвольная загрузка кода из `plugins/`.
3. **Инженерная гигиена:** ноль тестов, ноль CI, нет `LICENSE` при заявленном MIT, зависимости без фиксации версий, в git отслеживаются 4.21 МБ рантайм-артефактов (БД и аудио с голосом), 163 файла бэкапов в дереве, две параллельные реализации с уже начавшимся дрейфом конфигурации.

**Общая оценка:** архитектура — на уровне 8/10, реализация деталей и безопасность — 5/10, тестирование и CI — 1/10. До заявленной цели «автономного ассистента» критичны находки P0 (история, path traversal) и P1 (подтверждения опасных действий, маршрутизация, конфигурационный дрейф).

---

## 2. Ключевые метрики

| Метрика | Значение |
|---|---|
| Отслеживаемых файлов / объём | 414 файлов, ~5.14 МБ |
| Активный C# | 94 файла, 9 186 строк |
| Активный Python | 128 файлов, 8 969 строк |
| Бэкапы (`backups/`) | 163 файла (128 `.cs`, 7 075 строк) |
| Документация (`.md`) | 1 469 строк |
| Отслеживаемые аудио + БД | 4 415 074 байта (4.21 МБ) |
| Сборка C# (`-c Release`) | ✅ 0 ошибок, 1 предупреждение (CA2024, `OllamaClient.cs:110`), .NET SDK 10.0.401 |
| `scripts/check_port.py` | ✅ 126 файлов, 125 модулей |
| `python3 -m compileall` | ✅ exit 0 |
| Тесты | ❌ 0 тестовых файлов, pytest не установлен |
| CI | ❌ нет `.github/workflows` |
| LICENSE | ❌ отсутствует при заявленном MIT (`README.md:77`) |
| Зависимости Python | 9 шт., только нижние границы, lock-файла нет |
| `zere.db` | схема валидна, **0 строк** (Conversations/Memories пусты) |
| Секреты в треке | не обнаружены |
| Ветки | `main` — предок `python-port` (у `main` 0 собственных коммитов, merge-base `3ba3060`) |

---

## 3. Архитектура (краткая оценка)

**C#:** `ZERE.App` (консольный цикл) → `ZereEngine.ProcessAsync` → `HandlerPipeline` (фиксированный массив 9 обработчиков, `ServiceRegistration.cs:75-91`) → `AIHandler` → `OllamaClient` (`/api/generate`). Память — `ZERE.Memory` (SQLite через `Microsoft.Data.Sqlite`), инструменты — `ZERE.Tools` (Applications/Files/Gaming/Windows/System), голос — `ZERE.Voice` (Whisper STT, Piper/PocketTTS TTS, стриминг PCM).

**Python-порт:** полное зеркало структуры (`zere/ai`, `core`, `memory`, `tools`, `voice`) по спецификации `docs/PYTHON_PORT_SPEC.md` (1:1 имена, общие тесты через `check_port.py`). Конвейер идентичен (`services.py:269-284`).

**Замечания:**
- Порядок конвейера создаёт конфликты перехвата (см. P1-4): `WindowsHandler` (позиция 5) раньше `FileHandler` (позиция 6), `MemoryQueryHandler` (позиция 2) перехватывает все «что такое …» до AIHandler.
- Плагины: `IPersonalityPlugin` работает (6 стилей, `Custom` фактически скрыт из `GetAvailableStyles()` — `PersonalityPlugin.cs:73-78`, в списке остаётся 5; `README.md:13` заявляет 6), `ICommandHandlerPlugin` — **загружается, но никогда не исполняется** (см. P1-6).
- Две реализации уже разошлись по конфигурации: C# читает `ttsEngine`/`voiceReferencePath`, но не `voiceVolume`; Python читает `voiceVolume`, но не `ttsEngine`/`voiceReferencePath` и вообще не имеет PocketTTS (см. P1-7).
- Расхождение БД: C# хранит `zere.db` в `%LOCALAPPDATA%\ZERE`, Python — в корне репозитория (`memory_database.py:16`); `game_stats_database.py:15` пишет игровые статистики в ту же `db_path()`, тогда как C# использует отдельный `zere_games.db`.

---

## 4. Критические находки (P0)

### P0-1. История диалогов никогда не сохраняется (обе реализации)
- `ZereEngine.ProcessAsync` (`ZERE.Core/ZereEngine.cs:21-36`) и `engine.process()` (`zere/core/engine.py:26-37`) выполняют только извлечение фактов и прогон конвейера — **вызова `ConversationRepository.Save` нет нигде в активном коде** (сохранение существовало только в бэкапах `backups/v1.*/ZereEngine.cs`).
- Следствия: README-фича «История диалогов — сохранение и просмотр» (`README.md:11`) не работает (команда «покажи историю» всегда отвечает «История пуста»); `ContextBuilder.BuildHistory` читает из пустой таблицы, т.е. много-turn контекст (ROADMAP 2.1) не функционирует в принципе.
- Подтверждено динамически: `zere.db` — 0 строк; прогон engine без вставок в Conversations.
- **Дополнительный баг (проявится после исправления):** `GetLast` сортирует `ORDER BY Id DESC` (`ConversationRepository.cs:49-63`, `conversation_repository.py:50-72`), а `ContextBuilder.BuildHistory` (`ContextBuilder.cs:34-46`) не разворачивает список — контекст уйдёт в LLM от новых сообщений к старым.
- **Рекомендация:** добавить `Save(message, answer)` в оба engine; в `BuildHistory` — `.Reverse()`; покрыть тестом.

### P0-2. Path traversal в файловых операциях (доказано динамически)
- `FileManager.CreateFolder/CreateFile` (`ZERE.Tools/Files/FileManager.cs:21,33`) и Python-аналог (`zere/tools/files/file_manager.py:21,31`) склеивают имя из реплики пользователя с рабочим столом через `Path.Combine` / `self._desktop / name` без нормализации, без проверки на `..` и абсолютные пути.
- **Проверено на изолированном каталоге:** `create_file("../escape.txt")` создал файл **вне** Desktop; `create_file("/tmp/…/absolute.txt")` перебил базовый каталог абсолютным путём. `CreateFile` дополнительно перезаписывает существующие файлы (проверяется только `File.Exists` → `WriteAllText`).
- Сопутствующее: `DeleteFile` удаляет **первое совпадение имени** в рекурсивном обходе Desktop без подтверждения.
- **Рекомендация:** `Path.GetFullPath` + проверка `fullPath.StartsWith(desktopFullPath)`; запрет абсолютных путей и `..`; отдельное подтверждение для удаления; не перезаписывать существующие файлы без явного запроса.

### P0-3. Опасные действия без реального подтверждения и без срока действия
- **Kill процессов:** `ProcessService.Kill` (`ZERE.Tools/Windows/ProcessService.cs:39-58`, `zere/tools/windows/process_service.py:51-80`) убивает **все** совпадения по имени вместе с дочерними процессами, без какого-либо подтверждения; C# возвращает `true`, даже если все `Kill()` завершились исключением — пользователю сообщают «закрыт». Нет системных denylist (нельзя фразой «закрой svchost» сделать что-то опасное).
- **Power-действия:** подтверждение — любое одиночное слово «да/подтверди/выполни/сделай» (`WindowsHandler.cs:64-69`); pending-действие в `SafeActionManager` (`SafeActionManager.cs:10-56`) **не имеет TTL**: «да», сказанное хоть через час, выполнит `shutdown /s /t 0`. `Process.Start` для shutdown/restart не проверяет результат.
- **Ложные срабатывания:** матчинг на `Contains` без учёта отрицаний — **проверено:** «не выключай компьютер» → `Contains("выключай компьютер")` = true → запрос подтверждения выключения; любое вхождение слова «перезагрузка» в произвольной фразе → Restart (`WindowsCommandRouter.cs:16-49`).
- **Рекомендация:** TTL pending-действия (30–60 с), привязка к последнему запросу, полноценная фраза-подтверждение («подтверди выключение»), откат отрицаний («не/нет» → отмена), отдельный denylist процессов, честный отчёт результата kill.

---

## 5. Важные находки (P1)

### P1-4. Функция «найди файл» недостижима через конвейер
`WindowsHandler.CanHandle` перехватывает **любое** сообщение, начинающееся с «найди » (`WindowsHandler.cs:25`, `windows_handler.py:26`), и registered **раньше** `FileHandler` (порядок: Process → **Windows** → File, `ServiceRegistration.cs:82-86`). Команда «найди файл отчёт» уходит в поиск установленных приложений, файловый поиск не срабатывает никогда (доказано статически по порядку массива; динамический запуск на Linux невозможен из-за `winreg`). Python-версия идентична (`services.py:274-277`).
**Рекомендация:** сузить префикс WindowsHandler («найди приложение/программу/процесс») или поднять FileHandler выше.

### P1-5. «Удali его» парсится, но не исполняется (мёртвая ветка)
`FileCommandRouter.Parse` возвращает `DELETE_LAST_FILE` для «удали его»/«удалить его» (`FileCommandRouter.cs:13`, `file_command_router.py`), но ни в C# `FileHandler.cs:55-72`, ни в `file_handler.py:50-69` **нет ветки** для этого типа — фолбэк «Команда файлов не распознана».
**Проверено динамически:** `FileHandler.handle('удали его')` → «Команда файлов не распознана.».
**Рекомендация:** реализовать (удалять последний созданный файл) либо удалить тип из роутера и документации.

### P1-6. Плагины-обработчики команд не подключены к pipeline
`PluginManager` загружает `ICommandHandlerPlugin` из `./plugins/*.dll` / `./plugins/*.py` (`PluginManager.cs:95`, `plugin_manager.py:118-126`), но массив обработчиков фиксирован при регистрации DI (`ServiceRegistration.cs:75-91`, `services.py:269-284`) — **`CommandHandlers` нигде не читаются**. Документация утверждает обратное: `docs/ARCHITECTURE.md:106` «Плагин автоматически добавится в pipeline».
**Проверено динамически:** плагин-обработчик добавлен в менеджер, но в pipeline отсутствует (`pipeline_contains_plugin=False`).
**Рекомендация:** встроить `CommandHandlers` в формирование массива или исправить документацию.

**Обнаружение внешних Python-плагинов сломано (отдельный баг):** `load_plugin` (`zere/core/plugins/plugin_manager.py:131-137`) отбирает классы по условию `obj.__module__ == module`, где `obj.__module__` — строка, а `module` — объект модуля, созданный `importlib.util.module_from_spec` (`:122`). Сравнение строки с объектом модуля **всегда ложно**, поэтому ни один внешний `plugins/*.py` плагин не загружается никогда, вопреки `README.md:12` («.py в Python-версии»). C#-ветка DLL-загрузку выполняет (`PluginManager.cs:90-119`), но там действует незадокументированный trust boundary: `Assembly.LoadFrom` + `Initialize()` без подписи/allowlist/изоляции.

### P1-7. Конфигурация и код разошлись (обе реализации)
- **C# игнорирует `voiceVolume`:** `ZereConfig.cs` не содержит свойства `VoiceVolume` → значение `0.5` из `config.json` не читается, громкость TTS всегда `1.0f` (коммит `c02dc95` добавил ключ только для Python).
- **Python игнорирует `ttsEngine`/`voiceReferencePath`:** полей нет в `zere_config.py` → текущий `config/config.json` с `ttsEngine: pocket` на Python-ветке не имеет эффекта; **PocketTTS в Python-порте отсутствует полностью** (grep: 0 упоминаний pocket/StreamPlayer), как и команда «записать голос» (0 совпадений; в C# — `Program.cs:281-301`).
- **Мёртвые ключи в обеих реализациях:** `autoMemory`, `debugMode`, `logLevel` (C#: `ZereConfig.cs:13-17`; Python: `zere_config.py`) объявлены, но **ни разу не читаются** (grep по использованию — 0); Python `whisper_model`, `speech_speed`, `sentence_silence` из `VoiceConfig` тоже не используются — `piper_service.py:120-123` хардкодит `length_scale 1.15` / `sentence_silence 0.4` вместо конфигурируемых значений (C#: 0.2, настраиваемо).
- **Чек-лист зависимостей не соответствует рантайму:** C# `DependencyChecker` проверяет только `ZERE.Voice/Models/ggml-base.bin` (`DependencyChecker.cs:959-984`), тогда как `WhisperService` (`WhisperService.cs:24-31`) предпочитает medium и падает на base — при наличии только medium чекер объявит Whisper отсутствующим; `CheckPiper` (`:987-999`) требует Piper даже при `TtsEngine=pocket`. Python-аналог проверяет `ggml-base.bin` (`dependency_checker.py:819`), но Python-STT использует `faster-whisper` (CT2-формат, ggml ему не нужен — оговорено в докстринге `whisper_service.py`); `whisper_service.is_installed()` (`whisper_service.py:104-121`) возвращает `True`, если `_model_size in _MODEL_SIZES` — т.е. **почти всегда**, даже без скачанной модели.
- **Конфигурация грузится дважды и зависит от рабочей директории:** `Program.cs:12` и `ServiceRegistration.cs:25` вызывают `ZereConfig.Load()` независимо → в DI и в «настройках/записать голос» оказываются **разные объекты** конфига; путь к `config.json`/`plugins.json`/логам вычисляется через `Directory.GetCurrentDirectory()` (`ZereConfig.cs:28-32`, `PluginConfig.cs:12-15`, `LogService.cs:10-17`), поэтому запуск exe из другой папки молча создаёт пустой новый конфиг и отдельный набор плагинов. `Program.cs:54-59` при этом создаёт `DependencyChecker`/`VoiceManager` вручную в обход DI, а `BuildServiceProvider()` (`ServiceRegistration.cs:95`) никогда не dispose-ится — `IDisposable`-синглтоны не освобождаются при выходе.
- **Рекомендация:** свести схему конфига воедино (единый `config.schema`, тест на соответствие полей), один экземпляр конфига через DI, абсолютные пути от корня репозитория/ exe, реализовать или удалить мёртвые ключи, зафиксировать фактический TTS-движок Python-ветки.

### P1-8. Нет тестов, нет CI, нет LICENSE, зависимости не зафиксированы
- 0 тестовых файлов вне `backups/` и vendored-деревьев; pytest в окружении отсутствует; ROADMAP 5.4 («Покрытие тестами») не закрыт.
- `.github/workflows` отсутствует — ни сборка, ни `check_port.py` на коммиты не запускаются автоматически.
- `README.md:77` заявляет MIT, файла `LICENSE` нет.
- `requirements.txt` — 9 зависимостей только с нижними границами (`>=`), lock/ constraints нет; NuGet-версии в csproj зафиксированы точечно, central package management отсутствует.
- **Рекомендация:** минимальный набор unit-тестов (роутеры, FileManager, репозитории, ContextBuilder) + GitHub Actions (build + check_port + pytest) + `LICENSE` + lock-файл.

### P1-9. В git отслеживаются рантайм-артефакты, включая биометрику голоса
`git ls-files` показывает: `zere.db` (БД с потенциально персональными воспоминаниями в других клонах), `voice/reference_output.mp3`, `voice/sample_pocket.wav`, три `ZERE.Voice/Piper/processed_output_*.wav` — суммарно **4.21 МБ** (добавлено коммитами `2d5ff6f`, `c40c731`, `8f03fc8`). `.gitignore:160` игнорирует только `voice/reference.wav`, остальные голосовые сэмплы и БД — не покрыты. Удалить из индекса легко, но **история коммитов уже содержит их навсегда** — нужна очистка истории (`git filter-repo`).
**Рекомендация:** `git rm --cached` для zere.db/аудио, расширить `.gitignore`, очистить историю, пока репозиторий маленький.

### P1-10. Недоверенный ввод в индексе приложений и shell-команды
- `LocalAppDataScanner.cs:38-43` выбирает **самый короткий** `.exe` в дереве (`OrderBy(f => f.Length).FirstOrDefault()`) — легко попадает на updater/uninstaller/crash-handler; `UniversalAppIndexer.Build` (`:47`) безусловно перезаписывает дубликаты, последний зарегистрированный сканер (LocalAppData, Priority 100) вытесняет StartMenu/Registry.
- `RegistryScanner` берёт `DisplayIcon`/`InstallLocation` из реестра (`RegistryScanner.cs:49-130`) — локально изменяемые записи становятся путями запуска; `ApplicationLauncher.Launch` возвращает `true` после `Start()` без проверки факта запуска (`ApplicationLauncher.cs:53-55`); системные приложения передаются **голыми именами** (`calc.exe`, `notepad.exe`, `explorer.exe`, `mspaint.exe`, `ApplicationLauncher.cs:10-15`) в `Process.Start { UseShellExecute = true }` (`:84-88`) — разрешение имени зависит от рабочей директории/PATH, возможен подхват исполняемого файла из каталога запуска.
- `DependencyChecker` интерполирует имя модели из конфига в shell-команды: `cmd.exe /c {command}` (`DependencyChecker.cs:198`), `$"ollama pull {_config.Model}"` (`:359`); Python `_open_url` использует `subprocess.Popen([url], shell=True)` (`dependency_checker.py:68`; URL — захардкоженные константы, риск низкий, но паттерн опасный).
- **Рекомендация:** белый список каталогов/имён для сканеров, фильтр updater/uninstaller, `ArgumentList` вместо строковых shell-команд, валидация `config.Model` по regex.

### P1-11. Перехват общих вопросов памятью вместо LLM
`MemoryQueryHandler.CanHandle` перехватывает все «что такое …», «кто такой …» (`MemoryQueryHandler.cs:23-25`, `memory_query_handler.py:22`) на **втором** месте конвейера — если факта нет в памяти, ответ «Я пока не знаю ответ.» (`:85`), до AIHandler вопрос **не доходит никогда**. Для ассистента с LLM это деградация: «что такое квантовая запутанность» не получит ответа в принципе.
**Рекомендация:** при пустом поиске в памяти — fallthrough к AIHandler.

### P1-12. Установщик распаковывает ZIP через PowerShell со строковой интерполяцией пути
`ExtractPiperZip` подставляет путь найденного архива в single-quoted PowerShell-строку: `Expand-Archive -Path '{zipPath}' …` (`DependencyChecker.cs:662-670`); Python-аналог делает то же самое (`dependency_checker.py:569-579`). Путь ищется `glob("piper*.zip")` по Downloads/ Desktop/ CWD/ корню проекта (`:521-559`) — имя файла с апострофом выходит из кавычек и позволяет выполнить произвольный PowerShell-код (в локальных границах, но это реальный инъекционный вектор). Архив не проверяется по SHA-256/подписи. Аналогичный (латентный) паттерн — `ScreenCaptureService.cs:20-35` вставляет путь Desktop в `'$bmp.Save('{file}')'` (сервис сейчас не зарегистрирован в DI, см. P2-6).
**Рекомендация:** распаковка через `System.IO.Compression`/`zipfile` без shell; валидация имени, canonical path, контрольный SHA-256 фиксированного артефакта.

## 6. Прочие замечания (P2)

| # | Находка | Где |
|---|---|---|
| 0 | **Реального стриминга ответа Ollama в C# нет:** `PostAsync` без `HttpCompletionOption.ResponseHeadersRead` (`OllamaClient.cs:62`) буферизует весь NDJSON до чтения потока; `HttpResponseMessage`/`StringContent` не dispose-ятся | `OllamaClient.cs:57-65` |
| 0а | **Prompt-boundary:** `ContextBuilder.BuildMemory` вставляет **все** воспоминания без лимита длины/числа, `PromptBuilder` не экранирует границы разделителей и не разделяет роли — сохранённые пользователем факты могут раздувать промпт или менять инструкции (prompt injection через память) | `ContextBuilder.cs:17-30`, `PromptBuilder.cs:17-46` |
| 0б | **Утечка внутренних деталей:** `ZereEngine` возвращает пользователю raw `ex.Message` (`ZereEngine.cs:31-35`, Python `engine.py:33-37`), `HandlerPipeline.cs:23-26` печатает текст исключения — локальные пути/параметры/HTTP-ошибки наружу, причём флаг `debugMode` (`config.json:9`) на это поведение **не влияет** (см. P1-7) | — |
| 1 | Исключение обработчика не останавливает конвейер: после сбоя деструктивной команды ответ «подбирает» AIHandler; в C# ошибка только в `Console`, в Python — в `errors.log` | `HandlerPipeline.cs:14-27`, `handler_pipeline.py:15-29` |
| 2 | Системный промпт инжектится дважды (через `PromptBuilder` и повторно как аргумент `GenerateAsync`), а `/api/generate` склеивает всё в один плоский prompt вместо `/api/chat` с ролями | `AIHandler.cs:33-40`, `OllamaClient.cs:43-45`, `ollama_client.py:81-85` |
| 3 | C# `OllamaClient` не имеет кэша ответов (Python — LRU на 64 записи, `ollama_client.py:46-47`); CA2024 — синхронный `EndOfStream` в async-потоке; `GenerateAsync` не принимает `CancellationToken` — отмена ждёт таймаут до 10 минут | `OllamaClient.cs:110`, `:32,62-99` |
| 3а | Парсеры роутеров матчат по `Trim().ToLower()`, но срезают значение из **исходной** строки: при ведущих пробелах имя процесса/приложения искажается (`ProcessCommandRouter.cs:15,31-90`, `process_command_router.py:37-94`, тот же паттерн в `WindowsHandler.cs:122-124`); `Program.cs:252` не делает `Trim()` ввода. Следствие: «удали его»-класс багов и неверные kill/search-цели | — |
| 3б | `ProcessHandler.CanHandle` перехватывает любое «закрой …» раньше Windows/File-обработчиков (`ProcessHandler.cs:37`, порядок `ServiceRegistration.cs:82`) — «закрой папку/окно» уходит в kill-ветку | — |
| 3в | Смена стиля личности не сохраняется: `SettingsMenu` пишет только `ActivePersonalityId`, поле `ActivePersonalityStyle` не записывается (`SettingsMenu.cs:100-107`) → после рестарта стиль сбрасывается; reload плагинов (`:149-153`) чистит списки, но не сбрасывает/не восстанавливает `active_personality` — остаётся ссылка на выгруженный плагин (`plugin_manager.py:155-187`) | — |
| 4 | TTS-сервер `tools/zere_tts_server.py`: без аутентификации, без лимита размера тела запроса (доверяет `Content-Length`, `:172-197`), `--host` конфигурируем (`:213-215`) без enforcement loopback; спасает только `127.0.0.1` по умолчанию и глобальная блокировка синтеза | `zere_tts_server.py:100-215` |
| 5 | Загрузка плагинов исполняет произвольный код (`Assembly.LoadFrom ./plugins/*.dll`, `importlib` для `plugins/**/*.py`) без allowlist/подписи — приемлемо для локального доверия, но должно быть задокументировано как threat model; см. также P1-6 (Python-обнаружение сломано) | `PluginManager.cs:90-119`, `plugin_manager.py:112-147` |
| 5а | Резолвер Ollama опрашивает `http://host.docker.internal:11434` третьим кандидатом (`ollama_url_resolver.py:14-18`) — диалог/память уходят туда, если адрес отвечает; нет политики loopback-only/аутентификации | — |
| 5б | `Process.GetProcesses()` в цикле не dispose-ится — утечка native-хэндлов при частых командах (`ProcessService.cs:11-27`, аналогично `GameGuardian.cs:11-30`) | — |
| 6 | Мёртвый/дублирующийся код: `System/ProcessManager.cs` дублирует `Windows/ProcessService.cs`; `SystemInfoService`, `PowerController`, `ContextService`/`ContextMemory`, `GameStatsDatabase`/`GameStatsRepository` (DI использует in-memory `GameTracker`, `ServiceRegistration.cs:61` — статистика игр теряется между сессиями), `AppIndex` — используются только в бэкапах | `ZERE.Tools/System/*`, `ZERE.Memory/Gaming/*` |
| 7 | Гигиена репо: 163 файла бэкапов в дереве вместо git-тегов; две параллельные реализации удваивают объём поддержки; `InstalledAppScanner` кэширует `app_index.json`, но `UniversalAppIndexer.Build()` перезаписывает его при каждом старте | `backups/`, `UniversalAppIndexer.cs:39-61` |
| 8 | `VolumeCommandRouter` молча обрезает любые 3 цифры в 0..100; `WindowsCommandRouter` содержит опечаточный алиас `hybernate` (`:59`) и матчит «заморозь» как sleep | `VolumeCommandRouter.cs:13-18`, `WindowsCommandRouter.cs:52-63` |
| 8а | Повреждённый `config.json` валит запуск: `ZereConfig.Load` не перехватывает `JsonException` (`ZereConfig.cs:57-64`); `OllamaClient` не валидирует положительный timeout (`:17-20`) | — |
| 9 | README/AGENTS-дрейф: заявлено 6 стилей личности, включая Custom — фактически доступно 5 (`GetAvailableStyles()` исключает Custom, `PersonalityPlugin.cs:73-78`); `AGENTS.md` перечисляет `System/`-сервисы как активные, хотя они не зарегистрированы в DI | `README.md:13`, `AGENTS.md` |
| 10 | Python-порт не импортируется вне Windows (`winreg` на верхнем уровне в `registry_scanner.py:6`, `app_paths_scanner.py:5`) — для CI придётся использовать Windows-раннер или mocks; `DependencyChecker` в Python использует `shell=True` в `_open_url` (`dependency_checker.py:68`) | — |
| 11 | Зависимости невоспроизводимы: `numpy` импортируется в 5 модулях голоса (`audio_recorder.py:17` и др.), но **не объявлен** в `requirements.txt`; нет `pyproject.toml`/lock/hashes/`global.json` | `requirements.txt:1-9` |
| 12 | Бинарники `tools/uvw.exe`/`uvx.exe` (2×349 КБ) попали в историю коммитом `8f03fc8` и удалены в `c37ccbd`, но остаются в git-истории навсегда | git history |
| 13 | Python Piper при отсутствии `{voice}.onnx` молча берёт **первый** `*.onnx` из папки (`piper_service.py:241-253`) — возможна загрузка чужой модели; C#-аналог имеет тот же фолбэк | — |
| 14 | `MemoryRepository.search` не экранирует `%`/`_` пользовательского запроса в `LIKE` (`memory_repository.py:112-123`) — не инъекция (параметризовано), но неожиданные совпадения | — |
| 15 | `VoiceManager.listen()` вызывает `self._recorder.record()` **вне** try-блока (`voice_manager.py:91-106`) — ошибка PortAudio/микрофона роняет voice-цикл, тогда как сбои транскрибции ловятся | — |
| 16 | `AppIndex.cs` (schema version) объявлен, но не используется ни в одном месте активного кода (grep — только определения класса) | `AppIndex.cs:3-9` |

---

## 7. Сильные стороны

1. **Чистая архитектура и слойность** — зависимости направлены внутрь, DI-регистрация в одном месте, единый интерфейс обработчиков.
2. **Параметризованный SQL** во всех репозиториях (C# и Python) — SQL-инъекций не найдено.
3. **Отказоустойчивость:** retry/таймауты Ollama, reconnect Whisper/Piper, предзагрузка модели, таймаут синтеза 300 с, фолбэк TTS pocket→piper, `errors.log`, кэш ответов (Python) — ROADMAP «Фаза 1 «Стабильность»» в основном закрыт.
4. **Концепция SafeActionManager** для power-действий (правильное направление: нужен TTL и более строгое подтверждение — см. P0-3).
5. **Индексация приложений со скорингом** (exact → alias → prefix → substring + приоритет, `UniversalAppIndexer.cs:63-95`) и таблица алиасов.
6. **Документация:** `ARCHITECTURE.md`, `ROADMAP.md`, `PYTHON_PORT_SPEC.md`, research-документы — заметно выше среднего для личного проекта.
7. **Гигиена секретов:** `.gitignore` покрывает ключи/модели/`voice/reference.wav`; сканером секретов в треке ничего не найдено.
8. **Структурный контроль порта:** `scripts/check_port.py` реально работает (126/125), спецификация порта формализована.
9. **Обе сборки зелёные:** `dotnet build -c Release` — 0 ошибок; `compileall` — чисто.

---

## 8. Рекомендации по приоритетам

**Немедленно (P0):**
1. Добавить сохранение истории в оба engine + разворот порядка в `BuildHistory` (P0-1).
2. Нормализация и ограничение путей в `FileManager`, запрет перезаписи, подтверждение удаления (P0-2).
3. TTL и строгое подтверждение power-действий, учёт отрицаний, честный результат kill (P0-3).

**Ближайший спринт (P1):**
4. Починить перехват «найди файл» и ветку «удали его» (P1-4, P1-5).
5. Подключить `ICommandHandlerPlugin` к pipeline либо поправить документацию (P1-6).
6. Унифицировать конфигурацию C#/Python, убрать мёртвые ключи, определиться со статусом PocketTTS в Python (P1-7).
7. Минимальные тесты + GitHub Actions + LICENSE + lock-файл (P1-8).
8. Вычистить рантайм-артефакты и биометрику из git-истории (P1-9).
9. Ужесточить сканеры приложений и shell-вызовы (P1-10), fallthrough «что такое» к LLM (P1-11).
10. Убрать PowerShell/shell из установщика Piper, проверять артефакты по SHA-256 (P1-12).

**Планово (P2):** `/api/chat` вместо `/api/generate`, убрать дубль системного промпта, кэш ответов в C#, удалить мёртвый код, вынести `backups/` в теги, аутентификация/лимиты TTS-сервера, задокументировать threat model плагинов, синхронизировать README/AGENTS с реальностью.

---

## 9. Методика, подтверждённые проверки и ограничения

**Выполненные проверки (воспроизводимо):**
- `dotnet.exe build ZERE.slnx -c Release` → успех, 1 warning (CA2024, `OllamaClient.cs:110`).
- `python3 -m compileall zere main.py` → exit 0; `python3 scripts/check_port.py` → 126 файлов/125 модулей.
- Интроспекция `zere.db`: `PRAGMA integrity_check` = ok, все таблицы пусты.
- Динамические пробы: path traversal в `FileManager` (внеизолированный каталог); «удали его» → «Команда файлов не распознана»; плагин-обработчик не попадает в pipeline; прогон engine без сохранения истории; матчёт отрицаний на ключевых словах Windows-роутера.
- `git ls-files`/`git log --all --` для аудита отслеживаемых артефактов; grep-сканы секретов, мёртвых ключей конфига, вызовов `Save`.

**Ограничения:**
1. Среда — Linux; полноценный рантайм (Windows API, реестр, COM-громкость, kill процессов, Whisper/Piper/PocketTTS, живой Ollama) **не запускался** — выводы по этим подсистемам статические.
2. `faster_whisper`/`pytest` не установлены — динамические тесты голосового стека не выполнялись; аудит вёлся тремя параллельными проверками (ядро, инструменты/безопасность, голос), каждая из которых завершилась; все содержательные утверждения из их отчётов дополнительно сверены с кодом перед включением в этот отчёт.
3. Аудит зависимостей (CVE/SBOM) и сканирование всей git-истории на секреты не проводились.
4. Эксплуатационная проверка «на конкретном ПК» (какие `.exe` реально попадут в индекс, поведение shutdown) требует Windows-окружения.

*Отчёт подготовлен как результат полного аудита репозитория 2026-09-23.*
