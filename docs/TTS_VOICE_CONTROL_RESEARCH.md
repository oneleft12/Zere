# Ресерч: лучший TTS с максимальными регулировками голоса

> **Статус на текущий момент.** Движок Piper заменён на ChatTTS (`zere/voice/chattts/`,
> `ZERE.Voice/ChatTts/`, сайдкар `tools/zere_chattts_server.py`); ChatTTS удалён в 1.9.0; актуальный TTS — `docs/TTS_SILERO.md`.
> Отчёт ниже сохранён как исторический: упоминания Piper и его замеры относятся к Piper-эпохе.

**Дата:** 2026  
**Цель:** подобрать локальный движок синтеза речи с максимальным набором регулировок голоса для проекта ZERE (Windows, .NET 10, полностью офлайн, язык — русский, низкая латентность, текущий стек: Piper + PocketTTS с клонированием).

---

## 1. Критерии «максимальных регулировок»

Что вообще можно регулировать в TTS — шкала от «полного» к «нулевому»:

| Уровень регулировки | Что даёт | Где доступно |
|---|---|---|
| **Темп (скорость)** | множитель скорости речи | почти все движки |
| **Паузы** | длина пауз между фразами/предложениями, SSML `<break>` | Piper, Bark, ChatTTS, SSML-совместимые |
| **Выразительность / шум** | вариативность интонации, «сухость» vs «живость» | Piper (noise_scale, noise_w), поколенческие параметры (temperature/top_p) |
| **Эмоции** | happy / angry / sad / calm… как отдельные слайдеры или промпты | IndexTTS-2 (8 слайдеров), CosyVoice (текстовая инструкция), XTTS v2 (огранич.), Bark (маркеры в тексте), ChatTTS (токены) |
| **Текстовое описание голоса (text-prompt)** | пол, высота, тембр, темп, фоновый шум, реверберация словами | **Parler-TTS** (самый полный набор), CosyVoice Instruct |
| **Клонирование голоса** | свой тембр из референса 3–12 c | PocketTTS (уже есть), XTTS v2, F5-TTS, Fish Speech, IndexTTS, CosyVoice, MARS5 |
| **Точный питч (Hz)** | изменение высоты тона без изменения скорости | **ни один** встроенный движок не даёт; только DSP-постобработка (RubberBand/FFmpeg, NAudio, SoX) |
| **Громкость / тембр / EQ** | громкость, эквалайзер, реверб | только постобработка аудиопотока |

**Вывод №1:** «максимальные регулировки» = связка **(выразительный движок) + (универсальный DSP-слой постобработки)**. Ни один движок не даёт питч в герцах и полный EQ — это обязательно свой слой поверх любого TTS.

**Вывод №2:** для русского языка выбор сильно уже, чем для английского. Контролируемые по эмоциям лидеры (Parler-TTS, IndexTTS-2, ChatTTS, StyleTTS2) русский **не поддерживают**.

---

## 2. Сводная таблица движков

Латентность/память — замеры [Contra Collective](https://contracollective.com/blog/kokoro-vs-piper-vs-xtts-local-text-to-speech-m5-max-2026) (M5 Max; на Windows/NVIDIA порядок аналогичный).

| Движок | Русский | Клонирование | Регулировки голоса | Латентность 1-го звука | Память | Лицензия |
|---|---|---|---|---|---|---|
| **Piper** (текущий fallback) | ✅ irina, ruslan | ❌ | `length_scale` (темп), `noise_scale` (выразительность), `noise_w` (вариативность фонем), `sentence_silence` (паузы), `speaker_id` | ~40 мс, RTF 0.03 | ~300 МБ | MIT |
| **PocketTTS** (текущий основной) | ✅ | ✅ | клон + базовые параметры сервера | ~150–700 мс | — | своя (xVibePocketTTS) |
| **XTTS v2** (coqui-tts форк) | ✅ (1 из 17) | ✅ 6–12 c | `speed`, `emotion` (рабочо mainly en), temperature/top_p/entropy, язык, speaker embedding | ~600 мс, RTF 0.34 | ~4.5 ГБ | CPML (некоммерч.) |
| **CosyVoice / CosyVoice2-0.5B** | ✅ (9 яз.) | ✅ | **Instruct**: эмоция, темп, громкость, диалект — текстовой инструкцией; клонирование | средняя | ~2–4 ГБ | MIT |
| **Fish Speech / OpenAudio S1** | ⚠️ tier-2 | ✅ | клон, поколенческие параметры, S2-инструкции | средняя | ~4 ГБ (S1: 4B) | желательно проверить (S1 — research) |
| **Bark (Suno)** | ✅ | ⚠️ history-prompt / эмбеддинг | эмоции текстом: `[laughs]`, `[sighs]`, паузы, музыка/фон; temperature драматично влияет на подачу | высокая (недетерминированная AR) | ~4–8 ГБ | MIT |
| **ChatTTS** | ❌ (zh/en) | ❌ (5 спикеров) | control-токены: `[laugh]`, `[break]`, параметры `oral` (разговорность), `laugh`, `break`, `seed` | низкая | ~2 ГБ | CC-BY-NC |
| **Parler-TTS (mini v1.1 / large v1)** | ❌ (en) | ❌ | **самый полный текстовый промпт**: пол, **pitch**, **speaking rate**, фоновый шум, реверберация, акцент, тембр — словами | средняя (2.2B / mini ~890M) | 2–5 ГБ | веса — некоммерч., проверять |
| **IndexTTS-2 / 2.5** | ❌ (zh/en/ja/es/ar) | ✅ | **8 слайдеров эмоций**: happy, angry, sad, afraid, disgusted, melancholic, surprised, calm + эмоция из аудио-референса + текстовое описание эмоции | высокая (тяжёлый GPU) | ~6–10 ГБ | AGPL (проверить) |
| **Kokoro-82M** | ❌ | ❌ | `speed` + 54 готовых голоса, 24 кГц | ~90 мс, RTF 0.08 | ~900 МБ | Apache 2.0 |
| **Silero TTS v5** | ✅ | ❌ | мало (быстрый, старый) | очень низкая | <500 МБ | MIT (.modelo) |
| **StyleTTS2** | ❌ (en) | Style-vector из референса | прозодия через style vector, очень естественный en | низкая | ~2 ГБ | MIT |
| **MARS5 (CambAI)** | ⚠️ | ✅ 5 c | сильный контроль прозодии: пунктуация, паузы, стопы через BPE-токенизатор; inference_time_ratio (темп) | средняя | ~2–3 ГБ | некоммерч. — проверить |
| **dots.tts (RedNote)** | ⚠️ (100+ яз., проверить ru) | ✅ | zero-shot клон, live-стриминг, 2B, есть портативная Windows-сборка [DotsTTS-Studio](https://github.com/timoncool/DotsTTS-Studio) | низкая (стриминг) | ~4 ГБ GPU | проверить |
| **OuteTTS-0.3-1B** | ⚠️ | ❌ | LLM-архитектура, набор спикеров, слабые регулировки | средняя | ~2 ГБ | Apache |
| **Higgs Audio v3** | ✅ | ✅ | клон, портативный Windows-движок ([Higgs-Ultimate](https://github.com/timoncool/Higgs-Ultimate), офлайн, рус. интерфейс) | средняя | GPU | проверить |
| **sherpa-onnx** (обёртка) | ✅ (через VITS/Piper/Kokoro модели) | ❌ | единый ONNX-раннер для C#/C++, стриминг | низкая | как у модели | MIT |
| **SAPI5 / Windows.Media** | ✅ | ❌ | rate/pitch/volume, но «робот» | нулевая | — | системная |

---

## 3. Детальные регулировки по ключевым движкам

### 3.1 Piper (текущий fallback) — максимум из того, что уже есть
В `PiperService`/`zere_tts_server.py` стоит передавать и обнавлять в конфиге:
- **`length_scale`** — темп (1.0 = норма; 0.8 = быстрее; 1.2 = медленнее) ([gh-issue #714](https://github.com/rhasspy/piper/issues/714), [piper-plus](https://github.com/ayutaz/piper-plus/blob/dev/README_EN.md))
- **`noise_scale`** — выразительность интонации (по умолчанию ~0.667; выше → живее, ниже → ровнее)
- **`noise_scale_w`** — вариативность длины фонем (default 0.8; влияет на «суетливость»)
- **`sentence_silence`** — пауза между предложениями
- **`speaker_id`** — выбор голоса (русские: `ru_RU-irina-medium`, `ru_RU-denis-medium`, `ru_RU-ruslan-medium` — [список](https://quick-tts.com/ru/blog/luchshie-russkie-golosa-tts-2026.html))
- Питча нет — только постобработка.

### 3.2 XTTS v2 — клонирование + русский + emotion/speed
- 17 языков, **русский входит** ([HF](https://huggingface.co/coqui/XTTS-v2)).
- `tts.tts_to_file(..., emotion="Happy", speed=1.5)` — emotion реально работает не на всех языках (обсуждение: [HF discussion](https://huggingface.co/coqui/XTTS-v2/discussions/19)).
- Проект Coqui брошен, форк поддерживается пакетом **`coqui-tts`** ([semenov.work](https://semenov.work/posts/voice-cloning)).
- Минус: ~600 мс до первого звука, 4.5 ГБ — для живого диалога ZERE тяжело; годится как «медленный премиум-режим».

### 3.3 CosyVoice — лучшее соотношение «инструкции + русский»
- **Instruct-режим**: управление **эмоцией, темпом, громкостью, диалектом** текстовой инструкцией («говори мягко и медленно, с лёгкой грустью») ([GitHub](https://github.com/FunAudioLLM/CosyVoice)).
- Русский — один из 9 поддерживаемых языков ([cosyvoice.org](https://cosyvoice.org/multilingual-tts)).
- CosyVoice2-0.5B компактнее, пригоднее для стриминга.

### 3.4 Parler-TTS — эталон «максимальных регулировок», но только EN
- Управление текстовым описанием: пол, **высота голоса (pitch)**, **темп (speaking rate)**, фоновый шум, реверберация, акцент ([HF mini](https://huggingface.co/parler-tts/parler-tts-mini-v1.1), [large](https://huggingface.co/parler-tts/parler-tts-large-v1)).
- Для ZERE важен как **референс архитектуры**: описательный промпт-слой. Русский не поддерживает — как отдельный движок не подходит.

### 3.5 IndexTTS-2 — эталон эмоциональных слайдеров, но только zh/en/ja/es/ar
- Клонирование + **8 независимых слайдеров эмоций** (happy, angry, sad, afraid, disgusted, melancholic, surprised, calm), плюс эмоция из второго аудио-референса и текстовое описание эмоции ([localaimaster](https://localaimaster.com/blog/indextts-2-setup-guide), [DEV-review](https://dev.to/czmilo/indextts2-comprehensive-review-in-depth-analysis-of-2025s-most-powerful-emotional-speech-synthesis-model-1m9e)).
- Нет русского → для ZERE применимо только к клонированным коротким фразам/EN-контенту.

### 3.6 ChatTTS — тонкие разговорные регуляторы (без русского)
- Control-токены в тексте: `[laugh]`, `[break]` + параметры `oral` (степень разговорности), `laugh`, `break`, `seed` ([GitHub](https://github.com/2Noise/ChatTTS)).
- Хорошая модель для «живой» подачи, но zh/en.

### 3.7 Bark — эмоции прямо в тексте (русский есть)
- Маркеры `[laughs]`, `[sighs]`, паузы, музыка; голос через history-prompt ([DeepWiki](https://deepwiki.com/suno-ai/bark/4-voice-customization)); температура сильно меняет подачу.
- Минус: медленный и недетерминированный — для ассистента в реальном времени не годится, годится для «красивых» редких фраз.

### 3.8 Kokoro-82M — лучшее качество/скорость, но **русского нет**
- 82M, Apache 2.0, 54 голоса, ~90 мс до звука ([HF](https://huggingface.co/hexgrad/Kokoro-82M)). Полезен только для EN-стриминга; для ZERE (ru) — не вариант.

### 3.9 dots.tts — новый игрок
- 2B, fully-continuous AR, клонирование, live-стриминг, 100+ языков, WER 0.94/1.30% (zh/en), SIM 81+ ([GitHub](https://github.com/rednote-hilab/dots.tts), [демо](https://rednote-hilab.github.io/dots.tts-demo/)). Есть готовая портативная Windows-сборка. Проверить наличие русского и лицензию.

### 3.10 MARS5 — тонкая прозодия
- Контроль через пунктуацию и паузы, клон с ~5 сек, `inference_time_ratio` для темпа ([MarkTechPost](https://www.marktechpost.com/2024/06/26/camb-ai-releases-mars5-tts-a-novel-open-source-text-to-speech-model-for-insane-prosody)).

---

## 4. Слой постобработки — где берутся «недостающие» регулировки

Ни один движок не даёт прямого control над питчем в Hz. Единый DSP-слой (в `StreamPlayer`/`AudioPlayer` или в `zere_tts_server.py`) даёт **максимальный** набор поверх любого TTS:

| Регулировка | Реализация |
|---|---|
| **Питч (± тоны)** независимо от темпа | **Rubber Band** через FFmpeg (`rubberband=pitch=...`) ([ffmpeg docs](https://ayosec.github.io/ffmpeg-filters-docs/5.1/Filters/Audio/rubberband.html)); в C# — NAudio DMO PitchShift или SoundTouch.NET |
| **Темп** независимо от питча | тот же RubberBand / SoundTouch |
| **Громкость, EQ, реверб, компрессия** | NAudio DSP / SoX ([ovos sox-plugin](https://github.com/OpenVoiceos/ovos-tts-transformer-sox-plugin) — референс идеи «transformer после TTS») |
| **SSML-совместимый API** | внешний обработчик: `<prosody rate pitch volume>`, `<break time>`, `<emphasis>` → маппинг на параметры движка + DSP |
| Паузы между предложениями | у Piper — `sentence_silence`, у остальных — вставка тишины в поток |

---

## 5. Рекомендации для ZERE

### Архитектура: 3 уровня регулировок
1. **Уровень движка** — экспозировать в `config.json`/`VoiceConfig` все нативные параметры:
   - Piper: `lengthScale`, `noiseScale`, `noiseScaleW`, `sentenceSilence`, `speakerId` (уже почти есть);
   - PocketTTS: клонирование (есть) + параметры генерации сервера;
   - новый движок (см. ниже): свои слайдеры (эмоции/инструкции).
2. **Уровень текста** — `SpeechText` → mini-SSML: разметка пауз, «тихая/громкая» подача, эмоциональные маркеры, проброс в движок, который их понимает.
3. **Уровень DSP** — постобработка PCM-потока в `StreamPlayer`: питч, темп, громкость, EQ — **универсально для всех движков**.

### Движок — что добавить к существующему стеку
| Роль | Кандидат | Почему |
|---|---|---|
| **Основной (ru, выразительный)** | **Fish Speech S2** (приоритет), CosyVoice2 — запасной | Fish: chunked streaming, лучший Time-to-First-Audio; CosyVoice: instruct-эмоции, но требует промпт перед синтезом (задержка) |
| **Альтернатива ru + emotion** | **XTTS v2** (coqui-tts) | русский, клон, `speed`/`emotion`; тяжёлый и медленный — как «премиум»-режим |
| **Fallback (текущий)** | **Piper** | 40 мс, дешёвый, полные noise/length-регуляторы |
| **Клонирование (текущий)** | **PocketTTS** | оставить |
| **Экспериментальный (макс. эмоции)** | **IndexTTS-2** / **dots.tts** | слайдеры эмоций / новый класс модели; проверить ru |
| **Постобработка** | FFmpeg RubberBand + NAudio | питч/темп/EQ — «максимальные регулировки» на любом движке |

### Практические выводы
1. **Абсолютный максимум регулировок** даёт связка: *выразительный движок с клонированием и эмоциями (Fish Speech S2 / CosyVoice-подобный instruct) + DSP-слой (питч/темп/EQ) + структурные разметки пауз*. По отдельности ни один движок полного набора не даёт.
2. Для **русского** в первую очередь смотреть на: CosyVoice (9 яз., instruct), XTTS v2 (ru, emotion/speed), Fish Speech (ru tier-2), Bark (ru, медленный), Piper (ru, 4 голоса), Silero (ru, быстрый).
3. **Latency-бюджет ZERE**: первый звук должен быть <300 мс → Piper (~40 мс) и Kokoro-класс (~90 мс) укладываются; XTTS/Fish/IndexTTS требуют либо GPU, либо «стриминг попредложенно» (уже реализовано в `StreamPlayer`).
4. Параллельно с выбором движка — **зашить в `VoiceConfig` универсальную модель параметров**: `speed`, `pitchSemis`, `volumeDb`, `expressiveness`, `emotion`, `sentencePause`, `eqPreset` — и маппить их на конкретный движок (+ DSP-фоллбэк для недостающих). Тогда переключение движка не ломает настройки пользователя.
5. Лицензии: Piper/Kokoro/CosyVoice — свободные; **XTTS v2 — CPML (некоммерч.)**, Parler/IndexTTS/ChatTTS — некоммерческие веса — для некоммерческого ZERE ок, но проверить перед распространением.

---

## 6. Архитектурные инсайты (после ревью)

### 6.1 DSP-слой и стриминг: Overlap-Add / Cross-fade
Питч-шифтинг маленьких чанков на лету даёт фазовые сдвиги и щелчки на стыках. Требования к реализации в `StreamPlayer`:
- **Overlap-Add (OLA)** или cross-fade при склейке чанков;
- **Плавный переход при изменении параметров на лету** (пользователь крутит слайдер во время речи): fade-in/out старого и нового DSP-потоков на отрезке **~50–100 мс**;
- Для real-time чанков предпочтительнее **SoundTouch** (быстрее RubberBand, лучше для чанков) в связке с **NAudio**; RubberBand — эталон качества для офлайн-обработки.

### 6.2 Уровень текста: LLM генерирует mini-SSML сам
Полноценный SSML тяжёлый и LLM его плохо держит. Вместо него — лёгкий токен-синтаксис в самом промпте:

> *«При ответе используй теги: `[emotion=sarcastic]`, `[pause=500ms]`, `[speed=1.2]`. Пример: `[emotion=calm]Сэр, система в порядке.[pause=300ms][emotion=alert]Но я засек аномалию.»*

Pipeline в .NET:
1. **Regex-парсер** разбивает ответ LLM на массив `SpeechChunk { Text, Emotion, SpeedMultiplier, PauseMs }`;
2. чанки батчами уходят в движок (Python-сервис или ONNX-раннер), параметры чанка пробрасываются в DSP-слой;
3. старые чанки с уже начатым синтезом не пересинтезируются — параметры применяются от следующего чанка.

### 6.3 Рейтинг основного движка: Fish Speech S2 — фаворит наравне с CosyVoice2
- **Fish Speech S2** заточен под **chunked streaming inference** → лучший Time-to-First-Audio, критично для бюджета <300 мс; сильное клонирование с коротких референсов без потери просодии.
- **CosyVoice2 Instruct** часто требует аудио-/текстовый промпт перед синтезом → добавляет задержку до первого звука.
- Итог: **Fish S2 — основной кандидат**, CosyVoice2 — запасной (instruct-инструкции).

### 6.4 Альтернатива Python-микросервису: ONNX Runtime in-process
Вместо «зоопарка» `zere_tts_server.py` (Python + FastAPI + PyTorch) для **fallback-движков**:
- **Piper** и **Silero TTS v5** конвертируются в `.onnx`;
- в .NET 10 — нативный пакет **`Microsoft.ML.OnnxRuntime`**: запуск прямо в C#-процессе ZERE, **без IPC-оверхеда** (HTTP/gRPC), выигрыш **20–50 мс**, деплой без Python-окружения и гигабайт весов PyTorch;
- тяжёлые выразительные движки (Fish/CosyVoice/XTTS) остаются на Python-сервисе — ONNX-путь только для лёгких/фоллбэков.

### 6.5 Universal VoiceProfile: паттерн Strategy + Adapter

```csharp
public record VoiceProfile
{
    // Базовые (уходят в DSP)
    public float PitchSemitones { get; init; }   // -12 .. +12
    public float VolumeDb { get; init; }

    // Движковые (маппятся адаптерами)
    public float SpeedMultiplier { get; init; }  // 0.5 .. 2.0
    public string Emotion { get; init; }         // "neutral", "happy", "angry"…
    public float Expressiveness { get; init; }   // 0.0 .. 1.0 → noise_scale (Piper), temperature (Fish)
}

public interface ITtsEngineAdapter
{
    Task<byte[]> SynthesizeAsync(string text, VoiceProfile profile);
}
```

Принцип: если движок не умеет параметр (например питч) — адаптер отдаёт чистый PCM, а `AudioStreamPlayer` применяет SoundTouch на уровне .NET. **Пользователь не замечает разницу при переключении движков.**

### 6.6 Лицензии для публичного релиза
- **Релиз-дружелюбные**: Piper (MIT), CosyVoice2 (MIT), Kokoro (Apache 2.0), Silero;
- **Только local test mode** (пользователь сам качает веса): XTTS v2 (CPML), Parler-TTS, IndexTTS, ChatTTS — выпилить или изолировать за переключателем «локальное тестирование».

### 6.7 Дорожная карта внедрения

| # | Шаг | Даёт | Зависимости |
|---|---|---|---|
| **1** | `VoiceProfile` + `ITtsEngineAdapter` (Strategy+Adapter), маппинг на Piper/PocketTTS | универсальная модель настроек, движки взаимозаменяемы | — |
| **2** | DSP-слой в `StreamPlayer`: SoundTouch + NAudio, OLA/cross-fade 50–100 мс, live-переключение параметров | **питч/темп/громкость для любого движка — мгновенный UX-вин** ещё до интеграции новых движков | шаг 1 |
| **3** | Расширить `VoiceConfig`/конфиг: `pitchSemis`, `volumeDb`, `expressiveness`, `emotion`, `sentencePause`; команда «настройки голоса» в консоли | пользователь настраивает голос «под себя» | шаг 1 |
| **4** | Mini-SSML: regex-парсер `SpeechChunk[]` + системный промпт для LLM (`[emotion=..] [pause=..] [speed=..]`) | эмоции/паузы прямо из ответа LLM | шаг 1 |
| **5** | Экспозировать Piper-регуляторы (`lengthScale`, `noiseScale`, `noiseScaleW`, `sentenceSilence`) в `zere_tts_server.py` | больше контроля на текущем fallback | — |
| **6** | Интеграция Fish Speech S2 (основной выразительный, Python-сервис) | клонирование + стриминг + ru | шаги 1–4 |
| **7** | (опц.) ONNX Runtime: Piper/Silero in-process через `Microsoft.ML.OnnxRuntime` | фоллбэк без Python, −20–50 мс | шаг 1 |
| **8** | (опц.) IndexTTS-2 / dots.tts как экспериментальный «эмоциональный» режим | максимум эмоций | отдельный флаг |

**Самый быстрый вин**: шаги 1+2+3 — уже без единого нового движка пользователь получает питч, темп, громкость и сохранённый профиль голоса.

---

## 7. Источники

- [Kokoro vs Piper vs XTTS v2: Local TTS on M5 Max (2026) — Contra Collective](https://contracollective.com/blog/kokoro-vs-piper-vs-xtts-local-text-to-speech-m5-max-2026)
- [12 Best Open-Source TTS Models Compared (2025) — Inferless](https://www.inferless.com/learn/comparing-different-text-to-speech---tts--models-part-2)
- [The 6 Best On-Device TTS Models — GetStream](https://getstream.io/blog/best-on-device-tts-models)
- [Piper: Speed control — issue #714](https://github.com/rhasspy/piper/issues/714) · [piper-plus options](https://github.com/ayutaz/piper-plus/blob/dev/README_EN.md) · [Piper VOICES (piper1-gpl)](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md)
- [Русские голоса TTS 2026 (Piper) — Quick TTS](https://quick-tts.com/ru/blog/luchshie-russkie-golosa-tts-2026.html)
- [hexgrad/Kokoro-82M — Hugging Face](https://huggingface.co/hexgrad/Kokoro-82M)
- [coqui/XTTS-v2 — Hugging Face](https://huggingface.co/coqui/XTTS-v2) · [Emotions discussion](https://huggingface.co/coqui/XTTS-v2/discussions/19) · [Voice cloning with coqui-tts](https://semenov.work/posts/voice-cloning)
- [FunAudioLLM/CosyVoice — GitHub](https://github.com/FunAudioLLM/CosyVoice) · [Multilingual TTS (ru)](https://cosyvoice.org/multilingual-tts)
- [parler-tts-mini-v1.1](https://huggingface.co/parler-tts/parler-tts-mini-v1.1) · [parler-tts-large-v1](https://huggingface.co/parler-tts/parler-tts-large-v1)
- [IndexTTS-2 setup: emotion sliders — Local AI Master](https://localaimaster.com/blog/indextts-2-setup-guide) · [IndexTTS2 review — DEV](https://dev.to/czmilo/indextts2-comprehensive-review-in-depth-analysis-of-2025s-most-powerful-emotional-speech-synthesis-model-1m9e) · [index-tts GitHub](https://github.com/index-tts/index-tts)
- [2Noise/ChatTTS — GitHub](https://github.com/2Noise/ChatTTS)
- [suno-ai/bark: Voice customization — DeepWiki](https://deepwiki.com/suno-ai/bark/4-voice-customization) · [Coqui Bark docs](https://docs.coqui.ai/en/latest/models/bark.html)
- [fishaudio/fish-speech — GitHub](https://github.com/fishaudio/fish-speech) · [OpenAudio S1](https://openaudio.com/blogs/s1) · [Fish Audio S2 tech report](https://arxiv.org/html/2603.08823v1)
- [rednote-hilab/dots.tts — GitHub](https://github.com/rednote-hilab/dots.tts) · [DotsTTS-Studio (Windows)](https://github.com/timoncool/DotsTTS-Studio) · [демо dots.tts](https://rednote-hilab.github.io/dots.tts-demo/)
- [CambAI MARS5 — MarkTechPost](https://www.marktechpost.com/2024/06/26/camb-ai-releases-mars5-tts-a-novel-open-source-text-to-speech-model-for-insane-prosody)
- [Silero TTS v5 на русском — Хабр](https://habr.com/ru/articles/961930/)
- [OuteAI/OuteTTS-0.3-1B](https://huggingface.co/OuteAI/OuteTTS-0.3-1B/blob/main/README.md)
- [Higgs-Ultimate (Windows, офлайн)](https://github.com/timoncool/Higgs-Ultimate)
- [sherpa-onnx TTS docs](https://k2-fsa.github.io/sherpa/onnx/tts/index.html) · [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- [FFmpeg RubberBand filter](https://ayosec.github.io/ffmpeg-filters-docs/5.1/Filters/Audio/rubberband.html) · [ovos-tts-transformer-sox-plugin](https://github.com/OpenVoiceos/ovos-tts-transformer-sox-plugin)
- [Pipecat: Kokoro streaming](https://docs.pipecat.ai/api-reference/server/services/tts/kokoro) · [docker-kokoro API](https://github.com/hwdsl2/docker-kokoro)
- [TTS comparison (XTTS/Bark/Kokoro/Fish/MeloTTS) — Clore](https://docs.clore.ai/guides/guides_v2-ru/sravneniya/tts-comparison)
- [Open-Source TTS Latency Benchmark — Picovoice](https://picovoice.ai/docs/benchmark/tts/)
