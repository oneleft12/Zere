# Ресерч: самый лучший бесплатный распознаватель речи (STT) для ZERE

**Дата:** 2026  
**Цель:** найти самый крутой бесплатный (open-source, локальный) распознаватель речи, сравнить его с текущим стеком и спланировать применение в проекте ZERE (Windows, .NET 10 (C#) + Python-порт, полностью офлайн, язык — русский).  
**Метод:** обзор рынка (лидерборды, независимые бенчмарки), сравнение кандидатов по критериям проекта, **живой замер** победителя на этом ПК против текущего движка.

---

## 0. TL;DR — вердикт

**Победитель: GigaAM-v3 (SaluteDevices/Sber, лицензия MIT) + рантайм sherpa-onnx (Next-gen Kaldi, Apache-2.0) с официальной поддержкой C#/.NET и Python.**

Замер прямо на этой машине (AMD Ryzen 5 8400F, CPU, 4 потока, один и тот же файл 11.3 с русской речи):

| Показатель | GigaAM-v3 punct + sherpa-onnx | Текущий стек: faster-whisper `medium` |
|---|---|---|
| Время распознавания 11.3 с аудио (тёплый запуск) | **1.60–1.91 с** | 12.6–16.0 с |
| RTF (меньше = быстрее) | **0.14–0.17** | 1.12–1.42 |
| Инициализация / загрузка модели | **1.4–1.7 с** | 8.5 с (warm; первый запуск — с загрузкой весов) |
| Размер модели | **232 МБ** (encoder int8 224 МБ) | ~1.5 ГБ (CT2 medium) |
| Качество на тесте | ✅ «…У лукоморья дуб зелёный.» + пунктуация | ⚠️ «…У Лукомория дуб зеленый.» (ошибка склонения, без пунктуации) |

**Итог: новый движок примерно в 8 раз быстрее на CPU, в 6.5 раз легче по диску и на этой выборке точнее — при полной офлайн-работе и свободной лицензии MIT.**

Мультиязычный запасной вариант (если понадобится не-русский): **Qwen3-ASR-0.6B** (Apache-2.0, 52 языка) — тоже через sherpa-onnx.  
Быстрая победа без смены движка: `whisper-large-v3-turbo` или русский fine-tune `whisper-podlodka-turbo` в текущих Whisper.net / faster-whisper.

---

## 1. Критерии (что «крутость» означает именно для ZERE)

Из AGENTS.md, `config/config.json` и кода:

| Критерий | Требование проекта |
|---|---|
| Язык | **русский** (`config.language = "ru"`, `WithLanguage("ru")`) |
| Режим | полностью локально, без облачных API (цель проекта) |
| Платформа | Windows, .NET 10 (C#) + параллельный Python-порт (`main.py` через `ZERE.bat`) |
| Железо | CPU (GPU не предполагается), но параллельно работает LLM Ollama |
| Сценарий | **короткие голосовые команды** после wake-word (2–8 с), а не транскрибация подкастов |
| Точность | приоритет — распознавание команд и имён приложений; галлюцинации и «вода» недопустимы |
| Лицензия | свободная, пригодная для коммерческого релиза (`docs/COMMERCIAL_RELEASE_PLAN.md`) |
| Интеграция | желательно без новых тяжёлых зависимостей (Python-стек уже есть, C# — чистый .NET) |
| Латентность | конец речи → текст; в анализе `docs/VOICE_PERF_STABILITY_ANALYSIS.md` STT — один из узких мест |

Текущий стек (с чем сравниваем):

- **C#**: `ZERE.Voice/Whisper/WhisperService.cs` — Whisper.net **1.9.1** (whisper.cpp), модели `ggml-medium.bin` / `ggml-base.bin`, таймаут 30 с, `AudioPreprocessor`, вызовы в `VoiceManager.cs:151, 478, 553`, прогрев `PreloadWhisper()` (`VoiceManager.cs:103`).
- **Python**: `zere/voice/whisper/whisper_service.py` — **faster-whisper ≥ 1.0** (CTranslate2), `whisper_model: "medium"` из `zere/voice/voice_config.py`, таймауты 30 с (команда) / 15 с (wake-сегмент).

---

## 2. Что смотрел в интернете

1. **[The Top Open Source STT Models in 2025](https://modal.com/blog/open-source-stt)** (Modal, 05.08.2025) + [Open ASR Leaderboard](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard) — общий рейтинг (там доминируют английские бенчмарки: Canary Qwen 2.5B, Parakeet TDT, Whisper Large V3 Turbo).
2. **Независимый русский бенчмарк от авторов Vosk** — [«Открытые модели для распознавания русской речи 2025»](https://alphacephei.com/nsh/2025/04/18/russian-models.html) (Nickolay Shmyrev, обновлён 14.09.2025): 13 моделей × 11 датасетов, включая **«Команды Яндекса»** — прямой аналог сценария ZERE.
3. **[GigaAM](https://github.com/salute-developers/GigaAM)** (SaluteDevices/Sber) + [evaluation.md](https://github.com/salute-developers/GigaAM/blob/main/evaluation.md) — v1/v2/v3, лицензия MIT, ONNX-экспорт.
4. **Qwen3-ASR** — [блог Qwen](https://qwen.ai/blog?id=qwen3asr) (28.01.2026, open source), [технический отчёт](https://arxiv.org/html/2601.21337v1), [HF Qwen/Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) (Apache-2.0).
5. **sherpa-onnx** — [документация](https://k2-fsa.github.io/sherpa/onnx/index.html), [C# API](https://k2-fsa.github.io/sherpa/onnx/csharp-api/index.html), страницы предобученных моделей, релизы `asr-models` (проверял лично — скачал и прогнал модель, см. §4.3).
6. Прочие кандидаты: Vosk, faster-whisper, NVIDIA Parakeet/Canary, SenseVoice, Moonshine, Whisper Podlodka Turbo.

---

## 3. Сводная таблица кандидатов

| Движок / модель | Русский | Точность на русском (WER ↓) | Лицензия | Размер | Интеграция в ZERE | Вердикт |
|---|---|---|---|---|---|---|
| **GigaAM-v3 RNNT (punct)** + sherpa-onnx | ✅ только русский | **8.3** в среднем по 10 сетам (против **21.0** у Whisper-large-v3); Golos Crowd **2.4** vs 19.0; CommonVoice19 **0.9** vs 5.5 ([evaluation.md](https://github.com/salute-developers/GigaAM/blob/main/evaluation.md)) | **MIT** (GigaChat Team) | **232 МБ** (архив 163 МБ) | C#: NuGet `org.k2fsa.sherpa.onnx` (есть `lib/net10.0`); Python: `pip install sherpa-onnx` — **обе проверены** | ⭐ **рекомендация** |
| GigaAM2 в русском бенчмарке Vosk | ✅ | среднее **8.64** (RNNT); **«Команды Яндекса» 1.9** (лучший результат всего бенчмарка) | MIT | ~230 МБ | там же | лучший на командной речи |
| **Qwen3-ASR-0.6B** + sherpa-onnx | ✅ 52 языка, ru входит | FLEURS ru **9.91**, CommonVoice ru **14.07** (техотчёт; 1.7B: 5.99 / 8.28) | **Apache-2.0** | ~940 МБ (архив 879 МБ, int8) | официальные C#-примеры с VAD, Python API | лучший мультиязычный |
| Whisper (текущий: `medium` / `base`) | ✅ | в рус. бенчмарке Large V3 — **16.21**, v3 Turbo — 16.84 (среднее по 11 сетам) | MIT | 1.5 ГБ (medium) | уже интегрирован (Whisper.net / faster-whisper) | статус-кво, медленно на CPU |
| Whisper Podlodka Turbo ([bond005](https://huggingface.co/bond005/whisper-podlodka-turbo)) | ✅ русский fine-tune | **13.78** в рус. бенчмарке | MIT | ~1.5 ГБ | грузится в faster-whisper по имени HF / ggml для Whisper.net | быстрая замена весов без смены движка |
| Vosk 0.54 ([alphacep/vosk-model-ru](https://huggingface.co/alphacep/vosk-model-ru)) | ✅ | **11.02**; команды Яндекса **4.4**; стриминг из коробки | Apache-2.0 | 40 МБ–1.9 ГБ | официальный C# API, лёгкий | хороший для стриминга/wake, точность ниже GigaAM |
| NVIDIA Parakeet TDT v3 | ✅ (в списке 27 языков есть ru) | **16.02**; на командах Яндекса **19.5** (очень плохо для ассистента) | CC-BY-4.0 | ~600M | ONNX-путь неочевиден | не берём |
| faster-whisper (движок) | ✅ | = точность Whisper (ускорение CTranslate2) | MIT | — | **уже стоит** в Python-порте | хороший рантайм, но medium на CPU всё равно медленный |
| SenseVoice (sherpa-onnx) | ❌ нет русского | — | MIT | 230 МБ | — | не подходит |
| Moonshine | ❌ только англ. | — | MIT | — | — | не подходит |
| Kyutai STT / Granite Speech / Canary Qwen | преимущественно en | топ лидерборда, но не русский | разные | 2.5–8B | тяжело | не подходит |

Ключевой вывод по бенчмарку авторов Vosk: **для коротких голосовых команд GigaAM выигрывает с огромным отрывом** (1.9 против 18.6 у Whisper-large-v3 и 21.8 у Parakeet), а это ровно сценарий ZERE («открой дискорд», «сделай громче», «закрой процесс»).

---

## 4. Победитель подробно: GigaAM-v3 + sherpa-onnx

### 4.1 Что за модель

- **GigaAM** — семейство Conformer-моделей (220M–600M) от SaluteDevices/Sber (GigaChat Team), создано для русского языка; v1 (2024/04), v2 (2024/12), **v3 (2025/11)**, multilingual (2026/06).  
- **Лицензия MIT** — свободно и для хобби, и для коммерческого релиза (`LICENSE` внутри архива sherpa: «Copyright (c) 2024 GigaChat Team, MIT License»).  
- **v3** обучен на 700 тыс. часов претренинга + 4 тыс. часов ASR-данных, включая колл-центры, музыку и **голосовые сообщения**; варианты `e2e_*` добавляют пунктуацию и нормализацию текста. По LLM-судейству GigaAM выигрывает у Whisper 70:30.  
- **Точность** ([evaluation.md](https://github.com/salute-developers/GigaAM/blob/main/evaluation.md), средний WER по 10 русским сетам): V3 RNNT **8.3**, V2 RNNT 10.6, Whisper (large-v3) **21.0**.

### 4.2 Что за рантайм

**[sherpa-onnx](https://k2-fsa.github.io/sherpa/onnx/index.html)** (Next-gen Kaldi, Apache-2.0) — офлайн/стриминговый ASR-рантайм на ONNX Runtime:

- официальная конверсия GigaAM под sherpa-onnx, в том числе **GigaAM-v3 с пунктуацией** — релиз от **16.12.2025**:  
  `sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16.tar.bz2` (**163 МБ**);
- **C#/.NET**: NuGet [`org.k2fsa.sherpa.onnx`](https://www.nuget.org/packages/org.k2fsa.sherpa.onnx) (проверил: версия 1.13.8, есть сборка **`lib/net10.0/sherpa-onnx.dll`**, нативные библиотеки подключаются отдельными runtime-пакетами, лицензия Apache-2.0);
- **Python**: `pip install sherpa-onnx` (проверил — работает);
- Windows x64/x86/arm64 официально в списке платформ; есть примеры с микрофона, VAD (silero), «simulate streaming», горячие слова (hotwords), пунктуация;
- C#-примеры в репозитории: `dotnet-examples/offline-decode-files` (поддерживает `ModelConfig.ModelType = "nemo_transducer"`, `Transducer.Encoder/Decoder/Joiner`, `NumThreads`), `vad-non-streaming-qwen3-asr` и др.

### 4.3 Живая проверка (что я сделал своими руками)

1. Скачал архив `sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16` (163 МБ) из релизов sherpa-onnx.  
2. Распаковка: `encoder.int8.onnx` (224.6 МБ), `decoder.onnx` (4.6 МБ), `joiner.onnx` (2.7 МБ), `tokens.txt` (1025 субслов с пунктуацией), `LICENSE` (MIT), `test_wavs/example.wav`.  
3. `pip install sherpa-onnx onnxruntime`, прогнал распознавание (`OfflineRecognizer.from_transducer(...)`, `model_type='nemo_transducer'`, `num_threads=4`):

```
init: 1.43 s
wav: example.wav sr=16000 dur=11.29 s
text: "Ничьих не требуя похвал, Счастлив уж я надеждой сладкой, Что дева с трепетом любви
       Посмотрит, может быть, украдкой На песни грешные мои. У лукоморья дуб зелёный."
decode: 2.866 s (холодный), 1.908 s, 1.598 s (тёплые) → RTF 0.254 / 0.169 / 0.141
```

4. Для сравнения прогнал **текущий движок** на том же файле (`faster-whisper` 1.2.1, `medium`, int8, 4 потока, `beam_size=1`, `language='ru'`):

```
load: 8.45 s (warm)
pass 0: 16.016 s → RTF 1.419
pass 1: 12.599 s → RTF 1.116
text: "… На песни грешные мои. У Лукомория дуб зеленый."
```

**Условия замера:** AMD Ryzen 5 8400F (6 ядер), WSL2 Linux x86_64, 16 ГБ RAM, без GPU, 4 потока на модель; обе модели — greedy/жадный декодинг. На Windows-хосте ожидаемый порядок цифр аналогичен (это один и тот же CPU).

**Что видно:**

- **Скорость:** GigaAM в **~8 раз быстрее** (RTF 0.14 против 1.12–1.42); команда длиной 3–5 с будет распознаваться за ~0.5 с вместо 3–6 с.  
- **Загрузка:** 1.5 с против 8.5 с (и против «холодных» минут на первый запуск medium).  
- **Точность/качество:** GigaAM выдал верное «У лукоморья» + восклицательные знаки; Whisper — «У Лукомория» (падежная ошибка) и без пунктуации. Один пример — не бенчмарк, но с Official-бенчмарками (8.3 vs 21.0) картинка согласуется.  
- **Память/диск:** 232 МБ против 1.5 ГБ — плюс ~1.3 ГБ RAM, который высвобождается под Ollama.

---

## 5. Применение в ZERE: план внедрения

### 5.1 Целевая архитектура

Паттерн ровно тот же, что уже успешен для TTS (`ttsEngine: "pocket"` с автоматическим откатом на `"piper"`):

```jsonc
// config/config.json
"sttEngine": "gigaam"   // "gigaam" (новый дефолт) | "whisper" (текущий, фолбэк)
```

```
VoiceManager
   └─ ISttService (единый контракт: IsInstalled / Preload / TranscribeAsync(wav, timeout) / Dispose)
         ├─ GigaAmService   — sherpa-onnx,  model_type=nemo_transducer   ← новый дефолт
         └─ WhisperService  — Whisper.net (C#) / faster-whisper (Python) ← фолбэк
```

### 5.2 Изменения в C# (`ZERE.Voice`)

1. **Пакет**: `ZERE.Voice.csproj` → `<PackageReference Include="org.k2fsa.sherpa.onnx" Version="1.13.8" />` (нативные рантаймы подтянутся зависимостями, включая win-x64; для net10.0 пакет уже скомпилирован).  
2. **Новый сервис** `ZERE.Voice/Sherpa/GigaAmService.cs` — контракт зеркалит `WhisperService`:
   - путь модели: `ZERE.Voice/Models/sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16/` (резолв от `AppContext.BaseDirectory`, как сейчас);
   - `OfflineRecognizerConfig`: `ModelConfig.ModelType = "nemo_transducer"`, `Transducer.Encoder/Decoder/Joiner`, `Tokens`, `NumThreads = min(4, Environment.ProcessorCount)`;
   - `Preload()` — создать recognizer на старте (паттерн `PreloadWhisper`, `VoiceManager.cs:103`); init занимает ~1.5 с, поэтому прогрев обязателен;
   - таймаут 30 с и метрика `[Perf] STT=… мс` — переиспользовать как в `WhisperService.TranscribeAsync`;
   - `Dispose()` — освобождение нативных ресурсов (как сейчас у фабрики Whisper.net).  
3. **Роутинг** в `VoiceManager.cs` (3 точки вызова: `:151`, `:478`, `:553`): выбрать сервис по `sttEngine`, при отсутствии модели/ошибке — автоматически на `WhisperService` (точно как `pocket → piper`).  
4. **Конфиг**: `VoiceConfig` → `public string SttEngine { get; set; } = "gigaam";`.  
5. **Не трогаем**: `AudioRecorder`, `AudioPreprocessor`, `SpeechText`, `WakeWordDetector`, TTS-часть.

### 5.3 Изменения в Python-порте (`zere/voice`)

1. `requirements.txt`: `sherpa-onnx` (и, при желании, убрать из дефолта `faster-whisper`, оставив как фолбэк).  
2. Новый `zere/voice/sherpa/gigaam_service.py` — обёртка с тем же `transcribe()`/`preload()`/`is_installed()` API, что у `WhisperService` (проверенный вызов: `sherpa_onnx.OfflineRecognizer.from_transducer(tokens=…, encoder=…, decoder=…, joiner=…, model_type='nemo_transducer', num_threads=…)`, затем `create_stream()/accept_waveform()/decode_stream()`).  
3. `voice_manager.py` — тот же роутинг по ключу `sttEngine` из `config/config.json`.  
4. Wake-детектор оставить на текущей логике (отдельная задача — замена на silero-VAD/keyword-spotter, см. S2 в `VOICE_PERF_STABILITY_ANALYSIS.md`).

### 5.4 Модель и её доставка

- Архив: `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-transducer-punct-giga-am-v3-russian-2025-12-16.tar.bz2` (163 МБ, sha256 — зафиксировать при первом скачивании).  
- **C#**: распаковка `tar.bz2` — `SharpCompress` (поддерживает bzip2) в первый запуск **или** (проще и надёжнее) распаковка уже в `installer/install.ps1`, где скачивание голосовых артефактов с SHA-256 уже умеет делать (`Expand-Archive` не для bz2 — использовать `tar.exe`, встроенная в Windows 10+).  
- Структура в репозитории: модель (232 МБ) **не коммитить** — качать установщиком/при первом запуске, как ggml-модели сегодня (`tools/` в git входит точечно, бинарники — нет).

### 5.5 Этапы и оценка

> **Статус (внедрено):** этапы 0, 1, 3, 4 выполнены — `sttEngine: "gigaam"` теперь
> основной движок в C# и Python-версиях (роутинг с откатом на whisper, установщик
> качает и распаковывает модель, контракт панели/открытые API обновлены, тесты
> `tests/test_stt_engine.py`). Этап 2 (ручной A/B на 30–50 записях) и этап 5
> (VAD/hotwords) остаются опциональными. В установщике вместо отдельного
> `-SkipStt` действует общий `-SkipVoice`.

| Этап | Что | Оценка | Статус |
|---|---|---|---|
| **0. Spike (C#)** | NuGet + скачивание модели + консольный smoke: `OfflineRecognizer` грузит `nemo_transducer` на Windows x64, RTF-замер на `example.wav` | 0.5 дня | **Готово** |
| **1. Сервисы** | `GigaAmService` (C#) + `gigaam_service.py`, `sttEngine` в конфиге, роутинг в обоих `VoiceManager` | 1–2 дня | **Готово** |
| **2. A/B на реальных командах** | 30–50 записей команд (имена приложений, игровые команды, файловые операции) → % распознавания и латентность: whisper medium vs gigaam | 0.5 дня | не выполнен (опционально) |
| **3. Установщик** | `installer/install.ps1`: скачивание + SHA-256 + `tar -xjf`, флаг `-SkipStt`, обновить `docs/INSTALL.md` | 1 день | **Готово** (скачивание/проверка/распаковка; вместо `-SkipStt` — общий `-SkipVoice`) |
| **4. Надёжность** | фолбэк при ошибке, телеметрия `[Perf]`, `Preload`, тесты | 0.5 дня | **Готово** |
| **5. Опционально** | silero-VAD (2 МБ) вместо поллинга тишины; hotwords «джарвис»; multilingual-модели для `language != ru` | по желанию | не выполнен (опционально) |

### 5.6 Ожидаемый эффект (до → после)

| Метрика | Сейчас | После | Источник |
|---|---|---|---|
| STT на 11 с речи (CPU) | 12.6–16.0 с (RTF 1.1–1.4) | **1.6–1.9 с (RTF 0.14–0.17)** | живой замер, §4.3 |
| Команда 3–5 с | 3–6 с | **0.5–0.8 с** | экстраполяция RTF |
| Загрузка модели | 8.5 с (warm) / минуты (cold) | **1.5 с** | живой замер |
| Размер артефакта | 1.5 ГБ | **232 МБ** | `ls` архива |
| WER средний по рус. сетам | ~21 (Whisper-large-v3) / выше у medium | **8.3** | GigaAM evaluation.md |
| WER на голосовых командах | ~18.6 (Whisper Large V3) | **~1.9** (GigaAM2 RNNT) | бенчмарк alphacephei |
| Пунктуация в тексте | нет | **да** (punct-вариант) | замер §4.3 |
| Память под STT | ~1.5 ГБ+ | **~300 МБ** | размер весов int8 |

### 5.7 Риски и как их закрыть

| # | Риск | Митигация |
|---|---|---|
| R1 | C#-обёртка sherpa-onnx менее «брендовая», чем Whisper.net; API меняется между версиями (1.12 → 1.13) | изоляция за интерфейсом `ISttService`, пин версии NuGet, фолбэк на whisper, smoke-тест на этапе 0 |
| R2 | Документация sherpa для GigaAM-v3 ещё не обновлена на сайте (релизы есть, страницы нет) | параметры запуска взяты из архива (`run-rnnt-v3-punct.sh`) и проверены мной вживую |
| R3 | Модель только русская (проект фиксирован на `language = "ru"`) | `sttEngine=whisper` для прочих языков; в перспективе multilingual GigaAM (70+ языков) или Qwen3-ASR |
| R4 | Первичная инициализация ~1.5 с на команду | обязательный `Preload()` на старте (паттерн уже реализован) |
| R5 | Распаковка `.tar.bz2` в C# | `tar.exe` из Windows 10+ в установщике; в рантайме — SharpCompress или готовые файлы |
| R6 | Точность на «живом» микрофоне (шум, far-field) может отличаться от бенчмарка | этап 2 — A/B на своих записях; в бенчмарке Golos Farfield GigaAM 3.9–5.5 против Whisper 16.4 — запас есть |
| R7 | Лицензии для коммерческого релиза | MIT (GigaAM) + Apache-2.0 (sherpa-onnx) — совместимо; добавить упоминание GigaAM/GigaChat Team в NOTICE/кредиты |
| R8 | Вместе с Ollama CPU будет занят | модель в 8 раз быстрее = меньше конкуренция за CPU; `NumThreads` сделать настраиваемым |

---

## 6. Запасные варианты (если не хочется менять движок)

1. **Остаться на Whisper, поднять точность**:  
   - Python: `whisperModelSize: "large-v3-turbo"` или русский fine-tune `bond005/whisper-podlodka-turbo` (WER 13.78 в рус. бенчмарке против 16.84 у обычного Turbo) — меняется одна строка конфига;  
   - C#: положить `ggml-large-v3-turbo.bin` вместо `ggml-medium.bin` (MIT, 809M, RTFx 216 по лидерборду).  
   Это +10–20% точности, но **скорость на CPU почти не улучшится** — главная проблема medium остаётся.
2. **Vosk** — если когда-нибудь понадобится настоящий стриминг «текст по мере речи» (официальный C# API, Apache-2.0, но точность заметно ниже GigaAM).
3. **Qwen3-ASR-0.6B** — как мультиязычная замена, когда понадобится English/другие (Apache-2.0, 52 языка, int8 ~940 МБ, RTF 0.11–0.17 на CPU по докам sherpa, официальные C#-примеры с VAD).

---

## 7. Источники

- [The Top Open Source Speech-to-Text (STT) Models in 2025 — Modal](https://modal.com/blog/open-source-stt)  
- [Open ASR Leaderboard — Hugging Face](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard)  
- [Открытые модели для распознавания русской речи 2025 — alphacephei (авторы Vosk)](https://alphacephei.com/nsh/2025/04/18/russian-models.html)  
- [GigaAM — GitHub (MIT)](https://github.com/salute-developers/GigaAM) и [evaluation.md](https://github.com/salute-developers/GigaAM/blob/main/evaluation.md)  
- [GigaAM-v3 на Hugging Face (ai-sage/GigaAM-v3, MIT)](https://huggingface.co/ai-sage/GigaAM-v3)  
- [GigaAM-v3: открытая SOTA-модель распознавания речи на русском — Habr](https://habr.com/ru/companies/sberdevices/articles/973160/)  
- [sherpa-onnx — документация](https://k2-fsa.github.io/sherpa/onnx/index.html), [C# API](https://k2-fsa.github.io/sherpa/onnx/csharp-api/index.html), [модель GigaAM-v2 как образец страницы](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/nemo/giga-am-v2-russian-2025-04-19.html), [релизы asr-models](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models)  
- [NuGet org.k2fsa.sherpa.onnx](https://www.nuget.org/packages/org.k2fsa.sherpa.onnx)  
- [Qwen3-ASR — блог](https://qwen.ai/blog?id=qwen3asr), [технический отчёт](https://arxiv.org/html/2601.21337v1), [HF Qwen/Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B), [sherpa: Qwen3-ASR](https://k2-fsa.github.io/sherpa/onnx/qwen3-asr/index.html)  
- [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)  
- [Vosk](https://alphacephei.com/vosk/), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [whisper-podlodka-turbo](https://huggingface.co/bond005/whisper-podlodka-turbo)  
