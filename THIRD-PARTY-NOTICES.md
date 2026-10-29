# Сторонние компоненты ZERE

ZERE распространяется по лицензии MIT (см. `LICENSE`). Ниже — компоненты,
которые ZERE использует или устанавливает, и их лицензии. Файл нужен для
прозрачности дистрибутива и будущего коммерческого релиза.

> **Перед коммерческим распространением проверьте строки со статусом
> «уточнить».** Модели синтеза речи и LLM распространяются по своим
> лицензиям, которые могут запрещать коммерческое использование. Это не
> юридическое заключение.

## Python-зависимости (`requirements.txt`)

| Компонент | Назначение | Лицензия |
|---|---|---|
| requests | HTTP-клиент | Apache-2.0 |
| numpy | массивы, аудио | BSD-3-Clause |
| faster-whisper / CTranslate2 | STT Whisper (откат) | MIT |
| sherpa-onnx | STT GigaAM и KWS | Apache-2.0 |
| sounddevice / PortAudio | ввод и вывод звука | MIT |
| pycaw | громкость Windows (COM) | MIT |
| comtypes | COM-обвязка | MIT |
| psutil | процессы и система | BSD-3-Clause |
| mss | снимки экрана | MIT |
| pillow | картинки для Paint | MIT-CMU |
| wmi | WMI-запросы (Windows) | MIT |
| onnxruntime | инференс KWS | MIT |
| soundfile | запись WAV в сайдкарах | BSD-3-Clause |
| pypdf | PDF в конспекторе | BSD-3-Clause |
| pywebview | окно приложения (WebView2) | BSD-3-Clause |

## Зависимости разработки (`requirements-dev.txt`)

| Компонент | Лицензия |
|---|---|
| pytest, pytest-cov | MIT |
| PyYAML | MIT |
| ruff | MIT |

## C#-зависимости (`ZERE.*/*.csproj`)

| Компонент | Назначение | Лицензия |
|---|---|---|
| NAudio | вывод звука в `ZERE.Speaker` | MIT |
| Microsoft.Data.Sqlite | SQLite в C#-редакции | MIT |
| Microsoft.ML.OnnxRuntime | KWS-модель | MIT |
| Whisper.net | STT Whisper (C#) | MIT |
| Microsoft.Web.WebView2 | окно панели (C#) | проприетарная Microsoft (распространяется с Edge WebView2 Runtime) |
| .NET 10 / System.* | платформа | MIT |

## Модели и веса

| Модель | Где | Статус |
|---|---|---|
| GigaAM-v3 punct (~163 МБ) | STT по умолчанию, качается при первом запуске | уточнить лицензию у правообладателя перед коммерческим релизом |
| Silero v5_5_ru (145 МБ) | русский TTS | уточнить лицензию модели (у апстрима отдельная лицензия на веса) |
| t-tech/T-lite-it-2.1 (Ollama) | LLM по умолчанию | Apache-2.0 |
| qwen3.5 | LLM для слабых ПК | Apache-2.0 |
| KWS-модель `wake_*.onnx` | слово-триггер | обучена в проекте (см. `docs/WAKE_WORD.md`) |
| xVibePocketTTS | клонирование голоса, ставится отдельно | MIT (по данным апстрима; пакет не входит в репозиторий) |

## Внешние программы

ZERE **не включает** в дистрибутив Ollama, Node.js, `uv` и ffmpeg — они
устанавливаются отдельно и распространяются по своим лицензиям
(Ollama — MIT, Node.js — MIT, uv — MIT/Apache-2.0, ffmpeg — LGPL/GPL в
зависимости от сборки).

## Товарные знаки

Название «ZERE» может пересекаться с товарным знаком Marvel Characters, Inc.
(см. `docs/COMMERCIAL_RELEASE_PLAN.md`, §3.2). Для коммерческого выпуска
нужен ребрендинг или юридическое заключение.
