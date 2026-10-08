# Модели слова-триггера (wake word)

Сюда кладётся обученная модель KWS: `wake_<слово>.onnx` + манифест
`wake_<слово>.json` (слово транслитерируется в латиницу: «зере» → `wake_zere.onnx`).

Почему папка в репозитории, а не в `ZERE.Voice/Models/`: файл весит
**меньше 1 МБ**, поэтому он коммитится вместе с кодом — установщику не нужны
ни скачивание, ни SHA-256 (в отличие от моделей Whisper/GigaAM). Это же
значит, что обе редакции (Python и C#) читают один и тот же файл.

Контракт модели (его проверяет `tools/wake_word/self_test.py`):

| | |
|---|---|
| вход | `audio`, float32, `(batch, 16000)` — 1.0 с при 16 кГц, значения [-1, 1] |
| выход | `score`, float32, `(batch, 1)` — вероятность слова в окне |
| frontend | внутри графа (STFT → мел → лог → пер-оконная нормализация) |
| рантайм | onnxruntime на CPU: Python — `zere/voice/wakeword/kws_detector.py`, C# — `ZERE.Voice/WakeWord/KwsWakeWordDetector.cs` |

Как получить модель — `tools/wake_word/README.md` и `docs/WAKE_WORD.md`:

```bash
python -m tools.wake_word.record_positives --count 100
python -m tools.wake_word.synth_positives --count 3000
python -m tools.wake_word.build_negatives --from-dir D:\audio\room
python -m tools.wake_word.train --device cuda
```

Пока файла модели здесь нет, ZERE работает на прежнем детекторе слова-триггера
(энергетический VAD + STT + нечёткое сравнение строк) и пишет предупреждение в
консоль. Переключение — ключ `wakeEngine` в `config/config.json`:
`auto` (KWS, если модель есть) | `kws` | `whisper`.
