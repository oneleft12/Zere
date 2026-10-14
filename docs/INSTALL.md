# Установка ZERE на Windows

Установщик полностью готовит окружение: Python-зависимости, Ollama с моделью,
голосовые компоненты (GigaAM/Whisper + uv для ChatTTS), ярлыки и лаунчер. Все
скачиваемые артефакты проверяются по **SHA-256**.

## Способы установки

### 1. Быстрый (из репозитория)

Двойной клик по **`installer\Install-Zere.bat`** — или из консоли:

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

### 2. Проверка без изменений (dry-run)

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1 -CheckOnly
```

Показывает состояние всех компонентов и что потребуется сделать.
Код возврата: `0` — всё готово, `1` — требуются действия.

### 3. Готовый Setup.exe (Inno Setup)

```powershell
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1            # обе редакции (по умолчанию)
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -Edition python
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -WorkingTree # с некоммиченными изменениями
```

Результат: `installer\Output\ZereInstaller.exe` — стандартный мастер
установки Windows (установка в `%LOCALAPPDATA%\Programs\ZERE`, без прав
администратора, с деинсталлятором в «Установка и удаление программ»).

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
FileVersion    1.8.0.118      ← версия из конфига + номер сборки
ProductVersion 1.8.0
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

Сам ChatTTS отдельным артефактом не скачивается: `uv` приносит его при первом
синтезе (~2–3 ГБ с torch) — см. [docs/TTS_CHATTTS.md](TTS_CHATTTS.md).

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
успехе. Исключение — `ChatTTS`: без него ZERE работает в текстовом режиме.

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
- `ZERE.bat` в корне — лаунчер (Python-редакция → `.venv`, иначе
  `publish\app\ZERE.App.exe`, иначе системный `python`)
- Ярлыки `ZERE.lnk` на рабочем столе и в меню «Пуск», `ZERE - panel.url`
  (web-панель `http://127.0.0.1:8080`)
- `installer\install-manifest.json` — манифест установки (читается
  деинсталлятором)
- `installer\install-log.txt` — полный лог установки (перезаписывается при
  каждом запуске; в git не попадает)
- Недостающие `config\config.json` / `config\plugins.json`

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
├── Zere.iss           # Inno Setup: готовый Setup.exe
├── build-setup.ps1      # сборка Setup.exe (stage из git + ISCC)
├── install-manifest.json# (генерируется) манифест установки
├── install-log.txt      # (генерируется) полный лог установки
└── Output/              # (генерируется) ZereInstaller.exe
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
| `[FAIL] .venv и зависимости — нет: ...` | В отчёте перечислены отсутствующие модули: обычно это обрыв сети на PyPI или отсутствие колеса под выбранную версию Python; ставьте `pip install -r requirements.txt` вручную и смотрите хвост ошибки в логе |
| Голос не работает | `python -m compileall main.py zere`; проверьте `ttsEngine` в `config\config.json`; для ChatTTS — `tools\uv.exe` (первый синтез тянет ~2–3 ГБ с torch), для Silero — `torch` в окружении и 145 МБ модели в `ZERE.Voice\Silero` |
| Панель не отвечает | Она запускается вместе с ZERE на `http://127.0.0.1:8080` |

Логи самого ZERE: `logs\`. Логи панели и контрактные тесты — см.
`docs/WEB_PANEL_PLAN.md`.
