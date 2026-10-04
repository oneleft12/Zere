# Установка JARVIS на Windows

Установщик полностью готовит окружение: Python-зависимости, Ollama с моделью,
голосовые компоненты (GigaAM/Whisper/Piper), ярлыки и лаунчер. Все скачиваемые
артефакты проверяются по **SHA-256**.

## Способы установки

### 1. Быстрый (из репозитория)

Двойной клик по **`installer\Install-Jarvis.bat`** — или из консоли:

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
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1            # редакция python
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -Edition both
powershell -ExecutionPolicy Bypass -File installer\build-setup.ps1 -WorkingTree # с некоммиченными изменениями
```

Результат: `installer\Output\JarvisInstaller.exe` — стандартный мастер
установки Windows (установка в `%LOCALAPPDATA%\Programs\JARVIS`, без прав
администратора, с деинсталлятором в «Установка и удаление программ»).

Требования для сборки Setup: [Inno Setup 6](https://jrsoftware.org/isdl.php)
и git. По умолчанию staged-дистрибутив формируется из `git archive HEAD`
(только отслеживаемые файлы — без `.git`, `.venv`, `bin/obj`, `jarvis.db`,
`logs`).

## Что устанавливает установщик

| Компонент | Источник | Проверка |
|---|---|---|
| Python 3.12+ | winget (`Python.Python.3.14` → `3.13` → `3.12`) | запуск интерпретатора |
| Виртуальное окружение `.venv` | `requirements.txt` (pip) | `pip show faster-whisper` + `sherpa-onnx` |
| Ollama | winget (`Ollama.Ollama`), сервер на `127.0.0.1:11434` | `ollama list` |
| Модель LLM | из `config/config.json` (по умолчанию `qwen3.5:2b`) | `ollama pull` |
| Модель GigaAM-v3 (~163 МБ, основной STT) | GitHub `k2-fsa/sherpa-onnx` release `asr-models` | SHA-256 + размер, распаковка `tar -xjf` |
| Whisper `ggml-base.bin` (~141 МБ, откат STT) | HuggingFace `ggerganov/whisper.cpp` | SHA-256 + размер |
| Движок Piper (~21 МБ) | GitHub `rhasspy/piper` release 2023.11.14-2 | SHA-256 + размер |
| Голос `ru_RU-ruslan-medium` (~60 МБ) | HuggingFace `rhasspy/piper-voices` | SHA-256 + размер |
| Web-панель | `panel/dist` (сборка npm, если dist отсутствует) | наличие `dist/index.html` |
| .NET SDK 10 + C#-сборка | winget + `dotnet publish` (только `-Edition dotnet/both`) | `publish\app\JARVIS.App.exe` |
| Лаунчер, ярлыки, манифест | генерируются | — |

Контрольные суммы (`SHA-256`):

```
sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16.tar.bz2
                            f9620a0099019c6afcee26525ef9ed3297fa50dd5691c1902af0c948fc1a470b
ggml-base.bin            60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe
piper_windows_amd64.zip  f3c58906402b24f3a96d92145f58acba6d86c9b5db896d207f78dc80811efcea
ru_RU-ruslan-medium.onnx 72a5f88e0b20928064eb45d88e1daa21f8af62d18613580d32cbb4aed48dcf7f
ru_RU-ruslan-medium.onnx.json 706a4fb17bc304abd07809b552deae615e64dcbffbfbd09854ba37ca59e88117
```

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
- `JARVIS.bat` в корне — лаунчер (Python-редакция → `.venv`, иначе
  `publish\app\JARVIS.App.exe`, иначе системный `python`)
- Ярлыки `JARVIS.lnk` на рабочем столе и в меню «Пуск», `JARVIS - panel.url`
  (web-панель `http://127.0.0.1:8080`)
- `installer\install-manifest.json` — манифест установки (читается
  деинсталлятором)
- Недостающие `config\config.json` / `config\plugins.json`

Коды возврата: `0` — успех, `1` — есть критичные ошибки (см. `[FAIL]` в
отчёте), `2` — фатальная ошибка (отчёт всё равно печатается).

## Удаление

```powershell
powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1             # ярлыки, .venv, publish, манифест
powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1 -RemoveAssets # + голосовые артефакты
powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1 -PurgeData    # + данные: jarvis.db, logs, backups, voice
```

Или двойным кликом по `installer\Uninstall-Jarvis.bat`.
Деинсталлятор **не трогает исходный код и git-репозиторий**. Python, Ollama и
модель Ollama удаляются только вручную (`ollama rm <модель>`).

## Структура `installer/`

```
installer/
├── install.ps1          # основная логика установки
├── uninstall.ps1        # деинсталлятор
├── JarvisLauncher.bat   # шаблон лаунчера JARVIS.bat (ASCII/CRLF)
├── Install-Jarvis.bat   # двойной клик → install.ps1
├── Uninstall-Jarvis.bat # двойной клик → uninstall.ps1
├── Jarvis.iss           # Inno Setup: готовый Setup.exe
├── build-setup.ps1      # сборка Setup.exe (stage из git + ISCC)
├── install-manifest.json# (генерируется) манифест установки
└── Output/              # (генерируется) JarvisInstaller.exe
```

## Диагностика

| Симптом | Причина / решение |
|---|---|
| `winget недоступен` | Установите «App Installer» из Microsoft Store или добавьте `%LOCALAPPDATA%\Microsoft\WindowsApps` в PATH |
| UAC при установке .NET SDK | SDK ставится системно — подтвердите окно или установите SDK вручную |
| `сервер Ollama не запустился` | Запустите `ollama serve` вручную; проверьте, не занят ли порт 11434 |
| Модель/артефакты не скачались | Нет интернета или блокировка сети; скачайте вручную по ссылкам из таблицы и повторите запуск — установщик проверит SHA-256 |
| `файл не прошёл проверку SHA-256` | Повреждённая загрузка или изменился апстрим-файл — сообщите, обновим контрольную сумму |
| Голос не работает | `python -m compileall main.py jarvis`, наличие `JARVIS.Voice\Piper\piper.exe`, `espeak-ng-data\`, `*.onnx` |
| Панель не отвечает | Она запускается вместе с JARVIS на `http://127.0.0.1:8080` |

Логи самого JARVIS: `logs\`. Логи панели и контрактные тесты — см.
`docs/WEB_PANEL_PLAN.md`.
