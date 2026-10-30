# Установка ZERE на Windows

Установщик полностью готовит окружение: Python-зависимости, Ollama с моделью,
голосовые компоненты (GigaAM/Whisper + uv для Silero), ярлыки и лаунчер. Все
скачиваемые артефакты проверяются по **SHA-256**.

## Способы установки

### 1. Готовый установщик — `ZereSetup.exe` (рекомендуется)

Один exe: двойной клик, мастер на русском, права администратора не нужны.
Мастер спрашивает папку (по умолчанию `%LOCALAPPDATA%\Programs\ZERE`),
распаковывает дистрибутив, запускает `installer\install.ps1` (ход установки
виден в окне консоли), после успеха регистрирует деинсталлятор в «Установка и
удаление программ» и запускает `zere.exe` — окно приложения.

В мастере есть галочка **«Установить без Ollama»**: тогда Ollama и модель не
ставятся вовсе (не качаются ~5 ГБ), а ZERE работает без локальной модели —
нужен облачный ключ, он вводится в панели на экране «ИИ». Без ключа ZERE всё
равно запускается: окно и панель работают, чат честно просит подключить ключ
или поставить модель. Галочка передаёт `install.ps1 -SkipOllama`.

Для ПК, где ZERE работает только через API-ключ, есть сборка, где эта галочка
стоит сразу:

```powershell
# вариант «только облачный ключ»: /SILENT тоже идёт без Ollama
powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1 -NoOllama
```

Вариант записывается в `config\build-info.json` (`"variant": "no-ollama"`).
Обратный ключ `/WITHOLLAMA` ставит Ollama и в такой сборке, а `/SKIPOLLAMA`
отключает её в обычной.

```powershell
# сборка установщика (git-архив + системный csc.exe, Inno Setup не нужен)
powershell -ExecutionPolicy Bypass -File installer\build-installer.ps1
```

Результат: `installer\Output\ZereSetup.exe`. Тихая установка для автоматизации:

```powershell
installer\Output\ZereSetup.exe /SILENT "/DIR=C:\ZERE" /NOLAUNCH
# без Ollama и локальной модели — только облачный ключ
installer\Output\ZereSetup.exe /SILENT /SKIPOLLAMA "/DIR=C:\ZERE" /NOLAUNCH
```

Коды возврата: `0` — установлено, `1` — ошибка (подробности в
`installer\install-log.txt` папки установки).

**Почему установщик собран `csc.exe`, а не Inno Setup.** На Windows 11 с
включённым Smart App Control (WDAC) свежесобранный неподписанный `Setup.exe`
блокируется: «Политика ограничила приложение. Обратитесь к администратору»
(событие CodeIntegrity 3077/3118). Файлы, собранные системным компилятором,
этот фильтр пропускает — так же запускается `zere.exe`. Поэтому мастер
установки собирается им, а не ISCC.

**Подпись снимает блокировку окончательно.** Smart App Control пропускает
только подписанное доверенным УЦ. В проекте это встроено:
`build-installer.ps1 -CertThumbprint <отпечаток>` подписывает `zere.exe` и
`ZereSetup.exe` с меткой времени; CI умеет подписывать из секрета. Как
получить сертификат бесплатно (открытый проект) или за €25 — [SIGNING.md](SIGNING.md).

### 2. Быстрый (из репозитория)


Двойной клик по **`installer\Install-Zere.bat`** — или из консоли:

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

### 3. Проверка без изменений (dry-run)

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1 -CheckOnly
```

Показывает состояние всех компонентов и что потребуется сделать.
Код возврата: `0` — всё готово, `1` — требуются действия.

### 4. Запасной Setup.exe (Inno Setup)

```powershell
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1            # обе редакции (по умолчанию)
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -Edition python
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -WorkingTree # с некоммиченными изменениями
```

Результат: `installer\Output\ZereInstaller.exe` — стандартный мастер
установки Windows (установка в `%LOCALAPPDATA%\Programs\ZERE`, без прав
администратора, с деинсталлятором в «Установка и удаление программ»).
Годится там, где Smart App Control выключен или установщик подписан:
неподписанный `ZereInstaller.exe` на Windows 11 с SAC блокируется (см. §1).

Требования для сборки Setup: [Inno Setup 6](https://jrsoftware.org/isdl.php)
и git. По умолчанию staged-дистрибутив формируется из `git archive HEAD`
(только отслеживаемые файлы — без `.git`, `.venv`, `bin/obj`, `zere.db`,
`logs`), а редакция — `both`: дистрибутив несёт и Python-, и C#-версию.
Облегчённая сборка только с Python — `-Edition python`.

### Версия дистрибутива

Версия берётся из `config/config.json` (`"version"`) и передаётся в Inno Setup
как `MyAppVersion`; четвёртое поле `FileVersion` — **номер сборки** (число
коммитов git). Поэтому две сборки одной версии различимы в свойствах файла:

```
FileVersion    1.9.0.118      ← версия из конфига + номер сборки
ProductVersion 1.9.0
```

Версия дублируется ещё в пяти местах (значения по умолчанию): `build-setup.ps1`,
`DefaultConfigJson` в `install.ps1`, `Zere.iss`, `zere_config.py`,
`ZereConfig.cs`. Их совпадение проверяет `tests/test_installer.py`
(`test_version_sources_agree`) — при смене версии правьте все шесть.

## Что устанавливает установщик

| Компонент | Источник | Проверка |
|---|---|---|
| Python 3.12+ | winget (`Python.Python.3.14` → `3.13` → `3.12`) | запуск интерпретатора |
| Виртуальное окружение `.venv` | `requirements.txt` (pip) | весь список пакетов одним запуском Python (`importlib.util.find_spec`) |
| Ollama | winget (`Ollama.Ollama`), сервер на `127.0.0.1:11434` | `ollama list` |
| Модель LLM | из `config/config.json` (по умолчанию русская `t-tech/T-lite-it-2.1:q4_K_M`) | `ollama pull` |
| Модель GigaAM-v3 (~163 МБ, основной STT) | GitHub `k2-fsa/sherpa-onnx` release `asr-models` | SHA-256 + размер, распаковка `tar -xjf` |
| Whisper `ggml-base.bin` (~141 МБ, откат STT) | HuggingFace `ggerganov/whisper.cpp` | SHA-256 + размер |
| Менеджер Python `uv` (~18 МБ) | GitHub `astral-sh/uv` release 0.12.23 | SHA-256 + размер |
| Web-панель | `panel/dist` (сборка npm, если dist отсутствует) | наличие `dist/index.html` |
| Окно приложения `zere.exe` | компиляция `zere/desktop/launcher/ZereLauncher.cs` системным `csc.exe` (если exe нет) | наличие `zere.exe` |
| Окно (pywebview + WebView2) | `requirements.txt` + Runtime Edge WebView2 (есть в Windows 11/с Edge) | `import webview`, каталог `EdgeWebView\Application` |
| .NET SDK 10 + C#-сборка | winget + `dotnet publish` (только `-Edition dotnet/both`) | `publish\app\ZERE.App.exe` |
| Лаунчер, ярлыки, манифест | генерируются | — |

Контрольные суммы (`SHA-256`):

```
sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16.tar.bz2
                            f9620a0099019c6afcee26525ef9ed3297fa50dd5691c1902af0c948fc1a470b
ggml-base.bin            60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe
uv-x86_64-pc-windows-msvc.zip
                            75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90
```

Сам Silero отдельным артефактом не скачивается: модель (145 МБ) качается при
первом синтезе, а torch ставит `uv` в своё окружение — см.
[docs/TTS_SILERO.md](TTS_SILERO.md).

Silero (русский голос) отдельным артефактом тоже не скачивается: 145 МБ модели
`v5_5_ru.pt` качаются при первом синтезе в `ZERE.Voice/Silero/` —
см. [docs/TTS_SILERO.md](TTS_SILERO.md).

## Зависимости Python и лог установки

Проверка идёт по **всему** списку из `requirements.txt`: имена пакетов из
таблицы `$RequiredModules` в `install.ps1` проверяются одним запуском Python
через `importlib.util.find_spec` (тест `tests/test_installer.py` сверяет
таблицу с `requirements.txt`). Отсутствие любого из них — критичная ошибка, и
`pip install -r requirements.txt` запускается **всегда**, а не только при
создании `.venv`: иначе частично установленное окружение считалось готовым, и
ZERE падал на старте с `No module named ...`, хотя установщик отчитался об
успехе. Исключение — `torch` для Silero и модель TTS: без них ZERE работает в текстовом режиме.

Полный вывод установщика (в том числе pip) пишется в
`installer\install-log.txt` — файл переживает закрытие окна консоли, и по нему
видно, на каком пакете или файле сорвалась установка. Путь к логу печатается в
конце отчёта, а Setup.exe показывает его в окне ошибки, если `install.ps1`
вернул ненулевой код (раньше мастер писал «Установка завершена» при любом
исходе настройки).

## Параметры `install.ps1`

| Параметр | Назначение |
|---|---|
| `-Prefix <путь>` | корень установки (по умолчанию — репозиторий; Inno передаёт `{app}`) |
| `-Edition python\|dotnet\|both` | какую редакцию готовить (по умолчанию `python`) |
| `-Model <имя>` | модель Ollama (по умолчанию из `config/config.json`) |
| `-CheckOnly` | только проверка, без изменений |
| `-Yes` | без вопросов (для Inno Setup и автоматизации) |
| `-NoLaunch` | не предлагать запуск в конце |
| `-SkipOllama` | не трогать Ollama и модель |
| `-SkipVoice` | не качать голосовые артефакты |
| `-SkipShortcuts` | не создавать ярлыки |

Установка идемпотентна: повторный запуск пропускает готовые компоненты
(статус `[SKIP]`) и чинит недостающее.

## Что создаётся

- `.venv\` — виртуальное окружение Python
- `zere.exe` — приложение: одно окно ZERE, без консоли и без браузера
  (ярлыки ведут сюда)
- `ZERE.bat` в корне — запасной лаунчер (`zere.exe` → `.venv`, иначе
  `publish\app\ZERE.App.exe`, иначе системный `python`)
- Ярлык `ZERE.lnk` на рабочем столе и в меню «Пуск» — на `zere.exe`.
  Браузерный ярлык `ZERE - panel.url` больше не создаётся (старый удаляется):
  он открывал панель в браузере, а ZERE — оконное приложение
- `logs\desktop.log` — журнал запуска приложения (вывод Python без консоли)
- `data\webview\` — профиль WebView2: тема и язык панели (gitignored)
- `installer\install-manifest.json` — манифест установки (читается
  деинсталлятором)
- `installer\install-log.txt` — полный лог установки (перезаписывается при
  каждом запуске; в git не попадает)
- Недостающие `config\config.json` / `config\plugins.json`
- Только для `ZereSetup.exe`: `ZereUninstall.exe` рядом с программой и запись
  в `HKCU\...\Uninstall\ZERE` — деинсталлятор в «Установка и удаление
  программ»

Коды возврата: `0` — успех, `1` — есть критичные ошибки (см. `[FAIL]` в
отчёте), `2` — фатальная ошибка (отчёт всё равно печатается).

## Удаление

```powershell
powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1             # ярлыки, .venv, publish, манифест
powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1 -RemoveAssets # + голосовые артефакты
powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1 -PurgeData    # + данные: zere.db, logs, backups, voice
```

Или двойным кликом по `installer\Uninstall-Zere.bat`.
Деинсталлятор **не трогает исходный код и git-репозиторий**. Python, Ollama и
модель Ollama удаляются только вручную (`ollama rm <модель>`).

## Структура `installer/`

```
installer/
├── install.ps1          # основная логика установки
├── uninstall.ps1        # деинсталлятор
├── ZereLauncher.bat   # шаблон лаунчера ZERE.bat (ASCII/CRLF)
├── Install-Zere.bat   # двойной клик → install.ps1
├── Uninstall-Zere.bat # двойной клик → uninstall.ps1
├── ZereSetup.cs       # установщик-мастер (WinForms, C# 5): payload + install.ps1
├── build-installer.ps1  # сборка ZereSetup.exe (stage из git + csc)
├── Zere.iss           # Inno Setup: запасной Setup.exe
├── build-setup.ps1      # сборка Setup.exe (stage из git + ISCC)
├── install-manifest.json# (генерируется) манифест установки
├── install-log.txt      # (генерируется) полный лог установки
└── Output/              # (генерируется) ZereSetup.exe, ZereInstaller.exe
```

## Диагностика

| Симптом | Причина / решение |
|---|---|
| `winget недоступен` | Установите «App Installer» из Microsoft Store или добавьте `%LOCALAPPDATA%\Microsoft\WindowsApps` в PATH |
| UAC при установке .NET SDK | SDK ставится системно — подтвердите окно или установите SDK вручную |
| `сервер Ollama не запустился` | Запустите `ollama serve` вручную; проверьте, не занят ли порт 11434 |
| Модель/артефакты не скачались | Нет интернета или блокировка сети; скачайте вручную по ссылкам из таблицы и повторите запуск — установщик проверит SHA-256 |
| `файл не прошёл проверку SHA-256` | Повреждённая загрузка или изменился апстрим-файл — сообщите, обновим контрольную сумму |
| `No module named ...` при запуске ZERE | Откройте `installer\install-log.txt`: видно, что именно не поставил pip. Повторный запуск `installer\install.ps1` доустановит недостающие пакеты (шаг не пропускается, даже если часть зависимостей уже стоит) |
| Setup.exe: «Настройка ZERE завершилась с ошибкой (код N)» | Файлы скопированы, окружение настроено не полностью — причина в `installer\install-log.txt`; устраните её и запустите `installer\install.ps1` ещё раз |
| `ZereInstaller.exe` не запускается: «Политика ограничила приложение» | Windows 11 Smart App Control блокирует неподписанный Setup.exe от Inno Setup. Используйте `ZereSetup.exe` (собран системным `csc.exe`, этот фильтр его пропускает), `installer\Install-Zere.bat` или подпишите установщик сертификатом |
| `ZereSetup.exe` запустился, но установка падает | Откройте `installer\install-log.txt` в папке установки: мастер только распаковывает файлы и запускает `install.ps1`, вся настройка — там |
| `[FAIL] .venv и зависимости — нет: ...` | В отчёте перечислены отсутствующие модули: обычно это обрыв сети на PyPI или отсутствие колеса под выбранную версию Python; ставьте `pip install -r requirements.txt` вручную и смотрите хвост ошибки в логе |
| Голос не работает | `python -m compileall main.py zere`; проверьте `ttsEngine` в `config\config.json` (допустимо `silero` или `pocket` для C#); для Silero — `tools\uv.exe` и `torch` в его окружении, 145 МБ модели в `ZERE.Voice\Silero` |
| Панель не отвечает | Она запускается вместе с ZERE на `http://127.0.0.1:8080` |
| `zere.exe`: «ZERE уже запущен», а окна нет | Остался процесс `pythonw.exe` от прошлого запуска: завершите его в диспетчере задач и запустите снова |
| `zere.exe` открыл панель в браузере | Нет pywebview или WebView2 Runtime: `pip install pywebview`, поставьте «Microsoft Edge WebView2 Runtime»; подробности — `logs\desktop.log` |
| `zere.exe` ничего не делает | Смотрите `logs\desktop.log`: лаунчер пишет туда старт и последние ошибки, а при падении первых 7 секунд показывает окно с концом журнала |
| Нужна консоль для отладки | `zere.exe --console` или `python main.py` (панель — в браузере) |
| `zere.exe`: «заблокирован политикой Device Guard» | Windows 11 Smart App Control блокирует неподписанный exe. Ярлык ZERE и `ZERE.bat` в этом режиме запускают `pythonw.exe main.py --desktop`; отключение SAC — в «Безопасность Windows» (обратно без переустановки не включается) |

Логи самого ZERE: `logs\`. Логи панели и контрактные тесты — см.
`docs/WEB_PANEL_PLAN.md`.
